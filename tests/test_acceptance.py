"""Regression tests for the unfinished acceptance requirements."""

import math
import pytest
from sqlalchemy import select
from app import policy, service
from app.db import Attempt, Draft, Event, Question, QuestionVersion, Source, User, Workbook
from app.operations import delete_source, retention, status
from app.scoring import ranking, bundle_coverage, summarize
from app.schema import Support
from app.workflow import Engine
from conftest import Embeddings, Generator
from test_boundaries import start, propose, user
from test_api import client


def test_ranking_known_order_duplicates_and_empty_gold():
    m = ranking(["noise", "a", "a", "b"], {"a", "b"}, 4)
    assert m["recall"]["value"] == 1 and m["precision"]["value"] == 0.5
    assert m["mrr"] == 0.5
    assert m["ndcg"] == pytest.approx((1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3)))
    assert ranking([], set(), 3)["recall"]["value"] is None
    assert ranking(["a"], {"a", "b"}, 3)["precision"]["value"] == 1 / 3


def test_bundle_requires_complete_spans_and_all_sources():
    case = {
        "requirements": [
            {
                "bundles": [
                    [
                        {"source": "s", "hash": "h", "start": 0, "end": 10},
                        {"source": "t", "hash": "i", "start": 0, "end": 4},
                    ]
                ]
            }
        ]
    }
    spans = {
        "a": {"source": "s", "hash": "h", "start": 0, "end": 6},
        "b": {"source": "s", "hash": "h", "start": 6, "end": 10},
        "c": {"source": "t", "hash": "i", "start": 0, "end": 4},
    }
    assert bundle_coverage(case, ["a", "c"], spans)["numerator"] == 0
    assert bundle_coverage(case, ["a", "b", "c"], spans)["numerator"] == 1
    spans["c"]["hash"] = "stale"
    assert bundle_coverage(case, list(spans), spans)["numerator"] == 0


def test_missing_runs_do_not_improve_complete_score():
    cases = [
        {"id": str(i), "family": str(i), "disposition": "ANSWERABLE", "requirements": []} for i in range(2)
    ]
    runs = [{"case": "0", "variant": "corrective", "run": "r", "draft": {"answer": "Yes", "evidence": []}}]
    report = summarize(cases, runs, [{"run": "r", "adjudicated": True, "complete_supported": True}], {})
    assert report["variants"]["corrective"]["supported_complete"]["value"] == 0.5
    assert report["variants"]["corrective"]["missing_runs"] == ["1"]
    assert report["status"] == "incomplete" and not report["semantic_gate"]["passed"]


def test_ranking_population_excludes_cases_without_answerable_retrieval_target():
    anchor = {"source": "s", "hash": "h", "start": 0, "end": 5}
    cases = [
        {"id": "yes", "family": "f", "disposition": "ANSWERABLE", "requirements": [{"bundles": [[anchor]]}]},
        {"id": "no", "family": "g", "disposition": "UNSUPPORTED", "requirements": [{"bundles": []}]},
    ]
    runs = [
        {
            "case": c["id"],
            "variant": "hybrid",
            "run": c["id"],
            "trace": {"retrieval": [{"candidate_ids": ["a"]}]},
        }
        for c in cases
    ]
    report = summarize(cases, runs, [], {"a": anchor})
    metrics = report["variants"]["hybrid"]["retrieval"]["first_candidates"]["3"]
    assert metrics["precision"] == {"mean": 1 / 3, "cases": 1}
    assert metrics["recall"] == {"mean": 1, "cases": 1}
    assert report["variants"]["hybrid"]["attempted"] == 2


def test_missing_and_failed_runs_are_zero_scored_in_every_retrieval_stage():
    anchor = {"source": "s", "hash": "h", "start": 0, "end": 5}
    cases = [
        {
            "id": ident,
            "family": ident,
            "disposition": "ANSWERABLE",
            "requirements": [{"bundles": [[anchor]]}],
        }
        for ident in ("success", "failed", "missing")
    ]
    runs = [
        {
            "case": "success",
            "variant": "hybrid",
            "run": "r1",
            "trace": {
                "retrieval": [{"candidate_ids": ["a"]}],
                "inputs": [{"supplied_ids": ["a"]}],
            },
        },
        {"case": "failed", "variant": "hybrid", "run": "r2", "stop": "provider_failed"},
    ]
    report = summarize(cases, runs, [], {"a": {**anchor, "parent_start": 0, "parent_end": 5}})
    metrics = report["variants"]["hybrid"]
    assert metrics["missing_runs"] == ["missing"]
    for stage, summary in metrics["retrieval"].items():
        for k in (1, 3, 6, 12, 20):
            assert summary[str(k)]["recall"] == {"mean": 1 / 3, "cases": 3}
            assert summary[str(k)]["precision"] == {"mean": 1 / (3 * k), "cases": 3}
            assert summary[str(k)]["mrr"] == {"mean": 1 / 3, "cases": 3}
            assert summary[str(k)]["ndcg"] == {"mean": 1 / 3, "cases": 3}
        assert summary["bundle_coverage"] == {"numerator": 1, "denominator": 3, "value": 1 / 3}
        assert len(metrics["retrieval_cases"][stage]) == 3
    assert report["status"] == "incomplete"


@pytest.mark.parametrize("legacy_generation", [False, True])
def test_reindex_returns_source_identity_that_activation_can_supersede(env, monkeypatch, legacy_generation):
    from app.db import Chunk

    with env.db.transaction() as s:
        chunk = s.scalar(select(Chunk).where(Chunk.source_id == env.sources["public"]))
        blocks = [{"text": chunk.text, "locator": chunk.locator}]
    monkeypatch.setattr("app.web.parse_source", lambda *args: blocks)
    c = client(env, "reviewer")
    response = c.post(f"/v1/sources/{env.sources['public']}/reindex")
    assert response.status_code == 202
    rebuilt_id = response.json()["id"]
    with env.db.transaction() as s:
        rebuilt = s.get(Source, rebuilt_id)
        assert rebuilt.pipeline["rebuild_of"] == env.sources["public"]
        if legacy_generation:
            rebuilt.pipeline = {
                **rebuilt.pipeline,
                "rebuild_of": s.get(Source, env.sources["public"]).generation,
            }
    pending = next(x for x in c.get("/v1/sources?account=acme").json() if x["id"] == rebuilt_id)
    assert pending["rebuild_of"] == response.json()["supersedes"] == env.sources["public"]
    with env.db.transaction() as s:
        chunk = s.scalar(select(Chunk).where(Chunk.source_id == rebuilt_id))
        chunk.embedding, chunk.embedding_model = [1.0] + [0.0] * 383, "fake"
    assert (
        c.post(f"/v1/sources/{rebuilt_id}/activate", json={"supersedes": pending["rebuild_of"]}).status_code
        == 200
    )
    with env.db.transaction() as s:
        assert s.get(Source, rebuilt_id).active
        assert s.get(Source, env.sources["public"]).superseded


def test_immutable_intermediate_question_revisions(env):
    c = client(env)
    for revision, value in [(1, "Changed once"), (2, "Changed twice")]:
        assert (
            c.patch(f"/v1/questions/{env.q}", json={"expected_revision": revision, "text": value}).status_code
            == 200
        )
    h = c.get(f"/v1/questions/{env.q}/history").json()
    assert [x["text"] for x in h["questions"]][-2:] == ["Changed once", "Changed twice"]
    with env.db.transaction() as s:
        assert len(list(s.scalars(select(QuestionVersion).where(QuestionVersion.question_id == env.q)))) == 3


def test_claim_mapping_binds_approval_and_requires_checks(env):
    with env.db.transaction() as s:
        u = user(s, env, "reviewer")
        d = service.new_draft(s, u, env.q, 1, "Yes", "TLS 1.3", [env.chunks["public"]])
        with pytest.raises(policy.Rejected, match="claim_review_required"):
            service.approve(s, u, env.q, d.revision, True, claim_reviews=[False])
        approval = service.approve(
            s,
            u,
            env.q,
            d.revision,
            True,
            claim_reviews=[True],
            reason="Public TLS statement supports this claim",
        )
        d.claims = [{"text": "Unreviewed extra claim", "evidence_ids": d.evidence}]
        q, b = service.question_context(s, u, env.q)
        assert service.fingerprint(s, u, q, b, d) != approval.fingerprint
        assert approval.support_review["revision"] == d.revision


def test_checkpoint_loss_after_artifact_does_not_duplicate_stage(env):
    ident = start(env)
    gen = Generator([propose, Support(supported=True, missing=[], next_queries=[])])
    engine = Engine(env.db, gen, Embeddings())
    state = {"run_id": ident, "step": 0}
    state.update(engine.bounded(engine.search)(state))
    state.update(engine.bounded(engine.assess)(state))
    output = engine.bounded(engine.check)(state)
    with env.db.transaction() as s:
        draft_id = s.get(Question, env.q).current_draft
        attempts = len(list(s.scalars(select(Attempt))))
    reconstructed = Engine(env.db, Generator([]), Embeddings())
    assert reconstructed.bounded(reconstructed.check)(state) == output
    with env.db.transaction() as s:
        assert s.get(Question, env.q).current_draft == draft_id
        assert len(list(s.scalars(select(Draft)))) == 1
        assert len(list(s.scalars(select(Attempt)))) == attempts


def test_replay_rechecks_permissions(env):
    ident = start(env)
    engine = Engine(env.db, Generator([]), Embeddings())
    state = {"run_id": ident, "step": 0}
    engine.bounded(engine.search)(state)
    with env.db.transaction() as s:
        s.get(User, env.sales).active = False
    with pytest.raises(policy.Rejected):
        engine.bounded(engine.search)(state)


def test_checker_sees_uncited_qualification_and_correction_preserves_support(env, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from app.schema import Proposal, Requirement
    import app.workflow as workflow

    public, extra = env.chunks["public"], env.chunks["acme"]
    results = iter([[public, extra], [extra]])
    monkeypatch.setattr(workflow, "retrieve", lambda *args: next(results))

    def first_check(payload):
        assert payload["cited_ids"] == [public]
        assert {x["id"] for x in payload["evidence"]} == {public, extra}
        return Support(supported=False, missing=["Required qualification"], next_queries=["qualification"])

    def corrected(payload):
        assert payload["missing_requirements"] == ["Required qualification"]
        assert {x["id"] for x in payload["evidence"]} == {public, extra}
        return Proposal(
            status="draft_proposed",
            requirements=[
                Requirement(text="Scoped TLS policy", coverage="supported", evidence_ids=[public, extra])
            ],
            next_queries=[],
            answer="Yes",
            explanation="Scoped TLS policy and qualification.",
        )

    generator = Generator(
        [propose, first_check, corrected, Support(supported=True, missing=[], next_queries=[])]
    )
    ident = start(env)
    Engine(env.db, generator, Embeddings()).graph(InMemorySaver()).invoke(
        {"run_id": ident}, {"configurable": {"thread_id": ident}}
    )
    with env.db.transaction() as s:
        draft = s.get(Draft, s.get(Question, env.q).current_draft)
        assert draft.supported and set(draft.evidence) == {public, extra}


def test_kimi_contract_accounts_for_invalid_output_and_does_not_retry(monkeypatch):
    import json
    from io import BytesIO
    from urllib.error import HTTPError
    from app.config import Settings
    from app.providers import KimiProvider
    import app.providers as providers

    calls = []

    def response(request, timeout):
        assert timeout == 40
        body = json.loads(request.data)
        calls.append(body)
        assert body["reasoning_effort"] == "low" and body["max_completion_tokens"] == 1200
        assert "thinking" not in body and "temperature" not in body
        assert body["response_format"]["json_schema"]["strict"]
        return BytesIO(
            json.dumps(
                {
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                    "choices": [
                        {
                            "message": {
                                "content": '{"supported":true,"missing":[],"next_queries":[],"extra":1}'
                            }
                        }
                    ],
                }
            ).encode()
        )

    monkeypatch.setattr(providers, "urlopen", response)
    provider = KimiProvider(Settings("sqlite://", api_key="test-placeholder"))
    parsed, cost = provider.invoke("check", {"question": "Test"}, Support)
    assert parsed is None and cost == pytest.approx((100 * 6 + 20 * 15) / 1_000_000)

    def failure(request, timeout):
        calls.append(None)
        raise HTTPError(request.full_url, 429, "Rate limit", {}, None)

    monkeypatch.setattr(providers, "urlopen", failure)
    with pytest.raises(policy.Rejected, match="provider_failed"):
        provider.invoke("check", {"question": "Test"}, Support)
    assert len(calls) == 2 and provider.last_usage == {} and provider.last_error["http_status"] == 429


def test_kimi_daily_limit_stops_further_dispatches(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    from app.config import Settings
    from app.providers import KimiProvider
    import app.providers as providers

    calls = []

    def failure(request, timeout):
        calls.append(request)
        raise HTTPError(
            request.full_url,
            429,
            "Rate limit",
            {},
            BytesIO(b'{"error":{"message":"TPD limit reached: sensitive echoed input"}}'),
        )

    monkeypatch.setattr(providers, "urlopen", failure)
    provider = KimiProvider(Settings("sqlite://", api_key="test-placeholder"))
    with pytest.raises(policy.Rejected, match="provider_daily_limit"):
        provider.invoke("check", {"question": "Test"}, Support)
    assert provider.daily_limited and provider.last_error["limit_kind"] == "daily"
    assert "sensitive" not in str(provider.last_error)
    with pytest.raises(policy.Rejected, match="provider_daily_limit"):
        provider.admit()
    with pytest.raises(policy.Rejected, match="provider_daily_limit"):
        provider.invoke("check", {"question": "Test"}, Support)
    assert len(calls) == 1


def test_restricted_search_does_not_cross_customer(env):
    rows = client(env, "reviewer").get(f"/v1/search?workbook_id={env.book}&query=CANARY").json()
    assert env.chunks["internal"] in {r["id"] for r in rows}
    assert env.chunks["nova"] not in {r["id"] for r in rows}
    assert client(env).get(f"/v1/search?workbook_id={env.book}&query=CANARY").status_code == 404


def test_deletion_purges_derived_records_and_keeps_tombstone(env):
    with env.db.transaction() as s:
        service.new_draft(s, user(s, env), env.q, 1, "Yes", "TLS 1.3", [env.chunks["public"]])
        original = s.get(Source, env.sources["public"]).object_hash
    result = delete_source(env.db, env.objects, env.sources["public"], env.reviewer)
    assert result["removed_workbooks"] == 1
    with env.db.transaction() as s:
        assert s.get(Source, env.sources["public"]) is None and s.get(Workbook, env.book) is None
        assert not list(s.scalars(select(Draft)))
        assert s.scalar(select(Event).where(Event.action == "source_deleted")).details["tombstone"]
    assert not (env.objects.root / original).exists()


def test_retention_preview_then_purge(env):
    with env.db.transaction() as s:
        s.get(Workbook, env.book).created = 1
    assert env.book in retention(env.db, env.objects)["expired_workbooks"]
    with env.db.transaction() as s:
        assert s.get(Workbook, env.book)
    retention(env.db, env.objects, apply=True)
    with env.db.transaction() as s:
        assert s.get(Workbook, env.book) is None


def test_ops_alerts_for_missing_worker(env):
    assert "worker_heartbeat_missing" in status(env.db, env.objects)["alerts"]


def test_ops_counts_review_routed_errors_and_recent_auth_failures(env):
    import time
    from app.db import Run

    ident = start(env)
    with env.db.transaction() as s:
        run = s.get(Run, ident)
        run.status, run.stop_reason = "awaiting_review", "provider_failed"
        for age, code in [(0, 401), (0, 403), (3600, 401), (0, 429)]:
            s.add(
                Attempt(
                    run_id=ident,
                    workbook_id=env.book,
                    kind="generation",
                    reserved=0.01,
                    created=time.time() - age,
                    details={"http_status": code},
                )
            )
    result = status(env.db, env.objects)
    assert result["failed_runs"] == 0
    assert result["failure_reasons"]["provider_failed"] == 1
    assert result["recent_provider_auth_failures"] == 2
    assert "provider_authentication_failures" in result["alerts"]
    with env.db.transaction() as s:
        s.get(Run, ident).stop_reason = "spend_limit"
    assert status(env.db, env.objects)["cap_stops"] == {"spend_limit": 1}


def test_ops_counts_exports_invalidated_by_revision(env):
    from test_boundaries import approve_all

    approve_all(env)
    service.build_export(env.db, env.sales, env.objects, env.book)
    assert status(env.db, env.objects)["invalidated_exports"] == 0
    with env.db.transaction() as s:
        q = s.get(Question, env.q)
        service.new_draft(s, user(s, env), q.id, q.revision, "Unknown", "Updated review needed.", [])
    assert status(env.db, env.objects)["invalidated_exports"] == 1


def correction_scenario(env):
    from app.db import Chunk
    from app.schema import Proposal

    with env.db.transaction() as s:
        reviewer = user(s, env, "reviewer")
        for i in range(18):
            value = f"Customer hosting region EU policy {i}"
            if i == 17:
                value = "Recovery archive retention is thirty days."
            src = service.add_source(
                s,
                reviewer,
                env.objects,
                value.encode(),
                [{"text": value, "locator": "section:1"}],
                dict(
                    family=f"recovery-{i}",
                    title=f"Recovery {i}",
                    account="*",
                    roles=["sales", "security_reviewer"],
                    disclosure="public",
                    audience=[],
                    valid_from="2026-01-01",
                    valid_until="2027-12-31",
                    authority="approved_policy",
                ),
            )
            c = s.scalar(select(Chunk).where(Chunk.source_id == src.id))
            c.embedding, c.embedding_model = ([-1.0] if i == 17 else [1.0]) + [0.0] * 383, "fake"
            service.activate_source(s, reviewer, src.id)
        s.get(Question, env.q).text = "Customer hosting region EU policy and archive window"

    def assess(payload):
        found = [e for e in payload["evidence"] if "thirty days" in e["text"]]
        hosting = [e for e in payload["evidence"] if "Customer hosting region EU policy" in e["text"]]
        if found and hosting:
            return Proposal(
                status="draft_proposed",
                requirements=[
                    {
                        "text": "Archive retention is thirty days.",
                        "coverage": "supported",
                        "evidence_ids": [found[0]["id"]],
                    },
                    {
                        "text": "Customer hosting region is EU.",
                        "coverage": "supported",
                        "evidence_ids": [hosting[0]["id"]],
                    },
                ],
                next_queries=[],
                answer="Yes",
                explanation="Customer hosting region is EU. Archive retention is thirty days.",
            )
        return Proposal(
            status="needs_evidence",
            requirements=[{"text": "retention", "coverage": "missing", "evidence_ids": []}],
            next_queries=["recovery archive retention thirty days"],
            answer=None,
            explanation="",
        )

    class QueryEmbeddings(Embeddings):
        def query(self, text):
            return ([-1.0] if "thirty" in text else [1.0]) + [0.0] * 383

    return Generator(
        [assess, assess, Support(supported=True, missing=[], next_queries=[])]
    ), QueryEmbeddings()


def test_correction_recovers_with_real_retrieval(env):
    from langgraph.checkpoint.memory import InMemorySaver
    from app.db import Run

    gen, embeddings = correction_scenario(env)
    ident = start(env)
    Engine(env.db, gen, embeddings).graph(InMemorySaver()).invoke(
        {"run_id": ident, "route": "search"}, {"configurable": {"thread_id": ident}}
    )
    with env.db.transaction() as s:
        run = s.get(Run, ident)
        assert run.rounds == 2 and run.record["trace"][1]["new_ids"]
        assert s.get(Draft, run.record["draft_id"]).supported


def test_pending_rebuild_cached_vectors_and_atomic_supersession(env):
    from app.db import Chunk
    from app.worker import index_pending
    from test_boundaries import approve_all

    class Indexer:
        model_id = "fake"
        revision = "test-artifact-v1"
        calls = 0

        def documents(self, texts):
            self.calls += len(texts)
            return [[1.0] + [0.0] * 383 for _ in texts]

    indexer = Indexer()
    approve_all(env)
    with env.db.transaction() as s:
        u = user(s, env, "reviewer")
        old = s.get(Source, env.sources["public"])
        chunk = s.scalar(select(Chunk).where(Chunk.source_id == old.id))
        metadata = {
            key: getattr(old, key)
            for key in (
                "family",
                "title",
                "account",
                "roles",
                "disclosure",
                "audience",
                "valid_from",
                "valid_until",
                "authority",
                "provenance",
            )
        }
        blocks = [{"text": chunk.text, "locator": chunk.locator}]
        content = env.objects.get(old.object_hash)
        rebuilt = service.add_source(s, u, env.objects, content, blocks, metadata, rebuild_of=old.id)
        rebuilt_id = rebuilt.id
        assert rebuilt.pipeline["rebuild_of"] == old.id
        assert (
            service.add_source(s, u, env.objects, content, blocks, metadata, rebuild_of=old.id).id
            == rebuilt_id
        )
        assert not rebuilt.active and not old.superseded
        service.export_manifest(s, u, s.get(Workbook, env.book))
        with pytest.raises(policy.Rejected, match="source_not_indexed"):
            service.activate_source(s, u, rebuilt_id, supersedes=old.id)
    index_pending(env.db, indexer)
    assert indexer.calls == 1
    with env.db.transaction() as s:
        u = user(s, env, "reviewer")
        service.activate_source(s, u, rebuilt_id, supersedes=env.sources["public"])
        assert s.get(Source, rebuilt_id).active and s.get(Source, env.sources["public"]).superseded
        with pytest.raises(policy.Rejected):
            service.export_manifest(s, u, s.get(Workbook, env.book))
        again = service.add_source(s, u, env.objects, content, blocks, metadata, rebuild_of=rebuilt_id)
        again_id = again.id
    index_pending(env.db, indexer)
    assert indexer.calls == 1
    with env.db.transaction() as s:
        assert s.scalar(select(Chunk).where(Chunk.source_id == again_id)).embedding_model == "fake"


def test_chunked_upload_limit_without_content_length(env):
    c = client(env)
    response = c.post("/v1/questionnaires/import", content=(b"x" * (6 * 1024**2) for _ in range(2)))
    assert response.status_code == 413


def test_evidence_picker_excludes_readable_internal_and_other_customer(env):
    c = client(env, "reviewer")
    options = c.get(f"/v1/questions/{env.q}/evidence-options").json()
    ids = {r["id"] for r in options}
    assert env.chunks["public"] in ids
    assert env.chunks["internal"] not in ids and env.chunks["nova"] not in ids


@pytest.mark.parametrize("changed", [False, True])
def test_provider_admission_preserves_active_time_and_rechecks_revision(env, monkeypatch, changed):
    import app.workflow as workflow
    from app.db import Run

    clock = [1000.0]
    monkeypatch.setattr(workflow.time, "time", lambda: clock[0])
    ident = start(env)
    with env.db.transaction() as s:
        run = s.get(Run, ident)
        run.active_started, run.elapsed = 990.0, 5.0

    class Paced(Generator):
        def admit(self):
            clock[0] += 100
            if changed:
                with env.db.transaction() as s:
                    s.get(Question, env.q).revision += 1

    generator = Paced([Support(supported=True, missing=[], next_queries=[])])
    engine = Engine(env.db, generator, Embeddings())
    if changed:
        with pytest.raises(policy.Rejected, match="stale_run"):
            engine.call(ident, "check", {}, Support)
        assert not generator.calls
        with env.db.transaction() as s:
            assert not list(s.scalars(select(Attempt).where(Attempt.run_id == ident)))
    else:
        assert engine.call(ident, "check", {}, Support).supported
        with env.db.transaction() as s:
            run = s.get(Run, ident)
            assert run.active_started == 1090 and run.elapsed == 5
            assert run.record["provider_wait_seconds"] == 100
            assert len(list(s.scalars(select(Attempt).where(Attempt.run_id == ident)))) == 1


def test_shared_format_repair_fits_nearly_full_input_without_dropping_evidence(env):
    from app.providers import input_bound, request_messages
    from app.db import Run

    payload = {"evidence": [{"id": "retained", "text": "Original source evidence."}], "padding": ""}
    payload["padding"] = "x" * (5890 - input_bound(request_messages("check", payload, Support), Support))
    generator = Generator([None, Support(supported=True, missing=[], next_queries=[])])
    ident = start(env)
    assert Engine(env.db, generator, Embeddings()).call(ident, "check", payload, Support).supported
    assert len(generator.calls) == 2
    repaired = generator.calls[1][1]
    assert repaired["evidence"] == payload["evidence"]
    assert input_bound(request_messages("check", repaired, Support), Support) <= 6000
    with env.db.transaction() as s:
        assert s.get(Run, ident).repair_used and s.get(Run, ident).generation_attempts == 2
