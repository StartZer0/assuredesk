"""Application records are authoritative; graph checkpoints only hold references."""

import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    String,
    Text,
    Index,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def uid():
    return str(uuid.uuid4())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Base(DeclarativeBase):
    pass


class Identified:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)


class Meta(Base):
    __tablename__ = "meta"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    policy: Mapped[int] = mapped_column(default=1)
    corpus: Mapped[int] = mapped_column(default=1)


class User(Identified, Base):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    password: Mapped[str] = mapped_column(Text)
    roles: Mapped[list] = mapped_column(JSON, default=list)
    accounts: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(default=True)


class Login(Identified, Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf: Mapped[str] = mapped_column(String(80))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires: Mapped[float] = mapped_column(Float)


class Source(Identified, Base):
    __tablename__ = "sources"
    __table_args__ = (
        Index(
            "uq_source_generation",
            "generation",
            unique=True,
            postgresql_where=text("generation != 'legacy'"),
            sqlite_where=text("generation != 'legacy'"),
        ),
    )
    family: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    product: Mapped[str] = mapped_column(String(80), default="atlas")
    account: Mapped[str] = mapped_column(String(80), default="*")
    roles: Mapped[list] = mapped_column(JSON)
    disclosure: Mapped[str] = mapped_column(String(30))
    audience: Mapped[list] = mapped_column(JSON, default=list)
    valid_from: Mapped[str] = mapped_column(String(10))
    valid_until: Mapped[str] = mapped_column(String(10))
    authority: Mapped[str] = mapped_column(String(40))
    object_hash: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(default=False)
    superseded: Mapped[bool] = mapped_column(default=False)
    provenance: Mapped[list] = mapped_column(JSON, default=list)
    pipeline: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[float] = mapped_column(default=time.time)
    generation: Mapped[str] = mapped_column(String(64), default="legacy")


class Chunk(Identified, Base):
    __tablename__ = "chunks"
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(120))
    start: Mapped[int]
    parent_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(
        Vector(384).with_variant(JSON(none_as_null=True), "sqlite")
    )
    embedding_model: Mapped[str] = mapped_column(String(120), default="")
    metadata_record: Mapped[dict] = mapped_column(JSON, default=dict)


class Workbook(Identified, Base):
    __tablename__ = "workbooks"
    account: Mapped[str] = mapped_column(String(80))
    product: Mapped[str] = mapped_column(String(80), default="atlas")
    as_of: Mapped[str] = mapped_column(String(10))
    object_hash: Mapped[str] = mapped_column(String(64))
    mapping: Mapped[dict] = mapped_column(JSON)
    confirmed: Mapped[bool] = mapped_column(default=False)
    created: Mapped[float] = mapped_column(default=time.time)


class Question(Identified, Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("workbook_id", "row", name="uq_question_row"),)
    workbook_id: Mapped[str] = mapped_column(ForeignKey("workbooks.id"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    row: Mapped[int]
    revision: Mapped[int] = mapped_column(default=1)
    current_draft: Mapped[str | None] = mapped_column(String(36))
    blocked: Mapped[bool] = mapped_column(default=False)


class QuestionVersion(Identified, Base):
    __tablename__ = "question_versions"
    __table_args__ = (UniqueConstraint("question_id", "revision"),)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    revision: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(36))
    created: Mapped[float] = mapped_column(default=time.time)


class Draft(Identified, Base):
    __tablename__ = "drafts"
    __table_args__ = (UniqueConstraint("question_id", "revision", name="uq_draft_revision"),)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    revision: Mapped[int]
    answer: Mapped[str] = mapped_column(String(30))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    supported: Mapped[bool] = mapped_column(default=False)
    policy: Mapped[int]
    corpus: Mapped[int]
    claims: Mapped[list] = mapped_column(JSON, default=list)


class Approval(Identified, Base):
    __tablename__ = "approvals"
    draft_id: Mapped[str] = mapped_column(ForeignKey("drafts.id"), unique=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float]
    support_review: Mapped[dict] = mapped_column(JSON, default=dict)


class Run(Identified, Base):
    __tablename__ = "runs"
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    principal_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    revision: Mapped[int]
    policy: Mapped[int]
    corpus: Mapped[int]
    mode: Mapped[str] = mapped_column(String(30), default="corrective")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    rounds: Mapped[int] = mapped_column(default=0)
    generation_attempts: Mapped[int] = mapped_column(default=0)
    embedding_attempts: Mapped[int] = mapped_column(default=0)
    repair_used: Mapped[bool] = mapped_column(default=False)
    elapsed: Mapped[float] = mapped_column(default=0)
    active_started: Mapped[float | None]
    stop_reason: Mapped[str] = mapped_column(String(50), default="")
    record: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Identified, Base):
    __tablename__ = "jobs"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    delivery: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    owner: Mapped[str] = mapped_column(String(50), default="")
    generation: Mapped[int] = mapped_column(default=0)
    lease: Mapped[float] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    cancel: Mapped[bool] = mapped_column(default=False)
    resume: Mapped[bool] = mapped_column(default=False)
    created: Mapped[float] = mapped_column(default=time.time)


class Attempt(Identified, Base):
    __tablename__ = "attempts"
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    workbook_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    reserved: Mapped[float]
    actual: Mapped[float | None]
    created: Mapped[float] = mapped_column(default=time.time)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Export(Identified, Base):
    __tablename__ = "exports"
    __table_args__ = (UniqueConstraint("workbook_id", "fingerprint", name="uq_export_revision"),)
    workbook_id: Mapped[str] = mapped_column(ForeignKey("workbooks.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    object_hash: Mapped[str] = mapped_column(String(64))


class Event(Identified, Base):
    __tablename__ = "events"
    actor: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(36))
    created: Mapped[float] = mapped_column(default=time.time)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Stage(Base):
    __tablename__ = "stages"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))


class OperationalState(Base):
    __tablename__ = "operational_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    updated: Mapped[float] = mapped_column(default=time.time)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class RequestKey(Base):
    __tablename__ = "request_keys"
    key: Mapped[str] = mapped_column(String(240), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created: Mapped[float] = mapped_column(default=time.time)


def db_time(session):
    """Use the database clock for cross-process lease and retention decisions."""
    if session.bind.dialect.name == "postgresql":
        return float(session.scalar(text("SELECT EXTRACT(EPOCH FROM clock_timestamp())")))
    return time.time()


class Database:
    def __init__(self, url):
        options = {}
        if url == "sqlite://":
            options = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        self.engine = create_engine(url, hide_parameters=True, **options)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self):
        with self.sessions.begin() as session:
            yield session

    def test_schema(self):
        if self.engine.dialect.name != "sqlite":
            raise RuntimeError("Use Alembic migrations for PostgreSQL")
        Base.metadata.create_all(self.engine)
        with self.transaction() as session:
            session.add(Meta(id=1))


class Objects:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def put(self, data):
        h = hashlib.sha256(data).hexdigest()
        path = self.root / h
        try:
            with path.open("xb") as f:
                f.write(data)
            path.chmod(0o600)
        except FileExistsError:
            if path.read_bytes() != data:
                raise RuntimeError("Object integrity error")
        return h

    def get(self, h):
        if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            raise ValueError("Invalid object identifier")
        data = (self.root / h).read_bytes()
        if hashlib.sha256(data).hexdigest() != h:
            raise RuntimeError("Object integrity error")
        return data
