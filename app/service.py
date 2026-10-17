"""Transactional business operations, independent of LLM and graph execution."""

import time
import hashlib
import uuid
from datetime import date, datetime, timezone
from sqlalchemy import select
from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import policy
from .db import (
    Approval,
    Chunk,
    Draft,
    Event,
    Export,
    Job,
    Question,
    QuestionVersion,
    RequestKey,
    Run,
    Source,
    User,
    Workbook,
    digest,
    uid,
)
from .schema import ANSWERS
from .workbooks import clean_export, extract


def audit(s, user, action, target, **details):
    s.add(Event(actor=user.id, action=action, target=target, details=details))


def remember_question(s, user, q):
    s.flush()
    if not s.scalar(
        select(QuestionVersion.id).where(
            QuestionVersion.question_id == q.id, QuestionVersion.revision == q.revision
        )
    ):
        s.add(QuestionVersion(question_id=q.id, revision=q.revision, text=q.text, actor=user.id))


def once(s, user, operation, key, payload, action):
    policy.require(key and len(key) <= 100, "idempotency_key_required", 422)
    policy.epoch(s, lock=True)
    identity = f"{user.id}:{operation}:{key}"
    found = s.get(RequestKey, identity)
    hashed = digest(payload)
    if found:
        policy.require(found.payload_hash == hashed, "idempotency_conflict", 409)
        return found.result
    result = action()
    s.add(RequestKey(key=identity, payload_hash=hashed, result=result))
    return result


def import_workbook(s, user, objects, data, account, as_of, mapping, *, parsed_rows=None):
    policy.epoch(s, lock=True)
    policy.require(policy.content_user(user, account))
    policy.require(date.fromisoformat(as_of) <= date.today(), "future_as_of", 422)
    rows = parsed_rows if parsed_rows is not None else extract(data, mapping)
    book = Workbook(
        id=uid(),
        account=account,
        as_of=as_of,
        product="atlas",
        object_hash=objects.put(data),
        mapping=mapping,
        confirmed=False,
    )
    s.add(book)
    s.flush()
    for row in rows:
        q = Question(workbook_id=book.id, **row)
        s.add(q)
        remember_question(s, user, q)
    audit(s, user, "workbook_imported", book.id)
    return book


def question_context(s, user, question_id):
    q = s.get(Question, question_id)
    policy.require(q is not None)
    book = s.get(Workbook, q.workbook_id)
    policy.access(user, book)
    return q, book


def confirm_mapping(s, user, book_id):
    book = s.get(Workbook, book_id)
    policy.require(book is not None)
    policy.access(user, book)
    book.confirmed = True
    audit(s, user, "mapping_confirmed", book.id)


def add_source(s, user, objects, data, blocks, metadata, *, suffix=".md", rebuild_of=None):
    policy.security(user)
    policy.epoch(s, lock=True)
    required = {
        "family",
        "title",
        "account",
        "roles",
        "disclosure",
        "audience",
        "valid_from",
        "valid_until",
        "authority",
    }
    policy.require(required <= set(metadata) <= required | {"provenance"}, "invalid_source_metadata", 422)
    policy.require(metadata["account"] == "*" or metadata["account"] in user.accounts)
    policy.require(
        set(metadata["roles"]) <= {"sales", "security_reviewer"} and metadata["roles"], "invalid_roles", 422
    )
    # A reviewer may create only sources readable by their current role, never grant admin powers.
    policy.require(set(metadata["roles"]) & set(user.roles), "invalid_roles", 422)
    policy.require(set(metadata["audience"]) <= set(user.accounts), "invalid_audience", 422)
    policy.require(
        metadata["disclosure"] in {"public", "customer_approved", "internal_only"}, "invalid_disclosure", 422
    )
    policy.require(
        metadata["authority"]
        in {"approved_policy", "approved_specification", "approved_statement", "historical_response"},
        "invalid_authority",
        422,
    )
    policy.require(
        date.fromisoformat(metadata["valid_from"]) <= date.fromisoformat(metadata["valid_until"]),
        "invalid_interval",
        422,
    )
    policy.require(
        all(
            isinstance(metadata[k], str) and 0 < len(metadata[k]) <= limit
            for k, limit in [("family", 120), ("title", 200), ("account", 80)]
        ),
        "invalid_source_metadata",
        422,
    )
    if metadata["authority"] == "approved_statement":
        policy.require(
            isinstance(metadata.get("provenance"), list) and metadata["provenance"],
            "statement_provenance_required",
            422,
        )
    policy.curate_source(user, metadata["account"], metadata["disclosure"], metadata["audience"])
    policy.require(1 <= len(blocks) <= 10000, "empty_source", 422)
    from .parsing import PARSER_VERSION

    pipeline = {
        "parser": PARSER_VERSION,
        "chunker": "recursive-char-v2-1000-150",
        "format": suffix,
        "uploader": user.id,
        "acquired": time.time(),
        "rebuild_of": rebuild_of,
        "chunk_target": "approximately 300 tokens; embedding hard cap 450",
    }
    object_hash = objects.put(data)
    identity = digest(
        {
            "object": object_hash,
            "metadata": metadata,
            "parser": PARSER_VERSION,
            "chunker": pipeline["chunker"],
            "rebuild_of": rebuild_of,
        }
    )
    found = s.scalar(select(Source).where(Source.generation == identity))
    if found:
        return found
    source = Source(
        id=uid(), product="atlas", object_hash=object_hash, pipeline=pipeline, generation=identity, **metadata
    )
    s.add(source)
    s.flush()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=150, add_start_index=True, strip_whitespace=False
    )
    for block in blocks:
        text, locator = block["text"], block["locator"]
        for document in splitter.create_documents([text]):
            start, piece = document.metadata["start_index"], document.page_content
            policy.require(start >= 0 and piece.strip(), "invalid_chunk", 422)
            s.add(
                Chunk(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{identity}:{locator}:{start}")),
                    source_id=source.id,
                    text=piece,
                    locator=locator,
                    start=start,
                    parent_text=text[max(0, start - 200) : min(len(text), start + len(piece) + 200)],
                    metadata_record={
                        "text_hash": hashlib.sha256(piece.encode()).hexdigest(),
                        "generation": identity,
                        "parser": PARSER_VERSION,
                        "chunker": pipeline["chunker"],
                        "end": start + len(piece),
                        "parent_start": max(0, start - 200),
                        "dimensions": 384,
                        "preprocessing": "fastembed-passage-v1",
                    },
                )
            )
    audit(s, user, "source_uploaded", source.id, generation=identity, object_hash=object_hash)
    return source


def activate_source(s, user, source_id, *, supersedes=None):
    policy.security(user)
    source = s.get(Source, source_id)
    policy.require(source is not None)
    policy.curate_source(user, source.account, source.disclosure, source.audience)
    policy.require(
        not s.scalar(
            select(Chunk.id).where(Chunk.source_id == source.id, Chunk.embedding.is_(None)).limit(1)
        ),
        "source_not_indexed",
        409,
    )
    meta = policy.epoch(s, lock=True)
    if supersedes:
        prior = s.get(Source, supersedes)
        policy.require(
            prior is not None
            and prior.family == source.family
            and prior.product == source.product
            and prior.account == source.account,
            "invalid_supersession",
            422,
        )
        prior.superseded = True
    source.active = True
    meta.corpus += 1
    audit(s, user, "source_activated", source.id, generation=source.generation, supersedes=supersedes)


def change_user(s, actor, target_id, roles, accounts, active):
    policy.admin(actor)
    policy.require(set(roles) <= {"sales", "security_reviewer", "administrator"}, "invalid_roles", 422)
    policy.require(set(accounts) <= {"acme", "nova"}, "invalid_accounts", 422)
    meta = policy.epoch(s, lock=True)
    target = s.get(User, target_id)
    policy.require(target is not None)
    target.roles, target.accounts, target.active = roles, accounts, active
    meta.policy += 1
    audit(s, actor, "membership_changed", target.id)


def start_run(s, user, question_id, expected_revision, mode):
    from .config import LIMITS
    from .providers import ASSESS, CHECK
    from pathlib import Path

    meta = policy.epoch(s, lock=True)
    q, book = question_context(s, user, question_id)
    policy.require(book.confirmed, "mapping_unconfirmed", 409)
    policy.require(q.revision == expected_revision, "stale_revision", 409)
    policy.require(mode in {"dense", "hybrid", "corrective"}, "invalid_mode", 422)
    policy.require(not q.blocked, "review_required", 409)
    run = Run(
        id=uid(),
        question_id=q.id,
        principal_id=user.id,
        revision=q.revision,
        policy=meta.policy,
        corpus=meta.corpus,
        mode=mode,
        record={
            "config": digest(
                {
                    "limits": LIMITS,
                    "prompts": [ASSESS, CHECK],
                    "code": {
                        p.name: digest(p.read_text()) for p in sorted(Path(__file__).parent.glob("*.py"))
                    },
                }
            )
        },
    )
    s.add(run)
    s.flush()
    s.add(Job(run_id=run.id, delivery=f"start:{run.id}"))
    audit(s, user, "run_requested", run.id)
    return run


def new_draft(
    s,
    user,
    question_id,
    expected_revision,
    answer,
    explanation,
    evidence_ids,
    *,
    supported=False,
    claims=None,
):
    meta = policy.epoch(s, lock=True)
    q, book = question_context(s, user, question_id)
    policy.require(q.revision == expected_revision, "stale_revision", 409)
    policy.require(answer in ANSWERS and 0 < len(explanation) <= 6000, "invalid_answer", 422)
    policy.evidence(s, user, book, evidence_ids)
    if answer not in {"Unknown", "Declined"}:
        policy.require(evidence_ids, "evidence_required", 422)
    remember_question(s, user, q)
    claims = claims or [{"text": explanation, "evidence_ids": list(evidence_ids)}]
    policy.require(
        1 <= len(claims) <= 12
        and all(
            isinstance(c.get("text"), str)
            and c["text"].strip()
            and set(c.get("evidence_ids", [])) <= set(evidence_ids)
            for c in claims
        ),
        "invalid_claim_mapping",
        422,
    )
    q.revision += 1
    draft = Draft(
        id=uid(),
        question_id=q.id,
        revision=q.revision,
        answer=answer,
        explanation=explanation,
        evidence=list(dict.fromkeys(evidence_ids)),
        author_id=user.id,
        supported=supported,
        policy=meta.policy,
        corpus=meta.corpus,
        claims=claims,
    )
    s.add(draft)
    q.current_draft = draft.id
    audit(s, user, "draft_created", draft.id, question=q.id, revision=q.revision, claims=digest(claims))
    return draft


def fingerprint(s, user, q, book, draft):
    meta = policy.epoch(s)
    policy.require(draft.id == q.current_draft and draft.revision == q.revision, "stale_draft", 409)
    policy.require(
        (draft.policy, draft.corpus) == (meta.policy, meta.corpus), "source_or_policy_changed", 409
    )
    policy.require(not q.blocked, "review_required", 409)
    refs = policy.evidence(s, user, book, draft.evidence)
    return digest(
        {
            "question": [q.id, q.revision, q.text],
            "draft": [draft.id, draft.answer, draft.explanation],
            "claims": draft.claims,
            "evidence": [(c.id, src.id, src.object_hash, src.disclosure, src.audience) for c, src in refs],
            "scope": [book.account, book.product, book.as_of],
            "epochs": [meta.policy, meta.corpus],
        }
    )


def approve(
    s,
    user,
    question_id,
    expected_revision,
    attested_support=False,
    *,
    claim_reviews=None,
    reason="Evidence and full answer reviewed",
):
    policy.epoch(s, lock=True)
    q, book = question_context(s, user, question_id)
    policy.security(user, book)
    policy.require(q.revision == expected_revision and q.current_draft, "stale_revision", 409)
    draft = s.get(Draft, q.current_draft)
    policy.draft_access(s, user, book, draft)
    fp = fingerprint(s, user, q, book, draft)
    # The reviewer explicitly checks evidence; a model check alone never approves.
    policy.require(attested_support, "review_attestation_required", 422)
    if draft.answer not in {"Unknown", "Declined"}:
        policy.require(draft.evidence, "evidence_required", 422)
        policy.require(all(c.get("evidence_ids") for c in draft.claims), "claim_evidence_required", 422)
    # A manual edit has its own revision-bound human support check, independent of model output.
    reviews = claim_reviews if claim_reviews is not None else [True] * len(draft.claims)
    policy.require(
        len(reviews) == len(draft.claims) and all(x is True for x in reviews), "claim_review_required", 422
    )
    policy.require(
        isinstance(reason, str) and 0 < len(reason.strip()) <= 1000, "decision_reason_required", 422
    )
    expiry = time.time() + 7 * 86400
    for _, src in policy.evidence(s, user, book, draft.evidence):
        expiry = min(
            expiry, datetime.fromisoformat(src.valid_until).replace(tzinfo=timezone.utc).timestamp() + 86400
        )
    old = s.scalar(select(Approval).where(Approval.draft_id == draft.id))
    if old:
        policy.require(old.fingerprint == fp and old.expires > time.time(), "approval_expired", 409)
        return old
    approval = Approval(
        draft_id=draft.id,
        actor_id=user.id,
        fingerprint=fp,
        expires=expiry,
        support_review={
            "claims_hash": digest(draft.claims),
            "claims": reviews,
            "reason": reason,
            "checked_at": time.time(),
            "revision": q.revision,
        },
    )
    s.add(approval)
    # Resume only graphs paused on this exact draft, under their original principal.
    for run in s.scalars(select(Run).where(Run.question_id == q.id, Run.status == "awaiting_review")):
        if run.record.get("draft_id") == draft.id:
            s.add(Job(run_id=run.id, delivery=f"resume:{run.id}:{draft.id}", resume=True))
    audit(s, user, "answer_approved", draft.id, revision=q.revision, fingerprint=fp, reason=reason)
    return approval


def block_question(s, user, question_id, value, reason="Review requested"):
    policy.epoch(s, lock=True)
    q, book = question_context(s, user, question_id)
    if not value:
        policy.security(user, book)
    policy.require(
        isinstance(reason, str) and 0 < len(reason.strip()) <= 1000, "decision_reason_required", 422
    )
    q.blocked = value
    q.revision += 1
    audit(s, user, "review_disposition_changed", q.id, revision=q.revision, blocked=value, reason=reason)


def export_manifest(s, user, book):
    policy.access(user, book)
    policy.require(book.confirmed, "mapping_unconfirmed", 409)
    rows, fingerprints = [], []
    questions = list(
        s.scalars(select(Question).where(Question.workbook_id == book.id).order_by(Question.row))
    )
    policy.require(questions, "empty_workbook", 409)
    for q in questions:
        policy.require(q.current_draft, "approval_required", 409)
        draft = s.get(Draft, q.current_draft)
        policy.draft_access(s, user, book, draft)
        fp = fingerprint(s, user, q, book, draft)
        approval = s.scalar(select(Approval).where(Approval.draft_id == draft.id))
        policy.require(
            approval and approval.expires > time.time() and approval.fingerprint == fp,
            "approval_required",
            409,
        )
        fingerprints.append([fp, approval.id])
        rows.append((q.row, draft.answer, draft.explanation))
    return digest(fingerprints), rows


def build_export(db, user_id, objects, book_id):
    with db.transaction() as s:
        policy.epoch(s, lock=True)
        user, book = s.get(User, user_id), s.get(Workbook, book_id)
        policy.require(book is not None)
        before, rows = export_manifest(s, user, book)
        original, mapping = objects.get(book.object_hash), book.mapping
        questions = {
            q.row: q.text for q in s.scalars(select(Question).where(Question.workbook_id == book_id))
        }
    data = clean_export(original, mapping, rows, questions)
    object_hash = objects.put(data)
    with db.transaction() as s:
        policy.epoch(s, lock=True)
        user, book = s.get(User, user_id), s.get(Workbook, book_id)
        after, _ = export_manifest(s, user, book)
        policy.require(before == after, "export_stale", 409)
        existing = s.scalar(select(Export).where(Export.workbook_id == book_id, Export.fingerprint == after))
        if existing:
            return existing.id
        artifact = Export(id=uid(), workbook_id=book_id, fingerprint=after, object_hash=object_hash)
        s.add(artifact)
        audit(s, user, "export_created", artifact.id)
        return artifact.id


def download(s, user, objects, export_id):
    policy.epoch(s, lock=True)
    artifact = s.get(Export, export_id)
    policy.require(artifact is not None)
    fp, _ = export_manifest(s, user, s.get(Workbook, artifact.workbook_id))
    policy.require(fp == artifact.fingerprint, "export_stale", 409)
    audit(s, user, "export_downloaded", artifact.id)
    return objects.get(artifact.object_hash)
