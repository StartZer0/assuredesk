const $ = id => document.getElementById(id);
let me, book, running = new Map();
const answers = ['Yes', 'No', 'Partial', 'Not applicable', 'Unknown', 'Declined'];
function node(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function message(text) { $('message').textContent = text; }
async function api(path, method = 'GET', body) {
  const headers = {};
  if (method !== 'GET') {
    headers['X-CSRF-Token'] = me?.csrf || '';
    headers['Idempotency-Key'] = crypto.randomUUID();
  }
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'; body = JSON.stringify(body);
  }
  const r = await fetch('/v1' + path, {method, headers, body});
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || 'Request could not be completed');
  return data;
}
function action(text, fn, cls = 'secondary') {
  const b = node('button', text, cls);
  b.type = 'button';
  b.onclick = async () => {
    b.disabled = true;
    try { await fn(); } catch (e) { message(e.message.replaceAll('_', ' ')); }
    finally { b.disabled = false; }
  };
  return b;
}
async function books() {
  $('books').replaceChildren();
  for (const b of await api('/questionnaires')) {
    $('books').append(action(`${b.account.toUpperCase()} · ${b.as_of}${b.confirmed ? '' : ' · preview'}`, () => load(b.id)));
  }
}
async function session() {
  me = await api('/me');
  $('login').hidden = true; $('workspace').hidden = false;
  $('identity').textContent = `${me.name} · ${me.roles.join(', ')}`;
  $('accounts').replaceChildren(...me.accounts.map(a => { const o = node('option', a); o.value = a; return o; }));
  $('source-form').hidden = !me.roles.includes('security_reviewer');
  $('upload-form').elements.as_of.value = new Date().toISOString().slice(0, 10);
  $('source-form').elements.valid_from.value = new Date().toISOString().slice(0,10);
  $('source-form').elements.valid_until.value = '2027-12-31';
  await books();
}
async function evidence(id) {
  const e = await api(`/evidence/${id}?workbook_id=${book.id}`);
  $('evidence-title').textContent = e.title;
  $('evidence-meta').textContent = `${e.locator} · ${e.disclosure} · valid until ${e.expires}`;
  $('evidence-text').textContent = e.context;
  $('evidence').showModal();
}
async function load(id) { book = await api('/questionnaires/' + id); render(); }
function render() {
  const root = $('review'); root.replaceChildren();
  root.append(node('h2', `${book.account.toUpperCase()} questionnaire`), node('p', `As of ${book.as_of} · ${book.questions.length} questions`));
  if (!book.confirmed) {
    root.append(node('p', 'Check every extracted ID and question below against the uploaded sheet. Confirm only when this mapping is correct.'), node('pre', JSON.stringify(book.mapping, null, 2)),
      action('Confirm this mapping', async () => { await api(`/questionnaires/${book.id}/mapping`, 'POST'); await load(book.id); await books(); }, ''));
  }
  const exportButton = action('Preview approved export', async () => {
    const preview = await api(`/questionnaires/${book.id}/preview`);
    const panel = node('section'); panel.append(node('h3', `${preview.count} approved rows`));
    for (const row of preview.rows) panel.append(node('p', `${row.answer_cell}: ${row.answer} · ${row.explanation_cell}: ${row.explanation}`));
    panel.append(action('Create export', async () => {
    const x = await api(`/questionnaires/${book.id}/exports`, 'POST');
    const link = node('a', 'Download approved workbook'); link.href = `/v1/exports/${x.id}/download`;
    panel.append(link); message('Export ready. Download rechecks all approvals and permissions.');
    }, '')); root.prepend(panel);
  }, '');
  exportButton.disabled = !book.confirmed || book.questions.some(q => !q.draft?.approved || q.blocked);
  root.append(exportButton);
  for (const q of book.questions) {
    const card = node('section', undefined, 'question');
    card.append(node('h3', `${q.key} · ${q.text}`));
    card.append(node('p', `Question ${q.coordinates.question_col} → response ${q.coordinates.answer_col}, explanation ${q.coordinates.explanation_col}. Allowed: ${answers.join(', ')}.`, 'muted'));
    card.append(action('Revision and decision history', async () => {
      const h = await api(`/questions/${q.id}/history`);
      $('evidence-title').textContent = `${q.key} history`; $('evidence-meta').textContent = 'Authorized revisions and decisions';
      $('evidence-text').textContent = [...h.questions.map(v => `Question revision ${v.revision}: ${v.text}`), ...h.drafts.map(d => `Answer revision ${d.revision}: ${d.answer}. ${d.explanation}`), ...h.events.map(e => `${new Date(e.created*1000).toLocaleString()} ${e.action}: ${e.details.reason || ''}`)].join('\n\n');
      $('evidence').showModal();
    }));
    const questionEdit = node('details'); questionEdit.append(node('summary', 'Correct question text'));
    const questionText = node('textarea'); questionText.value = q.text; questionText.rows = 3;
    questionText.setAttribute('aria-label', 'Question text');
    questionEdit.append(questionText, action('Save question correction', async () => {
      await api(`/questions/${q.id}`, 'PATCH', {expected_revision:q.revision,text:questionText.value});
      await load(book.id); message('Question updated. A new answer and approval are required.');
    })); card.append(questionEdit);
    card.append(node('p', q.blocked ? 'Blocked for review' : q.draft?.approved ? 'Approved' : q.draft?.supported ? 'Support checked · human review needed' : 'Human review needed', 'badge'));
    if (q.run) {
      const trace = node('details'); trace.append(node('summary', `Retrieval: ${q.run.status.replaceAll('_',' ')} · ${q.run.rounds} rounds`));
      if (q.run.stop_reason) trace.append(node('p', q.run.stop_reason.replaceAll('_',' ')));
      for (const requirement of q.run.requirements) trace.append(node('p', `${requirement.coverage}: ${requirement.text}`));
      for (const gap of q.run.missing) trace.append(node('p', `Needs review: ${gap}`));
      for (const step of q.run.trace) {
        trace.append(node('p', `Round ${step.round}: ${step.status.replaceAll('_',' ')} · ${step.evidence_count} excerpts · ${(step.new_ids || []).length} newly supplied`));
        for (const query of step.queries || []) trace.append(node('p', `Search: ${query}`));
        for (const req of step.requirements || []) trace.append(node('p', `${req.coverage}: ${req.text}`));
      }
      card.append(trace);
    }
    if (q.restricted_review) card.append(node('p', 'This draft requires evidence access you do not currently have.'));
    if (book.confirmed && !q.blocked) card.append(action('Retrieve and draft', async () => {
      const run = await api(`/questions/${q.id}/runs`, 'POST', {expected_revision:q.revision,mode:'corrective'});
      running.set(run.id, {book:book.id, question:q.key}); message(`Retrieval queued for ${q.key}.`);
    }));
    if (q.draft) {
      card.append(node('p', `${q.draft.answer}: ${q.draft.explanation}`));
      q.draft.evidence.forEach((id, i) => card.append(action(`Evidence ${i+1}`, () => evidence(id))));
      for (const claim of q.draft.claims || []) {
        const line = node('p', claim.text);
        for (const id of claim.evidence_ids) line.append(action('Supporting excerpt', () => evidence(id)));
        card.append(line);
      }
    }
    if (!q.restricted_review) {
      const details = node('details'); details.append(node('summary', q.draft ? 'Edit answer' : 'Write a reviewed answer'));
      const select = node('select');
      answers.forEach(a => {const o = node('option', a); o.value = a; select.append(o);}); select.value = q.draft?.answer || 'Unknown';
      const explanation = node('textarea'); explanation.rows = 4; explanation.value = q.draft?.explanation || ''; explanation.setAttribute('aria-label','Explanation');
      const refs = new Set(q.draft?.evidence || []), choices = node('div');
      details.append(select, explanation, action('Choose supporting evidence', async () => {
        choices.replaceChildren();
        for (const item of await api(`/questions/${q.id}/evidence-options`)) {
          const label = node('label'), check = node('input'); check.type = 'checkbox';
          check.checked = refs.has(item.id);
          check.onchange = () => check.checked ? refs.add(item.id) : refs.delete(item.id);
          label.append(check, document.createTextNode(`${item.title} · ${item.locator}: ${item.text}`));
          choices.append(label);
        }
      }), choices, action('Save new revision', async () => {
        await api(`/questions/${q.id}/drafts`, 'POST', {expected_revision:q.revision, answer:select.value, explanation:explanation.value, evidence:[...refs]});
        await load(book.id); message('Saved. This revision needs approval.');
      }, '')); card.append(details);
    }
    if (me.roles.includes('security_reviewer')) {
      if (q.draft && !q.draft.approved && !q.blocked) {
        const claimChecks = (q.draft.claims || []).map(claim => {
          const label = node('label'); const check = node('input'); check.type = 'checkbox';
          label.append(check, document.createTextNode(` Supported and correctly scoped: ${claim.text}`)); card.append(label); return check;
        });
        const reason = node('input'); reason.placeholder = 'Review rationale'; reason.setAttribute('aria-label', 'Review rationale'); card.append(reason);
        const label = node('label'); const attestation = node('input'); attestation.type = 'checkbox';
        label.append(attestation, document.createTextNode(' I checked the full answer, its evidence and disclosure scope.'));
        const approve = action('Approve this revision', async () => {
          await api(`/questions/${q.id}/decisions`, 'POST', {decision:'approve',expected_revision:q.revision,attested_support:attestation.checked,claim_reviews:claimChecks.map(c => c.checked),reason:reason.value});
          await load(book.id); message('Revision approved.');
        }, ''); approve.disabled = true; const enabled = () => approve.disabled = !attestation.checked || claimChecks.some(c => !c.checked) || !reason.value.trim();
        attestation.onchange = enabled; claimChecks.forEach(c => c.onchange = enabled); reason.oninput = enabled;
        card.append(label, approve);
      }
      const dispositionReason = node('input'); dispositionReason.placeholder = 'Reason for requesting changes'; dispositionReason.setAttribute('aria-label','Change request reason'); card.append(dispositionReason);
      card.append(action(q.blocked ? 'Unblock for revision' : 'Request changes / block', async () => {
        if (!dispositionReason.value.trim()) throw new Error('Enter a reason for this decision.');
        await api(`/questions/${q.id}/decisions`, 'POST', {decision:q.blocked ? 'unblock':'block',expected_revision:q.revision,reason:dispositionReason.value}); await load(book.id);
      }));
    }
    root.append(card);
  }
}
$('login-form').onsubmit = async e => {
  e.preventDefault(); const f = new FormData(e.target);
  try { await api('/login','POST',Object.fromEntries(f)); e.target.reset(); await session(); message(''); }
  catch (err) { message(err.message.replaceAll('_',' ')); }
};
$('logout').onclick = async () => { await api('/logout','POST'); location.reload(); };
$('close-evidence').onclick = () => $('evidence').close();
$('upload-form').onsubmit = async e => {
  e.preventDefault();
  try { const b = await api('/questionnaires/import','POST',workbookForm(e.target)); await books(); await load(b.id); message('Review the extracted questions before confirming.'); }
  catch (err) { message(err.message.replaceAll('_',' ')); }
};
$('source-form').onsubmit = async e => {
  e.preventDefault();
  try { await api('/sources/import','POST',sourceForm(e.target)); message('Source uploaded. Activate after indexing completes.'); $('source-list').click(); }
  catch (err) { message(err.message.replaceAll('_',' ')); }
};
$('source-list').onclick = async () => {
  try {
    const account = book?.account || me.accounts[0]; if (!account) return;
    $('sources').replaceChildren();
    for (const src of await api(`/sources?account=${account}`)) {
      const row = node('div', `${src.title} · ${src.disclosure} · ${src.active ? 'active':'pending'}`);
      if (book) row.append(action('Inspect', async () => {
        const chunks = await api(`/sources/${src.id}/chunks?workbook_id=${book.id}`);
        $('evidence-title').textContent = src.title; $('evidence-meta').textContent = src.disclosure;
        $('evidence-text').textContent = chunks.map(c => `${c.id}\n${c.locator}\n${c.text}`).join('\n\n'); $('evidence').showModal();
      }));
      if (!src.active && !src.superseded && me.roles.includes('security_reviewer')) row.append(action('Activate', async () => {
        await api(`/sources/${src.id}/activate`,'POST',{supersedes:src.rebuild_of || undefined}); $('source-list').click(); message('Source activated. Existing approvals now require refreshed drafts.');
      }));
      row.append(node('p', `Version ${src.generation.slice(0,12)} · expires ${src.expires}${src.superseded ? ' · superseded' : ''}`, 'muted'));
      if (src.active && me.roles.includes('security_reviewer')) row.append(action('Deactivate', async () => {
        await api(`/sources/${src.id}/deactivate`, 'POST'); $('source-list').click(); message('Source deactivated; dependent approvals are stale.');
      }));
      if (src.active && me.roles.includes('security_reviewer')) row.append(action('Rebuild pending version', async () => {
        await api(`/sources/${src.id}/reindex`, 'POST'); $('source-list').click();
        message('Pending version created. Activate it after indexing to replace this version atomically.');
      }));
      $('sources').append(row);
    }
  } catch (e) { message(e.message.replaceAll('_',' ')); }
};
setInterval(async () => {
  for (const [id, info] of running) {
    try {
      const r = await api('/runs/' + id);
      message(`${info.question}: ${r.status.replaceAll('_',' ')} · ${r.rounds} retrieval rounds · ${r.generation_attempts} model attempts${r.stop_reason ? ' · '+r.stop_reason : ''}`);
      if (['awaiting_review','succeeded','failed','cancelled'].includes(r.status)) {
        running.delete(id); if (book?.id === info.book) await load(book.id);
      }
    } catch (e) { running.delete(id); message(e.message.replaceAll('_',' ')); }
  }
}, 3000);
session().catch(() => {});

$('search-evidence').onclick = async () => {
  try {
    if (!book) throw new Error('Select a questionnaire first.');
    const matches = await api(`/search?workbook_id=${book.id}&query=${encodeURIComponent($('evidence-query').value)}`);
    $('search-results').replaceChildren();
    for (const match of matches) {
      const row = node('div', `${match.title} · ${match.disclosure}`);
      row.append(action('Read excerpt', () => evidence(match.id)));
      if (match.disclosure !== 'internal_only') row.append(node('p', `Citation: ${match.id}`, 'muted'));
      $('search-results').append(row);
    }
  } catch(e) { message(e.message.replaceAll('_',' ')); }
};
$('operations').onclick = async () => {
  try {
    const state = await api('/operations');
    $('evidence-title').textContent = 'Operations'; $('evidence-meta').textContent = state.alerts.join(', ') || 'No active alerts';
    $('evidence-text').textContent = JSON.stringify(state, null, 2); $('evidence').showModal();
  } catch(e) { message(e.message.replaceAll('_',' ')); }
};

function workbookForm(form) {
  const data = new FormData(form), mapping = {};
  for (const key of ['id_col','question_col','answer_col','explanation_col','first_row','last_row']) {
    mapping[key] = Number(data.get(key)); data.delete(key);
  }
  data.set('mapping', JSON.stringify(mapping)); return data;
}
function sourceForm(form) {
  const raw = new FormData(form), data = new FormData(), metadata = {};
  data.set('file', raw.get('file'));
  for (const key of ['title','family','account','disclosure','authority','valid_from','valid_until']) metadata[key] = raw.get(key);
  metadata.roles = raw.get('roles') === 'both' ? ['sales','security_reviewer'] : ['security_reviewer'];
  metadata.audience = metadata.disclosure === 'customer_approved' ? (raw.get('audience') === 'both' ? ['acme','nova'] : [raw.get('audience')]) : [];
  metadata.provenance = raw.get('provenance') ? [raw.get('provenance')] : [];
  data.set('metadata',JSON.stringify(metadata)); return data;
}
