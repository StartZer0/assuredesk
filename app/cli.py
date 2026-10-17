"""Operator entry points. No automatic live model calls on setup."""

import argparse
import getpass
import json
from pathlib import Path
import secrets

from argon2 import PasswordHasher
from sqlalchemy import select

from . import service
from .config import Settings
from .db import Database, Objects, User
from .providers import LocalEmbeddings
from .workbooks import sample_workbook


def seed(db, objects):
    credentials, created_sources = {}, []
    with db.transaction() as s:
        for name, roles, accounts in [
            ("sales", ["sales"], ["acme"]),
            ("reviewer", ["security_reviewer"], ["acme", "nova"]),
            ("admin", ["administrator"], []),
        ]:
            user = s.scalar(select(User).where(User.name == name))
            if not user:
                password = secrets.token_urlsafe(18)
                user = User(
                    name=name, roles=roles, accounts=accounts, password=PasswordHasher().hash(password)
                )
                s.add(user)
                credentials[name] = password
        s.flush()
        reviewer = s.scalar(select(User).where(User.name == "reviewer"))
        from .db import Source

        if not s.scalar(select(Source.id).limit(1)):
            for title, text, disclosure, roles, audience, account in [
                (
                    "Atlas EU hosting",
                    "Atlas production customer data is stored in the EU. "
                    "This document does not establish where backups reside.",
                    "public",
                    ["sales", "security_reviewer"],
                    [],
                    "*",
                ),
                (
                    "Atlas backup policy",
                    "Atlas customer backups are stored exclusively in the EU. "
                    "Backups are retained for 30 days. This policy applies to Acme and Nova deployments.",
                    "customer_approved",
                    ["sales", "security_reviewer"],
                    ["acme", "nova"],
                    "*",
                ),
                (
                    "Atlas encryption",
                    "Atlas encrypts customer data in transit using TLS 1.3. "
                    "Atlas encrypts customer data at rest using AES-256.",
                    "public",
                    ["sales", "security_reviewer"],
                    [],
                    "*",
                ),
                (
                    "Internal investigation",
                    "Synthetic confidential canary: ORCHID-INTERNAL-493. "
                    "Unapproved investigative notes must never enter a customer draft.",
                    "internal_only",
                    ["security_reviewer"],
                    [],
                    "*",
                ),
                (
                    "Nova negotiated exception",
                    "Synthetic customer-isolation canary: NOVA-ONLY-772.",
                    "customer_approved",
                    ["sales", "security_reviewer"],
                    ["nova"],
                    "nova",
                ),
            ]:
                metadata = dict(
                    family=title,
                    title=title,
                    account=account,
                    roles=roles,
                    disclosure=disclosure,
                    audience=audience,
                    valid_from="2026-01-01",
                    valid_until="2027-12-31",
                    authority="approved_policy",
                )
                source = service.add_source(
                    s, reviewer, objects, text.encode(), [{"text": text, "locator": "synthetic:1"}], metadata
                )
                created_sources.append(source.id)
    return credentials, created_sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["seed", "prepare-model", "checkpoints", "create-user", "probe", "check-parser", "inventory"],
    )
    parser.add_argument("--name")
    parser.add_argument("--role", choices=["sales", "security_reviewer", "administrator"])
    args = parser.parse_args()
    settings = Settings.env()
    db = Database(settings.database_url)
    objects = Objects(settings.object_root)
    if args.command == "inventory":
        from importlib.metadata import distributions

        rows = [
            {
                "name": d.metadata["Name"],
                "version": d.version,
                "license": d.metadata.get("License-Expression") or d.metadata.get("License") or "unreported",
                "home": d.metadata.get("Home-page", ""),
            }
            for d in distributions()
        ]
        print(json.dumps(sorted(rows, key=lambda r: r["name"].lower()), indent=2))
    elif args.command == "check-parser":
        from .parsing import parse_source

        result = parse_source(b"# Synthetic test\n\nNo credentials.", ".md")
        print(json.dumps({"parser_ok": len(result) == 2}))
    elif args.command == "prepare-model":
        embeddings = LocalEmbeddings(settings.embedding_cache, download=True)
        print(json.dumps({"model": embeddings.model_id, "dimensions": len(embeddings.query("test"))}))
    elif args.command == "checkpoints":
        from .worker import saver_locked

        with saver_locked(db, "schema-setup") as saver:
            saver.setup()
        print("Checkpoint schema ready.")
    elif args.command == "seed":
        credentials, created_sources = seed(db, objects)
        if created_sources:
            from .worker import index_pending

            index_pending(db, LocalEmbeddings(settings.embedding_cache))
            with db.transaction() as s:
                reviewer = s.scalar(select(User).where(User.name == "reviewer"))
                for ident in created_sources:
                    service.activate_source(s, reviewer, ident)
        output = Path(settings.object_root).parent
        output.mkdir(parents=True, exist_ok=True)
        (output / "sample-questionnaire.xlsx").write_bytes(sample_workbook())
        secret = output / "demo-credentials.json"
        if credentials:
            import os

            fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as file:
                json.dump(credentials, file)
        print("Synthetic sources and workbook ready. Local credentials: data/demo-credentials.json")
    elif args.command == "create-user":
        if not args.name or not args.role:
            parser.error("--name and --role required")
        password = getpass.getpass("Password (minimum 12 characters): ")
        if len(password) < 12:
            parser.error("Password too short")
        with db.transaction() as s:
            s.add(
                User(
                    name=args.name,
                    password=PasswordHasher().hash(password),
                    roles=[args.role],
                    accounts=[] if args.role == "administrator" else ["acme", "nova"],
                )
            )
    else:
        # Read-only account/model availability check, no billable generation.
        from urllib.request import Request, urlopen

        try:
            request = Request(
                "https://api.moonshot.ai/v1/models", headers={"Authorization": "Bearer " + settings.api_key}
            )
            with urlopen(request, timeout=10) as response:
                available = settings.model in {x["id"] for x in json.load(response)["data"]}
            print(json.dumps({"model": settings.model, "available": available}))
        except Exception:
            print(json.dumps({"available": False, "error": "provider_probe_failed"}))
            raise SystemExit(1)


if __name__ == "__main__":
    main()
