"""Opt-in real PostgreSQL tests, isolated in disposable per-test schemas."""

from concurrent.futures import ThreadPoolExecutor
import os
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app import policy, service
from app.db import Attempt, Base, Database, Draft, Job, Question, Run, Workbook
from app.retrieval import retrieve
from app.schema import Support
from app.worker import claim, saver_locked, execute
from app.workflow import Engine
from conftest import Embeddings, Generator
from test_boundaries import start, propose, user


@pytest.fixture
def pg(env):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for real PostgreSQL integration tests")
    schema = "test_" + uuid4().hex
    root = create_engine(url)
    with root.begin() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
    scoped = make_url(url).update_query_dict({"options": f"-csearch_path={schema},public"})
    db = Database(scoped)
    Base.metadata.create_all(db.engine, checkfirst=False)
    with env.db.transaction() as original, db.transaction() as target:
        # Copy fixtures by table order, without sharing ORM identity/session state.
        for table in Base.metadata.sorted_tables:
            rows = original.execute(select(table)).mappings().all()
            if rows:
                target.execute(table.insert(), [dict(r) for r in rows])
    old = env.db
    env.db = db
    yield env
    env.db = old
    db.engine.dispose()
    with root.begin() as c:
        c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    root.dispose()


def test_pg_exact_dense_filter(pg):
    with pg.db.transaction() as s:
        ids = retrieve(
            s, user(s, pg), s.get(Workbook, pg.book), ["NOVA-CANARY"], [[1.0] + [0.0] * 383], "dense", "fake"
        )
        assert pg.chunks["public"] in ids and pg.chunks["nova"] not in ids


def test_pg_newest_run_ordering(pg, monkeypatch):
    from test_api import test_questionnaire_displays_newest_run_by_creation_not_random_id

    test_questionnaire_displays_newest_run_by_creation_not_random_id(pg, monkeypatch)


def test_pg_operator_summaries(pg):
    from test_acceptance import (
        test_ops_counts_exports_invalidated_by_revision,
        test_ops_counts_review_routed_errors_and_recent_auth_failures,
    )

    test_ops_counts_review_routed_errors_and_recent_auth_failures(pg)
    test_ops_counts_exports_invalidated_by_revision(pg)


def test_concurrent_budget_reservations_cannot_overspend(pg):
    ident = start(pg)
    with pg.db.transaction() as s:
        s.add(Attempt(run_id="other", workbook_id="other", kind="generation", reserved=4.985))

    def reserve(_):
        try:
            Engine(pg.db, Generator([]), Embeddings()).reserve(ident, "generation")
            return True
        except policy.Rejected as e:
            assert e.code == "spend_limit"
            return False

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(reserve, range(2)))
    assert sorted(outcomes) == [False, True]
    with pg.db.transaction() as s:
        assert s.get(Run, ident).generation_attempts == 1


def test_duplicate_job_delivery_claimed_once(pg):
    start(pg)
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda n: claim(pg.db, str(n)), range(2)))
    assert sum(x is not None for x in claims) == 1


def test_expired_lease_reclaimed_with_fence(pg):
    ident = start(pg)
    jid, generation = claim(pg.db, "first")
    with pg.db.transaction() as s:
        s.get(Job, jid).lease = time.time() - 1
    assert claim(pg.db, "second") == (jid, generation + 1)
    with pytest.raises(policy.Rejected, match="lease_lost"):
        Engine(pg.db, Generator([]), Embeddings(), job_guard=(jid, "first", generation)).search(
            {"run_id": ident}
        )


def test_graph_pause_process_reconstruction_resume(pg):
    ident = start(pg)
    provider = Generator([propose, Support(supported=True, missing=[], next_queries=[])])
    with saver_locked(pg.db, ident) as saver:
        saver.setup()
    claimed = claim(pg.db, "first")
    execute(pg.db, provider, Embeddings(), "first", *claimed)
    with pg.db.transaction() as s:
        run = s.get(Run, ident)
        assert run.status == "awaiting_review" and run.active_started is None
        q = s.get(Question, pg.q)
        service.approve(s, user(s, pg, "reviewer"), q.id, q.revision, True)
    claimed = claim(pg.db, "restarted")
    assert claimed
    execute(pg.db, Generator([]), Embeddings(), "restarted", *claimed)
    with pg.db.transaction() as s:
        assert s.get(Run, ident).status == "succeeded"
        assert len(list(s.scalars(select(Draft)))) == 1


def test_checkpoint_contains_no_evidence_text(pg):
    ident = start(pg)
    config = {"configurable": {"thread_id": ident}}
    with saver_locked(pg.db, ident) as saver:
        saver.setup()
        Engine(
            pg.db, Generator([propose, Support(supported=True, missing=[], next_queries=[])]), Embeddings()
        ).graph(saver).invoke({"run_id": ident, "route": "search"}, config)
        state = saver.get(config)
        assert "CANARY" not in str(state) and "TLS" not in str(state)


@pytest.mark.parametrize("fault", ["before_artifact", "after_artifact"])
def test_process_death_around_stage_commit(pg, fault):
    """A real child exit loses the graph cursor but not committed application artifacts."""
    import subprocess
    import sys
    from app.db import Stage

    ident = start(pg)
    engine = Engine(pg.db, Generator([propose]), Embeddings())
    state = {"run_id": ident, "step": 0}
    state.update(engine.bounded(engine.search)(state))
    state.update(engine.bounded(engine.assess)(state))
    code = """
import os
from app.db import Database
from app.schema import Support
from app.workflow import Engine
class Provider:
 def reserve_cost(self): return .01
 def invoke(self, *args):
  if os.environ['FAULT'] == 'before_artifact': os._exit(23)
  return Support(supported=True, missing=[], next_queries=[]), .001
engine=Engine(Database(os.environ['SCOPED_DATABASE']),Provider(),None)
engine.bounded(engine.check)({'run_id':os.environ['RUN_ID'],'step':int(os.environ['STEP'])})
os._exit(23)
"""
    child = subprocess.run(
        [sys.executable, "-c", code],
        env={
            **os.environ,
            "SCOPED_DATABASE": pg.db.engine.url.render_as_string(hide_password=False),
            "RUN_ID": ident,
            "STEP": str(state["step"]),
            "FAULT": fault,
        },
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == 23
    provider = Generator([Support(supported=True, missing=[], next_queries=[])])
    restarted = Engine(pg.db, provider, Embeddings())
    restarted.bounded(restarted.check)(state)
    with pg.db.transaction() as s:
        assert len(list(s.scalars(select(Draft)))) == 1
        assert s.get(Stage, restarted.stage_key(state, "check")).output["route"] == "review"
        assert len(provider.calls) == (1 if fault == "before_artifact" else 0)
        if fault == "before_artifact":
            assert s.scalar(select(Attempt).where(Attempt.status == "unknown")) is not None


def test_encrypted_fresh_restore_preserves_review_and_fences_jobs(env, tmp_path):
    """Real pg_dump/restore into two disposable databases, including pending work."""
    import subprocess
    import sys
    from cryptography.fernet import Fernet
    from app.db import Approval, Meta, Objects, User
    from app.operations import backup, restore

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for PostgreSQL recovery drill")
    root = create_engine(url, isolation_level="AUTOCOMMIT")
    names = ["recovery_" + uuid4().hex for _ in range(2)]
    databases = []
    try:
        for name in names:
            with root.connect() as c:
                c.execute(text(f'CREATE DATABASE "{name}"'))
            databases.append(Database(make_url(url).set(database=name)))
        source, target = databases
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env={**os.environ, "DATABASE_URL": source.engine.url.render_as_string(hide_password=False)},
            check=True,
            capture_output=True,
            timeout=30,
        )
        with env.db.transaction() as original, source.transaction() as s:
            for table in Base.metadata.sorted_tables:
                rows = original.execute(select(table)).mappings().all()
                if table.name == "meta":
                    s.get(Meta, 1).policy, s.get(Meta, 1).corpus = rows[0]["policy"], rows[0]["corpus"]
                elif rows:
                    s.execute(table.insert(), [dict(r) for r in rows])
            u = s.get(User, env.reviewer)
            for ident in env.questions:
                d = service.new_draft(s, u, ident, 1, "Unknown", "A complete answer is not established.", [])
                service.approve(
                    s, u, ident, d.revision, True, claim_reviews=[True], reason="Reviewed uncertainty"
                )
            q = s.get(Question, env.q)
            run = service.start_run(s, u, q.id, q.revision, "corrective")
            s.add(Attempt(run_id=run.id, workbook_id=env.book, kind="generation", reserved=0.01))
            run_id = run.id
            before, _ = service.export_manifest(s, u, s.get(Workbook, env.book))
        work = claim(source, "crashed-process")
        assert work
        key = tmp_path / "recovery.key"
        key.write_bytes(Fernet.generate_key())
        key.chmod(0o600)
        archive = tmp_path / "snapshot.fernet"
        started = time.monotonic()
        backup(source, env.objects, archive, key)
        assert b"database.dump" not in archive.read_bytes()
        recovered = Objects(tmp_path / "restored")
        result = restore(target, recovered, archive, key)
        with target.transaction() as s:
            assert (
                service.export_manifest(s, s.get(User, env.reviewer), s.get(Workbook, env.book))[0] == before
            )
            assert s.get(Run, run_id).stop_reason == "restored_requires_reconciliation"
            assert s.get(Job, work[0]).cancel
            assert s.scalar(select(Attempt).where(Attempt.run_id == run_id)).actual is None
            assert len(list(s.scalars(select(Approval)))) == 5
        assert result["approval_records"] == 5
        assert all(recovered.get(h.name) == env.objects.get(h.name) for h in recovered.root.iterdir())
        with pytest.raises(policy.Rejected, match="restore_requires_empty_database"):
            restore(target, recovered, archive, key)
        from pathlib import Path
        import json

        Path("output").mkdir(exist_ok=True)
        Path("output/restore-drill.json").write_text(
            json.dumps(
                {
                    **result,
                    "elapsed_seconds": time.monotonic() - started,
                    "approval_fingerprint_preserved": True,
                    "uncertain_job_fenced": True,
                    "unknown_charge_retained": True,
                },
                indent=2,
            )
        )
    finally:
        for db in databases:
            db.engine.dispose()
        for name in names:
            with root.connect() as c:
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        root.dispose()
