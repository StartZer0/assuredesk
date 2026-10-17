import argparse
from contextlib import contextmanager
import hashlib
import threading
import time

import psycopg
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from sqlalchemy import or_, select

from . import policy
from .config import Settings
from .db import Chunk, Database, Job, Run, OperationalState, Source, db_time, uid, digest
from .providers import KimiProvider, LocalEmbeddings
from .workflow import Engine


def psycopg_url(db):
    return db.engine.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg:", "postgresql:", 1
    )


def claim(db, owner, run_id=None):
    with db.transaction() as s:
        job = s.scalar(
            select(Job)
            .where(
                Job.cancel.is_(False),
                Job.run_id == run_id if run_id else True,
                Job.attempts < 3,
                or_(Job.status == "queued", (Job.status == "running") & (Job.lease < db_time(s))),
            )
            .order_by(Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        job.owner, job.generation, job.status = owner, job.generation + 1, "running"
        job.lease, job.attempts = db_time(s) + 120, job.attempts + 1
        return job.id, job.generation


def heartbeat(db, ident, owner, generation, stop):
    while not stop.wait(20):
        with db.transaction() as s:
            job = s.get(Job, ident)
            if not job or job.owner != owner or job.generation != generation or job.cancel:
                return
            if job.status != "running" or job.lease < db_time(s):
                return
            job.lease = db_time(s) + 120


def index_pending(db, embeddings):
    with db.transaction() as s:
        chunks = list(
            s.scalars(select(Chunk).where(Chunk.embedding.is_(None), Chunk.embedding_model == "").limit(20))
        )
        pending = [(c.id, s.get(Source, c.source_id).title + "\n" + c.text) for c in chunks]
    for ident, text in pending:
        try:
            with db.transaction() as s:
                cached = s.scalar(
                    select(Chunk)
                    .where(
                        Chunk.metadata_record["index_text_hash"].as_string() == digest(text),
                        Chunk.metadata_record["embedding_revision"].as_string()
                        == getattr(embeddings, "revision", embeddings.model_id),
                        Chunk.embedding_model == embeddings.model_id,
                        Chunk.embedding.is_not(None),
                    )
                    .limit(1)
                )
                vector = list(cached.embedding) if cached else None
            if vector is None:
                vector = embeddings.documents([text])[0]
            model = embeddings.model_id
        except policy.Rejected as exc:
            if exc.code != "embedding_input_limit":
                raise
            vector, model = None, "rejected:embedding_input_limit"
        with db.transaction() as s:
            chunk = s.get(Chunk, ident)
            if chunk:
                chunk.embedding, chunk.embedding_model = vector, model
                chunk.metadata_record = {
                    **chunk.metadata_record,
                    "embedding_revision": getattr(embeddings, "revision", model),
                    "index_text_hash": digest(text),
                    "preprocessing": "title-child-v2",
                }


@contextmanager
def saver_locked(db, run_id):
    lock_key = int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8], "big", signed=True)
    with psycopg.connect(psycopg_url(db), autocommit=True, prepare_threshold=0, row_factory=dict_row) as conn:
        locked = conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (lock_key,)).fetchone()["ok"]
        policy.require(locked, "run_busy", 409)
        try:
            yield PostgresSaver(conn)
        finally:
            if not conn.closed:
                exists = conn.execute("SELECT 1 FROM runs WHERE id=%s", (run_id,)).fetchone()
                if not exists and run_id != "schema-setup":
                    # A concurrent deletion may have raced the saver. Remove its final reference-only write.
                    saver = PostgresSaver(conn)
                    saver.delete_thread(run_id)
                conn.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))


def execute(db, provider, embeddings, owner, ident, generation):
    stop = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(db, ident, owner, generation, stop), daemon=True)
    thread.start()
    status, reason = "failed", "execution_failed"
    try:
        with db.transaction() as s:
            job = s.get(Job, ident)
            run_id, resume = job.run_id, job.resume
        with saver_locked(db, run_id) as saver:
            with db.transaction() as s:
                policy.epoch(s, lock=True)
                job = s.get(Job, ident)
                policy.require(
                    job.owner == owner
                    and job.generation == generation
                    and job.lease > db_time(s)
                    and not job.cancel,
                    "lease_lost",
                    409,
                )
                run = s.get(Run, run_id)
                if run.active_started:
                    run.elapsed += max(0, time.time() - run.active_started)
                run.active_started = time.time()
                run.status = "running"
            graph = Engine(db, provider, embeddings, job_guard=(ident, owner, generation)).graph(saver)
            config = {"configurable": {"thread_id": run_id}, "recursion_limit": 24}
            snapshot = graph.get_state(config)
            if resume:
                initial = Command(resume=True)
            else:
                initial = None if snapshot.values else {"run_id": run_id, "route": "search"}
            output = graph.invoke(initial, config)
            status = "paused" if output.get("__interrupt__") else "succeeded"
            reason = ""
    except policy.Rejected as exc:
        reason = exc.code
    except Exception:
        # No raw exception body: providers and parsers can echo restricted content.
        reason = "execution_failed"
    finally:
        stop.set()
        thread.join(timeout=2)
        with db.transaction() as s:
            policy.epoch(s, lock=True)
            job = s.get(Job, ident)
            if job and job.owner == owner and job.generation == generation and job.lease > db_time(s):
                run = s.get(Run, job.run_id)
                if run.active_started:
                    run.elapsed += max(0, time.time() - run.active_started)
                run.active_started = None
                if job.cancel:
                    status, reason = "cancelled", "cancelled"
                job.status, job.lease = status, 0
                if status in {"failed", "cancelled"}:
                    run.status, run.stop_reason = status, reason
        print(f"job={ident} status={status} reason={reason}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings.env()
    db = Database(settings.database_url)
    provider = KimiProvider(settings)
    embeddings = LocalEmbeddings(settings.embedding_cache)
    owner = uid()
    while True:
        with db.transaction() as s:
            state = s.get(OperationalState, "worker")
            if state is None:
                state = OperationalState(key="worker")
                s.add(state)
            state.updated, state.details = db_time(s), {"owner": owner}
        try:
            index_pending(db, embeddings)
        except policy.Rejected as exc:
            # Oversized/unembeddable input must not prevent existing question jobs from running.
            with db.transaction() as s:
                s.merge(
                    OperationalState(key="ingestion_error", updated=db_time(s), details={"reason": exc.code})
                )
            print(f"indexing status=blocked reason={exc.code}", flush=True)
        work = claim(db, owner)
        if work:
            execute(db, provider, embeddings, owner, *work)
            if provider.daily_limited:
                print(
                    "Kimi daily allowance exhausted. Restart the worker after the provider resets it.",
                    flush=True,
                )
                return
        if args.once:
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
