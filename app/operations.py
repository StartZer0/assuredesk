"""Small operator tools: health, retention, encrypted snapshots and fresh restores."""

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from datetime import datetime, timezone

from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.engine import make_url

from . import policy, service
from .config import Settings
from .db import (
    Approval,
    Attempt,
    Chunk,
    Database,
    Draft,
    Event,
    Export,
    Job,
    Login,
    Objects,
    OperationalState,
    Question,
    QuestionVersion,
    RequestKey,
    Run,
    Source,
    Stage,
    User,
    Workbook,
    db_time,
)


def status(db, objects):
    with db.transaction() as s:
        now = db_time(s)
        heartbeat = s.get(OperationalState, "worker")
        queued = list(s.scalars(select(Job).where(Job.status == "queued", Job.cancel.is_(False))))
        oldest = max((now - j.created for j in queued), default=0)
        worker_age = now - heartbeat.updated if heartbeat else None
        uncertain = s.scalar(select(func.count()).select_from(Attempt).where(Attempt.actual.is_(None)))
        failed = s.scalar(select(func.count()).select_from(Run).where(Run.status == "failed"))
        errors = [
            x.details for x in s.scalars(select(OperationalState).where(OperationalState.key.like("%error")))
        ]
        disk = shutil.disk_usage(objects.root)
        storage = 1 - disk.free / disk.total
        alerts = []
        if worker_age is None or worker_age > 150:
            alerts.append("worker_heartbeat_missing")
        if oldest > 120:
            alerts.append("queue_age_exceeded")
        if storage >= 0.8:
            alerts.append("storage_above_80_percent")
        if errors:
            alerts.append("ingestion_errors")
        reasons = Counter(s.scalars(select(Run.stop_reason).where(Run.stop_reason != "")))
        failures = Counter(
            s.scalars(
                select(Run.stop_reason).where(
                    (Run.status == "failed")
                    | Run.stop_reason.in_(
                        ["provider_failed", "embedding_failed", "invalid_model_output", "unknown_evidence"]
                    )
                )
            )
        )
        auth_failures = s.scalar(
            select(func.count())
            .select_from(Attempt)
            .where(
                Attempt.created >= now - 900,
                Attempt.kind == "generation",
                Attempt.details["http_status"].as_integer().in_([401, 403]),
            )
        )
        if auth_failures >= 2:
            alerts.append("provider_authentication_failures")
        invalidated_exports = 0
        for artifact, actor in s.execute(
            select(Export, Event.actor).outerjoin(
                Event, (Event.target == Export.id) & (Event.action == "export_created")
            )
        ):
            # Reuse the download policy without reading objects, recording a download,
            # or exposing workbook contents to the operations viewer.
            try:
                fingerprint, _ = service.export_manifest(
                    s, s.get(User, actor) if actor else None, s.get(Workbook, artifact.workbook_id)
                )
                invalidated_exports += fingerprint != artifact.fingerprint
            except policy.Rejected:
                invalidated_exports += 1
        return {
            "queue_count": len(queued),
            "oldest_queue_seconds": oldest,
            "worker_age_seconds": worker_age,
            "storage_fraction": storage,
            "unknown_cost_attempts": uncertain,
            "failed_runs": failed,
            "failure_reasons": dict(failures),
            "stop_reasons": dict(reasons),
            "cap_stops": {r: n for r, n in reasons.items() if r.endswith("_limit")},
            "recent_provider_auth_failures": auth_failures,
            "invalidated_exports": invalidated_exports,
            "correction_rounds": s.scalar(select(func.coalesce(func.sum(Run.rounds), 0))),
            "alerts": alerts,
            "ingestion_errors": errors,
        }


def clear_checkpoints(s, run_ids):
    # Saver table names/keys are explicit; never interpolate user-provided SQL identifiers.
    existing = set(inspect(s.connection()).get_table_names())
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
        if table in existing:
            for ident in run_ids:
                s.execute(text(f"DELETE FROM {table} WHERE thread_id=:id"), {"id": ident})


def purge_book(s, ident):
    question_ids = list(s.scalars(select(Question.id).where(Question.workbook_id == ident)))
    run_ids = list(s.scalars(select(Run.id).where(Run.question_id.in_(question_ids))))
    draft_ids = list(s.scalars(select(Draft.id).where(Draft.question_id.in_(question_ids))))
    s.execute(delete(Job).where(Job.run_id.in_(run_ids)))
    s.execute(delete(Stage).where(Stage.run_id.in_(run_ids)))
    clear_checkpoints(s, run_ids)
    s.execute(delete(Run).where(Run.id.in_(run_ids)))
    s.execute(delete(Approval).where(Approval.draft_id.in_(draft_ids)))
    s.execute(delete(Draft).where(Draft.question_id.in_(question_ids)))
    s.execute(delete(QuestionVersion).where(QuestionVersion.question_id.in_(question_ids)))
    s.execute(delete(Question).where(Question.id.in_(question_ids)))
    export_ids = list(s.scalars(select(Export.id).where(Export.workbook_id == ident)))
    s.execute(delete(Export).where(Export.workbook_id == ident))
    s.execute(delete(Workbook).where(Workbook.id == ident))
    s.execute(
        delete(Event).where(Event.target.in_([ident, *question_ids, *run_ids, *draft_ids, *export_ids]))
    )


def delete_source(db, objects, ident, user_id):
    from .db import User

    with db.transaction() as s:
        meta = policy.epoch(s, lock=True)
        src, user = s.get(Source, ident), s.get(User, user_id)
        policy.require(src is not None)
        policy.curate_source(user, src.account, src.disclosure, src.audience)
        src.active = False
        meta.corpus += 1
        chunk_ids = set(s.scalars(select(Chunk.id).where(Chunk.source_id == ident)))
        affected = set()
        for draft in s.scalars(select(Draft)):
            if chunk_ids & set(draft.evidence):
                affected.add(s.get(Question, draft.question_id).workbook_id)
        for run in s.scalars(select(Run)):
            if chunk_ids & set(run.record.get("seen_evidence", [])):
                affected.add(s.get(Question, run.question_id).workbook_id)
        # Remove every derived record that could retain the deleted source's content.
        for book in affected:
            purge_book(s, book)
        s.execute(delete(Chunk).where(Chunk.source_id == ident))
        s.execute(delete(Source).where(Source.id == ident))
        s.execute(delete(Event).where(Event.target == ident))
        s.execute(delete(RequestKey))  # Old idempotent replies must not reference purged content.
        s.add(
            Event(
                actor=user.id,
                action="source_deleted",
                target=ident,
                details={"tombstone": True, "removed_workbooks": len(affected)},
            )
        )
        collect_objects(s, objects)
    return {"removed_workbooks": len(affected)}


def collect_objects(s, objects):
    s.flush()
    retained = (
        set(s.scalars(select(Source.object_hash)))
        | set(s.scalars(select(Workbook.object_hash)))
        | set(s.scalars(select(Export.object_hash)))
    )
    for path in objects.root.iterdir():
        if len(path.name) == 64 and path.name not in retained and path.is_file():
            path.unlink()


def retention(db, objects, *, days=90, apply=False):
    policy.require(days >= 1, "invalid_retention", 422)
    with db.transaction() as s:
        meta = policy.epoch(s, lock=apply)
        cutoff = db_time(s) - days * 86400
        books = list(s.scalars(select(Workbook.id).where(Workbook.created < cutoff)))
        sources = list(s.scalars(select(Source.id).where(Source.created < cutoff)))
        result = {"expired_workbooks": books, "expired_sources": sources, "applied": apply}
        if not apply:
            return result
        meta.corpus += 1
        expired_chunks = set(s.scalars(select(Chunk.id).where(Chunk.source_id.in_(sources))))
        for run in s.scalars(select(Run)):
            if expired_chunks & set(run.record.get("seen_evidence", [])):
                books.append(s.get(Question, run.question_id).workbook_id)
        for draft in s.scalars(select(Draft)):
            if expired_chunks & set(draft.evidence):
                books.append(s.get(Question, draft.question_id).workbook_id)
        for ident in set(books):
            purge_book(s, ident)
        s.execute(delete(Chunk).where(Chunk.source_id.in_(sources)))
        s.execute(delete(Source).where(Source.id.in_(sources)))
        s.execute(delete(Event).where(Event.created < cutoff))
        s.execute(delete(RequestKey))
        s.execute(delete(Login).where(Login.expires < db_time(s)))
        s.add(
            Event(
                actor="operator",
                action="retention_applied",
                target="retention",
                details={"tombstone": True, "sources": len(sources), "workbooks": len(set(books))},
            )
        )
        collect_objects(s, objects)
        return result


def pg_command(url, program, *args, input=None):
    url = make_url(str(url)) if isinstance(url, str) else url
    executable = shutil.which(program)
    if not executable:
        candidate = Path("/opt/homebrew/opt/postgresql@17/bin") / program
        executable = str(candidate) if candidate.exists() else program
    env = {
        **os.environ,
        "PGDATABASE": url.database,
        "PGUSER": url.username or os.environ.get("USER", ""),
        "PGHOST": url.query.get("host", url.host or "localhost"),
        "PGPORT": str(url.port or url.query.get("port", 5432)),
        "PGPASSWORD": url.password or "",
    }
    if "options" in url.query:
        env["PGOPTIONS"] = url.query["options"]
    proc = subprocess.run([executable, *args], env=env, input=input, capture_output=True, timeout=120)
    policy.require(proc.returncode == 0, program + "_failed", 503)
    return proc.stdout


def encryption_key(path):
    from cryptography.fernet import Fernet

    path = Path(path)
    policy.require(path.exists() and path.stat().st_mode & 0o077 == 0, "private_backup_key_required", 422)
    return Fernet(path.read_bytes().strip())


def backup(db, objects, destination, key_path):
    """DB-exported MVCC snapshot + immutable objects, serialized with deletion/activation."""
    policy.require(db.engine.dialect.name == "postgresql", "postgres_required", 422)
    cipher = encryption_key(key_path)
    with db.transaction() as s:
        policy.epoch(s, lock=True)
        snapshot = s.scalar(text("SELECT pg_export_snapshot()"))
        dump = pg_command(db.engine.url, "pg_dump", "-Fc", "--no-owner", "--snapshot=" + snapshot)
        hashes = (
            set(s.scalars(select(Source.object_hash)))
            | set(s.scalars(select(Workbook.object_hash)))
            | set(s.scalars(select(Export.object_hash)))
        )
        manifest = {
            "created": time.time(),
            "objects": sorted(hashes),
            "database_sha256": hashlib.sha256(dump).hexdigest(),
            "migration": s.scalar(text("SELECT version_num FROM alembic_version")),
            "lock_hash": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
        }
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            contents = {"database.dump": dump, "manifest.json": json.dumps(manifest).encode()}
            contents.update({"objects/" + h: objects.get(h) for h in hashes})
            policy.require(sum(map(len, contents.values())) <= 250 * 1024**2, "pilot_backup_size_limit", 413)
            for name, content in contents.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(content), 0o600
                tar.addfile(info, io.BytesIO(content))
        sealed = cipher.encrypt(archive.getvalue())
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with destination.open("xb") as f:
        f.write(sealed)
    destination.chmod(0o600)
    return {"path": str(destination), "objects": len(hashes), "sha256": hashlib.sha256(sealed).hexdigest()}


def restore(destination_db, objects, archive_path, key_path):
    policy.require(
        not inspect(destination_db.engine).get_table_names(), "restore_requires_empty_database", 409
    )
    policy.require(not list(objects.root.iterdir()), "restore_requires_empty_objects", 409)
    plain = encryption_key(key_path).decrypt(Path(archive_path).read_bytes())
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
        policy.require(sum(m.size for m in tar.getmembers()) <= 250 * 1024**2, "backup_too_large", 413)
        manifest = json.load(tar.extractfile("manifest.json"))
        expected = {"manifest.json", "database.dump"} | {"objects/" + h for h in manifest["objects"]}
        policy.require(
            {m.name for m in tar.getmembers()} == expected and all(m.isfile() for m in tar.getmembers()),
            "invalid_backup_members",
            422,
        )
        dump = tar.extractfile("database.dump").read()
        policy.require(
            hashlib.sha256(dump).hexdigest() == manifest["database_sha256"], "backup_integrity_failed", 422
        )
        for h in manifest["objects"]:
            content = tar.extractfile("objects/" + h).read()
            policy.require(hashlib.sha256(content).hexdigest() == h, "backup_integrity_failed", 422)
            objects.put(content)
        pg_command(
            destination_db.engine.url,
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--dbname=" + destination_db.engine.url.database,
            input=dump,
        )
    with destination_db.transaction() as s:
        # Explicitly fence uncertain deliveries. Resume only after operator reconciliation.
        for job in s.scalars(select(Job).where(Job.status.in_(["queued", "running"]))):
            job.cancel, job.status, job.lease = True, "cancelled", 0
            run = s.get(Run, job.run_id)
            run.status, run.stop_reason, run.active_started = (
                "cancelled",
                "restored_requires_reconciliation",
                None,
            )
        pending = s.scalar(select(func.count()).select_from(Approval))
        s.execute(delete(Login))
    return {
        "objects_verified": len(manifest["objects"]),
        "approval_records": pending,
        "migration": manifest["migration"],
    }


def prune_backups(directory):
    """Keep seven newest daily snapshots and one older snapshot from each latest month."""
    paths = sorted(Path(directory).glob("assuredesk-*.fernet"), key=lambda p: p.stat().st_mtime, reverse=True)
    keep = set(paths[:7])
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    older = [
        p
        for p in paths
        if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m") < this_month
    ]
    if older:
        keep.add(older[0])
    for p in paths:
        if p not in keep:
            p.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "retention", "backup", "restore", "keygen", "daily"])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive")
    parser.add_argument("--key", default="data/backup.key")
    parser.add_argument("--off-host", help="Existing SSH destination host:/private/backup/directory")
    args = parser.parse_args()
    settings = Settings.env()
    db, objects = Database(settings.database_url), Objects(settings.object_root)
    if args.command == "keygen":
        from cryptography.fernet import Fernet

        with open(os.open(args.key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
            f.write(Fernet.generate_key())
        print("Private key created. Store a separate recovery copy; never upload it with the archive.")
        return
    if args.command == "status":
        result = status(db, objects)
    elif args.command == "retention":
        result = retention(db, objects, apply=args.apply)
    elif args.command == "daily":
        archive = (
            Path(settings.object_root).parent
            / "backups"
            / ("assuredesk-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".fernet")
        )
        result = backup(db, objects, archive, args.key)
        if args.off_host:
            policy.require(
                not args.off_host.startswith("-") and ":/" in args.off_host, "invalid_backup_destination", 422
            )
            subprocess.run(["scp", "-q", "--", str(archive), args.off_host], check=True, timeout=120)
            result["off_host_copied"] = True
        result["retention"] = retention(db, objects, apply=True)
        prune_backups(archive.parent)
    else:
        policy.require(args.archive, "archive_required", 422)
        if args.command == "restore":
            result = restore(db, objects, args.archive, args.key)
        else:
            result = backup(db, objects, args.archive, args.key)
            if args.off_host:
                policy.require(
                    not args.off_host.startswith("-") and ":/" in args.off_host,
                    "invalid_backup_destination",
                    422,
                )
                subprocess.run(["scp", "-q", "--", args.archive, args.off_host], check=True, timeout=120)
                result["off_host_copied"] = True
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
