"""Local evaluation artifacts and a budgeted, three-variant comparison; no model judge."""

import argparse
from datetime import date
from io import BytesIO
import json
import os
import time
from pathlib import Path

from openpyxl import Workbook as Excel
from sqlalchemy import select

from . import policy, service
from .config import Settings
from .db import Attempt, Chunk, Database, Draft, Objects, Question, Run, Source, User, digest
from .providers import ASSESS, CHECK, KimiProvider, LocalEmbeddings
from .schema import Proposal, Support
from .worker import claim, execute, index_pending

# Synthetic facts, not claims about a real vendor. Two independent spans per family.
FAMILIES = [
    (
        "transit",
        "Transport encryption",
        "Atlas uses TLS 1.3 for public API connections.",
        "Legacy FTP transfers are not supported.",
    ),
    (
        "storage",
        "Storage encryption",
        "Atlas primary databases use AES-256 encryption at rest.",
        "Customer-managed encryption keys are not supported.",
    ),
    (
        "mfa",
        "Multifactor authentication",
        "Atlas administrators must use multifactor authentication.",
        "Customer end-user MFA is configurable by each customer.",
    ),
    (
        "sso",
        "Single sign-on",
        "Atlas supports SAML 2.0 single sign-on.",
        "Single sign-on requires the enterprise subscription.",
    ),
    (
        "rbac",
        "Role permissions",
        "Atlas has viewer, editor and administrator roles.",
        "Custom role creation is not supported.",
    ),
    (
        "sessions",
        "Session expiry",
        "Atlas browser sessions expire after eight hours.",
        "An idle session expires after thirty minutes.",
    ),
    (
        "deletion",
        "Deletion requests",
        "Atlas deletes active customer records within seven days of a verified request.",
        "Backup copies expire under a separate thirty-day retention policy.",
    ),
    (
        "logs",
        "Audit retention",
        "Atlas retains customer audit events for ninety days.",
        "Exported customer logs are outside the Atlas retention policy.",
    ),
    (
        "backups",
        "Backup storage",
        "Atlas creates daily encrypted backups in the EU.",
        "Backups are retained for thirty days.",
    ),
    (
        "recovery",
        "Recovery objectives",
        "Atlas targets a recovery point objective of twenty-four hours.",
        "Its recovery time objective is eight hours; neither objective is a contractual guarantee.",
    ),
    (
        "incident",
        "Incident notification",
        "Atlas notifies affected customers within seventy-two hours of confirming an incident.",
        "The notification interval starts on confirmation, not initial detection.",
    ),
    (
        "hosting",
        "Hosting region",
        "Atlas production application data resides in the EU.",
        "Customers cannot select a specific EU country.",
    ),
    (
        "subprocessors",
        "Subprocessor notice",
        "Atlas gives thirty days notice before adding a subprocessor.",
        "Emergency replacements can use a shorter interval with a documented justification.",
    ),
    (
        "audit",
        "Assurance report",
        "Atlas provides an annual independent controls report to approved customers.",
        "The report does not certify every customer configuration.",
    ),
    (
        "pentest",
        "Penetration testing",
        "Atlas commissions an external penetration test annually.",
        "Full test reports require a confidentiality agreement.",
    ),
    (
        "vuln",
        "Vulnerability remediation",
        "Atlas targets critical vulnerability remediation within seven days.",
        "Documented compensating controls can extend this target.",
    ),
    (
        "devices",
        "Employee devices",
        "Atlas managed employee devices require disk encryption.",
        "Personal devices cannot access production administration.",
    ),
    (
        "training",
        "Security training",
        "Atlas employees complete security training annually.",
        "New employees complete onboarding training within thirty days.",
    ),
    (
        "privileged",
        "Privileged access",
        "Atlas reviews privileged access quarterly.",
        "This internal-only review record is not approved for customers.",
    ),
    (
        "ai",
        "AI processing",
        "Atlas does not use customer records to train general-purpose AI models.",
        "Customer opt-in is required for optional AI inference features.",
    ),
    (
        "network",
        "Network controls",
        "Atlas restricts database access to application service networks.",
        "This obsolete network description is expired.",
    ),
    (
        "support",
        "Support access",
        "Atlas support access requires a customer-authorized ticket.",
        "Support access is time limited and recorded.",
    ),
    (
        "keys",
        "Key rotation",
        "Nova Atlas keys rotate every ninety days.",
        "This negotiated statement is approved for Nova only.",
    ),
    (
        "availability",
        "Availability reporting",
        "Atlas publishes monthly availability reports.",
        "Maintenance windows are reported separately from unplanned outages.",
    ),
]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, indent=2)


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def build(root):
    policy.require(not (root / "cases.jsonl").exists(), "evaluation_already_exists", 409)
    sources, cases = [], []
    (root / "documents").mkdir(parents=True, exist_ok=True)
    for i, (family, topic, fact, caveat) in enumerate(FAMILIES):
        split = "development" if i < 12 else "validation" if i < 18 else "test"
        ids = []
        # Explicitly contradictory current statements in four held-together families.
        contradictory = i in {3, 9, 15, 21}
        if contradictory:
            caveat = "The current approved exception contradicts the policy: " + fact.replace(
                "Atlas ", "Atlas does not ", 1
            )
        for j, span in enumerate([fact, caveat]):
            ident = f"{family}-{j + 1}"
            ids.append(ident)
            metadata = dict(
                family=family,
                title=f"SYNTHETIC {topic} / {j + 1}",
                account="nova" if i == 22 else "*",
                roles=["security_reviewer"] if i == 18 else ["sales", "security_reviewer"],
                disclosure="internal_only" if i == 18 else "customer_approved",
                audience=["nova"] if i == 22 else ["acme", "nova"],
                authority="approved_policy",
                valid_from="2026-01-01",
                valid_until="2026-01-02" if i == 20 else "2027-12-31",
            )
            fmt = (".md", ".pdf", ".json")[(i * 2 + j) % 3]
            if fmt == ".json":
                metadata["authority"] = "approved_statement"
                metadata["provenance"] = [f"Synthetic policy authority: {family}; curated scoped statement"]
                content = json.dumps({"statement": span}).encode()
            elif fmt == ".pdf":
                from pypdf import PdfWriter
                from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

                w = PdfWriter()
                page = w.add_blank_page(width=1000, height=300)
                font = DictionaryObject(
                    {
                        NameObject("/Type"): NameObject("/Font"),
                        NameObject("/Subtype"): NameObject("/Type1"),
                        NameObject("/BaseFont"): NameObject("/Helvetica"),
                    }
                )
                page[NameObject("/Resources")] = DictionaryObject(
                    {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})}
                )
                stream = DecodedStreamObject()
                escaped = span.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                stream.set_data(f"BT /F1 10 Tf 20 250 Td ({escaped}) Tj ET".encode())
                page[NameObject("/Contents")] = w._add_object(stream)
                out = BytesIO()
                w.write(out)
                content = out.getvalue()
            else:
                content = span.encode()
            (root / "documents" / (ident + fmt)).write_bytes(content)
            sources.append(
                {
                    "id": ident,
                    "text": span,
                    "hash": digest(span),
                    "metadata": metadata,
                    "file": "documents/" + ident + fmt,
                    "format": fmt,
                }
            )
        # Five related forms remain grouped; candidate labels precede system outputs.
        questions = [
            f"For Acme, describe Atlas {topic.lower()}, including the stated limitation or exception.",
            f"For Nova, does the following accurately describe Atlas? {fact} Include the documented caveat.",
            f"Describe Atlas {topic.lower()} and provide its independently verified certification number.",
            f"Does that setting apply to our deployment's {topic.lower()}? We have not identified the product, configuration or customer.",
            f"As an Acme sales representative, what can I tell the customer about {topic.lower()} and its exceptions?",
        ]
        for j, q in enumerate(questions):
            account = "nova" if j == 1 else "acme"
            disposition = (
                "CLARIFICATION"
                if j == 3
                else "UNSUPPORTED"
                if i in {18, 20} or (i == 22 and account != "nova")
                else "CONFLICT"
                if contradictory
                else "PARTIAL"
                if j == 2
                else "ANSWERABLE"
            )
            requirements = [
                {"claim": x, "bundles": [[{"source": sid, "start": 0, "end": len(x), "hash": digest(x)}]]}
                for x, sid in zip([fact, caveat], ids, strict=True)
            ]
            if disposition == "UNSUPPORTED":
                requirements = [{"claim": "Eligible scoped evidence", "bundles": []}]
            if j == 2:
                requirements.append({"claim": "Independently verified certification number", "bundles": []})
            cases.append(
                {
                    "id": f"{family}-{j + 1}",
                    "family": family,
                    "split": split,
                    "question": q,
                    "account": account,
                    "principal": "sales" if j == 4 else "reviewer",
                    "as_of": "2026-10-04",
                    "disposition": disposition,
                    "requirements": requirements,
                    "label_status": "candidate_unreviewed",
                    "reuse": False,
                }
            )
    write_lines(root / "sources.jsonl", sources)
    write_lines(root / "cases.jsonl", cases)
    write_json(
        root / "review.json",
        {
            "label_authors": [],
            "independent_reviewers": [],
            "notes": "Candidate synthetic cases require human correction and review before a locked run.",
        },
    )
    print(
        json.dumps(
            {
                "sources": len(sources),
                "cases": len(cases),
                "splits": [60, 30, 30],
                "status": "candidate_unreviewed",
            }
        )
    )


def validate(root):
    cases = read_lines(root / "cases.jsonl")
    sources = read_lines(root / "sources.jsonl")
    family_splits = {}
    ids = set()
    texts = set()
    source_map = {x["id"]: x for x in sources}
    for c in cases:
        policy.require(c["id"] not in ids and c["question"] not in texts, "duplicate_case", 422)
        ids.add(c["id"])
        texts.add(c["question"])
        policy.require(c["split"] in {"development", "validation", "test"}, "invalid_split", 422)
        policy.require(family_splits.setdefault(c["family"], c["split"]) == c["split"], "family_leakage", 422)
        for req in c["requirements"]:
            for bundle in req["bundles"]:
                for anchor in bundle:
                    source = source_map[anchor["source"]]
                    policy.require(
                        digest(source["text"]) == anchor["hash"]
                        and 0 <= anchor["start"] < anchor["end"] <= len(source["text"]),
                        "invalid_bundle_anchor",
                        422,
                    )
    counts = {
        split: sum(c["split"] == split for c in cases) for split in ["development", "validation", "test"]
    }
    policy.require(
        counts == dict(development=60, validation=30, test=30) and len(family_splits) == 24,
        "invalid_split_counts",
        422,
    )
    return cases, sources


def config_hash(settings):
    files = {str(p): digest(p.read_text()) for p in sorted(Path("app").glob("*.py"))}
    return digest(
        {
            "model": settings.model,
            "rates": [settings.input_price, settings.output_price],
            "embedding": LocalEmbeddings.model_id,
            "assess": ASSESS,
            "check": CHECK,
            "schemas": [Proposal.model_json_schema(), Support.model_json_schema()],
            "code": files,
            "lock": digest(Path("uv.lock").read_text()),
        }
    )


def corpus_snapshot(db):
    with db.transaction() as s:
        sources = [
            {c.name: getattr(src, c.name) for c in Source.__table__.columns}
            for src in s.scalars(select(Source).order_by(Source.id))
        ]
        chunks = [
            {
                "id": c.id,
                "source": c.source_id,
                "text": digest(c.text),
                "parent": digest(c.parent_text),
                "model": c.embedding_model,
                "vector": None if c.embedding is None else digest([float(x) for x in c.embedding]),
            }
            for c in s.scalars(select(Chunk).order_by(Chunk.id))
        ]
        principals = [
            {"id": u.id, "roles": u.roles, "accounts": u.accounts, "active": u.active}
            for u in s.scalars(select(User).order_by(User.id))
        ]
        return digest({"sources": sources, "chunks": chunks, "principals": principals})


def freeze(root, settings, *, source_reviewed=False):
    cases, sources = validate(root)
    review = json.loads((root / "review.json").read_text())
    authors = set(review["label_authors"])
    reviewers = set(review["independent_reviewers"])
    policy.require(
        (authors and reviewers - authors and all(c["label_status"] == "human_reviewed" for c in cases))
        or (source_reviewed and all(c["label_status"] == "source_reviewed" for c in cases)),
        "independent_label_review_required",
        409,
    )
    policy.require(not (root / "freeze.json").exists(), "already_frozen", 409)
    write_json(
        root / "freeze.json",
        {
            "cases": digest(cases),
            "sources": digest(sources),
            "config": config_hash(settings),
            "review": digest(review),
            "corpus": corpus_snapshot(Database(settings.database_url)),
            "threshold": 0.90,
            "independent_validation": not source_reviewed,
            "date": date.today().isoformat(),
        },
    )
    print("Evaluation configuration frozen; locked outputs still require independent human scoring.")


def ingest(root, db, objects, embeddings):
    _, sources = validate(root)
    policy.require(not (root / "source-bindings.json").exists(), "evaluation_already_ingested", 409)
    bindings = {}
    with db.transaction() as s:
        reviewer = s.scalar(select(User).where(User.name == "reviewer"))
        policy.security(reviewer)
        for source in sources:
            from .parsing import parse_source

            suffix = source.get("format", ".md")
            content = (root / source["file"]).read_bytes() if source.get("file") else source["text"].encode()
            blocks = parse_source(content, suffix)
            policy.require(
                "".join(b["text"] for b in blocks).strip() == source["text"].strip(),
                "corpus_extraction_changed",
                422,
            )
            src = service.add_source(s, reviewer, objects, content, blocks, source["metadata"], suffix=suffix)
            s.flush()
            chunks = list(s.scalars(select(Chunk).where(Chunk.source_id == src.id)))
            bindings[source["id"]] = {
                "source": src.id,
                "chunks": [c.id for c in chunks],
                "spans": {
                    c.id: {
                        "source": source["id"],
                        "hash": source["hash"],
                        "start": c.start,
                        "end": c.start + len(c.text),
                        "parent_start": c.metadata_record.get("parent_start", 0),
                        "parent_end": c.metadata_record.get("parent_start", 0) + len(c.parent_text),
                    }
                    for c in chunks
                },
            }

    for _ in range(10):
        index_pending(db, embeddings)
    with db.transaction() as s:
        reviewer = s.scalar(select(User).where(User.name == "reviewer"))
        for binding in bindings.values():
            service.activate_source(s, reviewer, binding["source"])
    write_json(root / "source-bindings.json", bindings)
    print("Synthetic evaluation sources ingested; gold cases and labels were not ingested.")


def run_batch(root, db, objects, settings, split, limit, campaign, batch, interval=0):
    cases, sources = validate(root)
    if split != "development":
        frozen = json.loads((root / "freeze.json").read_text())
        policy.require(
            (frozen["cases"], frozen["sources"], frozen["config"])
            == (digest(cases), digest(sources), config_hash(settings)),
            "frozen_inputs_changed",
            409,
        )
    if split != "development":
        policy.require(frozen["corpus"] == corpus_snapshot(db), "frozen_corpus_changed", 409)
    policy.require((root / "source-bindings.json").exists(), "ingest_evaluation_sources_first", 409)
    chosen = [c for c in cases if c["split"] == split][:limit]
    plans_path = root / "batches.json"
    plans = json.loads(plans_path.read_text()) if plans_path.exists() else {}
    plan = {
        "cases": [c["id"] for c in chosen],
        "split": split,
        "config": config_hash(settings),
        "sources": digest(sources),
        "campaign": campaign,
    }
    policy.require(batch not in plans or plans[batch] == plan, "batch_inputs_changed", 409)
    plans[batch] = plan
    write_json(plans_path, plans)
    provider, embeddings = KimiProvider(settings), LocalEmbeddings(settings.embedding_cache)
    runs_path = root / "runs.jsonl"
    records = read_lines(runs_path) if runs_path.exists() else []
    completed = {(r["case"], r["variant"]) for r in records if r["batch"] == batch}
    next_admission = 0.0
    for case in chosen:
        for variant in ["dense", "hybrid", "corrective"]:
            if (case["id"], variant) in completed:
                continue
            until = max(next_admission, getattr(provider, "cooldown_until", 0))
            while time.time() < until:
                time.sleep(min(30, until - time.time()))
            next_admission = time.time() + interval
            w = Excel()
            w.active.append(["ID", "Question", "Response", "Explanation"])
            w.active.append([case["id"], case["question"]])
            data = BytesIO()
            w.save(data)
            with db.transaction() as s:
                u = s.scalar(select(User).where(User.name == case.get("principal", "reviewer")))
                policy.require(policy.content_user(u, case["account"]))
                book = service.import_workbook(
                    s,
                    u,
                    objects,
                    data.getvalue(),
                    case["account"],
                    case["as_of"],
                    dict(id_col=1, question_col=2, answer_col=3, explanation_col=4, first_row=2, last_row=2),
                )
                service.confirm_mapping(s, u, book.id)
                q = s.scalar(select(Question).where(Question.workbook_id == book.id))
                run = service.start_run(s, u, q.id, q.revision, variant)
                run.record = {
                    "evaluation_batch": batch,
                    "evaluation_campaign": campaign,
                    "case": case["id"],
                    "config": config_hash(settings),
                }
                ident = run.id
            work = claim(db, "evaluation", run_id=ident)
            policy.require(work is not None, "evaluation_job_unavailable", 409)
            execute(db, provider, embeddings, "evaluation", *work)
            with db.transaction() as s:
                run = s.get(Run, ident)
                q = s.get(Question, run.question_id)
                d = s.get(Draft, q.current_draft) if q.current_draft else None
                attempts = list(s.scalars(select(Attempt).where(Attempt.run_id == ident)))
                record = {
                    "case": case["id"],
                    "family": case["family"],
                    "split": split,
                    "variant": variant,
                    "run": ident,
                    "batch": batch,
                    "campaign": campaign,
                    "status": run.status,
                    "stop": run.stop_reason,
                    "rounds": run.rounds,
                    "generation_attempts": run.generation_attempts,
                    "embedding_attempts": run.embedding_attempts,
                    "elapsed": run.elapsed,
                    "trace": run.record,
                    "cost": sum(a.actual if a.actual is not None else a.reserved for a in attempts),
                    "attempts": [
                        {
                            "kind": a.kind,
                            "status": a.status,
                            "reserved": a.reserved,
                            "actual": a.actual,
                            "details": a.details,
                        }
                        for a in attempts
                    ],
                    "draft": None
                    if not d
                    else {
                        "answer": d.answer,
                        "explanation": d.explanation,
                        "evidence": d.evidence,
                        "supported": d.supported,
                    },
                }
            records.append(record)
            write_lines(runs_path, records)
            if provider.daily_limited:
                print(
                    "Kimi daily allowance exhausted. Requests stopped; resume after the provider resets it."
                )
                return
            if record["stop"] == "spend_limit":
                print("Shared budget reached. Resume this batch after the applicable limit resets.")
                return
    print(f"{len(records)} recorded runs. No answer was automatically approved.")


def report(root, batch=None):
    from .scoring import summarize

    cases, _ = validate(root)
    runs = read_lines(root / "runs.jsonl") if (root / "runs.jsonl").exists() else []
    batches = {r["batch"] for r in runs}
    policy.require(batch or len(batches) <= 1, "select_report_batch", 422)
    batch = batch or next(iter(batches), "")
    runs = [r for r in runs if r["batch"] == batch]
    judgments = read_lines(root / "judgments.jsonl") if (root / "judgments.jsonl").exists() else []
    bindings = (
        json.loads((root / "source-bindings.json").read_text())
        if (root / "source-bindings.json").exists()
        else {}
    )
    spans = {ident: span for b in bindings.values() for ident, span in b.get("spans", {}).items()}
    plans = json.loads((root / "batches.json").read_text()) if (root / "batches.json").exists() else {}
    planned = plans.get(batch, {}).get("cases")
    result = summarize(cases, runs, judgments, spans, planned_cases=planned)
    result["batch"] = batch
    result["scoring_code_digest"] = digest(Path(__file__).with_name("scoring.py").read_text())
    result["review_basis"] = "source-grounded review; no independent human validation claimed"
    if (root / "freeze.json").exists():
        frozen = json.loads((root / "freeze.json").read_text())
        review = json.loads((root / "review.json").read_text())
        independent = bool(
            frozen.get("independent_validation")
            and digest(review) == frozen["review"]
            and set(review.get("independent_reviewers", [])) - set(review.get("label_authors", []))
        )
        for run in runs:
            ratings = [
                j
                for j in judgments
                if j.get("run") == run["run"]
                and not j.get("adjudicated")
                and isinstance(j.get("complete_supported"), bool)
            ]
            independent = independent and len({j.get("reviewer") for j in ratings}) >= 2
            judgment = next((j for j in judgments if j.get("run") == run["run"] and j.get("adjudicated")), {})
            independent = independent and all(
                k in judgment
                for k in ("assertions", "citations", "applicable", "disclosure_eligible", "conflict", "ready")
            )
            if run.get("draft") and run["draft"]["answer"] not in {"Unknown", "Declined"}:
                independent = (
                    independent
                    and bool(judgment.get("assertions"))
                    and len(judgment.get("citations", [])) == len(run["draft"]["evidence"])
                )
        locked = runs and all(
            r["split"] == "test" and r.get("trace", {}).get("config") == frozen["config"] for r in runs
        )
        metric = result["variants"]["corrective"]["supported_complete"]["value"]
        result["semantic_gate"].update(
            factual_target_met=bool(
                locked
                and result["status"] == "scored"
                and metric is not None
                and metric >= frozen["threshold"]
            ),
            independent_validation=bool(independent),
            locked_comparison=bool(locked),
        )
        result["semantic_gate"]["passed"] = bool(
            independent
            and locked
            and result["status"] == "scored"
            and metric is not None
            and metric >= frozen["threshold"]
        )
    write_json(root / "report.json", result)
    lines = [
        "# AssureDesk evaluation",
        "",
        f"Batch: `{batch}`; {result['attempted_runs']} recorded variant runs over {result['planned_cases']} questions.",
        "",
        f"Status: {result['status']}. " + result["review_basis"],
        "",
        f"Semantic release gate: **{'passed' if result['semantic_gate']['passed'] else 'not passed'}** "
        f"(complete-supported threshold {result['semantic_gate']['threshold']:.0%}; independent validation required).",
        f"Frozen locked factual target met: {result['semantic_gate'].get('factual_target_met', False)}. "
        f"Independent validation available: {result['semantic_gate'].get('independent_validation', False)}.",
        "",
        "| Variant | Supported complete | Selective precision | Missing / unscored | Known cost + uncertain reservation |",
        "|---|---|---|---|---|",
    ]
    for mode, v in result["variants"].items():
        m, p = v["supported_complete"], v["selective_precision"]
        lines.append(
            f"| {mode} | {m['numerator']}/{m['denominator']} | {p['numerator']}/{p['denominator']} | {len(v['missing_runs'])}/{v['unscored']} | ${v['cost_usd']:.6f} |"
        )
    lines += [
        "",
        "Full retrieval, routing, citation, uncertainty, and cost counts: `report.json`.",
        result["retrieval_population"],
        "Unscored semantic outcomes are unresolved, never inferred from the model's own support check.",
        "",
        "## Cases requiring review",
        "",
    ]
    scores = {j["run"]: j for j in judgments if j.get("adjudicated")}
    for r in runs:
        if not scores.get(r["run"], {}).get("complete_supported"):
            lines.append(
                f"- {r['case']} / {r['variant']}: {r.get('stop') or r['status']}; "
                + ("unscored" if r["run"] not in scores else "not complete and supported")
            )
    (root / "evaluation-report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(result, indent=2))
    return result


def review_packet(root):
    """Blinded outputs and exact source material for manual, claim-level judgments."""
    runs = read_lines(root / "runs.jsonl")
    cases = {c["id"]: c for c in read_lines(root / "cases.jsonl")}
    bindings = json.loads((root / "source-bindings.json").read_text())
    sources = {c["id"]: c for c in read_lines(root / "sources.jsonl")}
    packets = []
    for r in sorted(runs, key=lambda r: digest(r["run"])):
        cited = set((r.get("draft") or {}).get("evidence", []))
        packets.append(
            {
                "run": r["run"],
                "case": cases[r["case"]],
                "draft": r.get("draft"),
                "sources": [sources[key] for key, b in bindings.items() if cited & set(b["chunks"])],
                "judgment": {
                    "reviewer": "",
                    "adjudicated": False,
                    "complete_supported": None,
                    "assertions": [],
                    "citations": [],
                    "review_minutes": None,
                },
            }
        )
    write_lines(root / "review-packet.jsonl", packets)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "command", choices=["build", "validate", "ingest", "freeze", "run", "report", "review-packet"]
    )
    p.add_argument("--root", type=Path, default=Path("data/evaluation"))
    p.add_argument("--split", choices=["development", "validation", "test"], default="development")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument(
        "--interval",
        type=float,
        default=0,
        help="Minimum seconds between run admissions, outside active processing",
    )
    p.add_argument(
        "--source-reviewed",
        action="store_true",
        help="Freeze source-reviewed exploratory labels without claiming independent human validation",
    )
    p.add_argument("--campaign", default="pilot-1")
    p.add_argument("--batch", default="development-1")
    args = p.parse_args()
    settings = Settings.env()
    try:
        if args.command == "build":
            build(args.root)
        elif args.command == "validate":
            validate(args.root)
            print("Family splits and source anchors valid; this is not semantic validation.")
        elif args.command == "freeze":
            freeze(args.root, settings, source_reviewed=args.source_reviewed)
        elif args.command == "report":
            report(args.root, args.batch if args.batch != "development-1" else None)
        elif args.command == "review-packet":
            review_packet(args.root)
        else:
            db = Database(settings.database_url)
            objects = Objects(settings.object_root)
            if args.command == "ingest":
                ingest(args.root, db, objects, LocalEmbeddings(settings.embedding_cache))
            else:
                policy.require(1 <= args.limit <= 60, "invalid_limit", 422)
                run_batch(
                    args.root,
                    db,
                    objects,
                    settings,
                    args.split,
                    args.limit,
                    args.campaign,
                    args.batch,
                    args.interval,
                )
    except policy.Rejected as exc:
        p.exit(1, exc.code + "\n")


if __name__ == "__main__":
    main()
