from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import service
from app.db import Chunk, Database, Objects, Question, User
from app.workbooks import sample_workbook

MAPPING = dict(id_col=1, question_col=2, answer_col=3, explanation_col=4, first_row=2, last_row=6)


@pytest.fixture
def env(tmp_path):
    db = Database("sqlite://")
    db.test_schema()
    objects = Objects(tmp_path / "objects")
    with db.transaction() as s:
        sales = User(name="sales", password="unused", roles=["sales"], accounts=["acme"])
        reviewer = User(
            name="reviewer", password="unused", roles=["security_reviewer"], accounts=["acme", "nova"]
        )
        admin = User(name="admin", password="unused", roles=["administrator"], accounts=[])
        s.add_all([sales, reviewer, admin])
        s.flush()
        book = service.import_workbook(
            s, sales, objects, sample_workbook(), "acme", date.today().isoformat(), MAPPING
        )
        service.confirm_mapping(s, sales, book.id)
        sources, chunks = {}, {}
        for name, account, disclosure, roles, audience in [
            ("public", "*", "public", ["sales", "security_reviewer"], []),
            ("internal", "*", "internal_only", ["security_reviewer"], []),
            ("nova", "nova", "customer_approved", ["sales", "security_reviewer"], ["nova"]),
            ("acme", "*", "customer_approved", ["sales", "security_reviewer"], ["acme"]),
        ]:
            text = f"{name.upper()}-CANARY: Atlas encrypts all customer data using TLS 1.3."
            src = service.add_source(
                s,
                reviewer,
                objects,
                text.encode(),
                [{"text": text, "locator": "section:1"}],
                dict(
                    family=name,
                    title=name,
                    account=account,
                    disclosure=disclosure,
                    roles=roles,
                    audience=audience,
                    valid_from=(date.today() - timedelta(days=2)).isoformat(),
                    valid_until=(date.today() + timedelta(days=30)).isoformat(),
                    authority="approved_policy",
                ),
            )
            c = s.scalar(select(Chunk).where(Chunk.source_id == src.id))
            c.embedding = [1.0] + [0.0] * 383
            c.embedding_model = "fake"
            s.flush()
            service.activate_source(s, reviewer, src.id)
            sources[name], chunks[name] = src.id, c.id
        s.flush()
        questions = list(
            s.scalars(select(Question).where(Question.workbook_id == book.id).order_by(Question.row))
        )
        result = SimpleNamespace(
            db=db,
            objects=objects,
            sales=sales.id,
            reviewer=reviewer.id,
            admin=admin.id,
            book=book.id,
            q=questions[0].id,
            questions=[q.id for q in questions],
            sources=sources,
            chunks=chunks,
        )
    yield result
    db.engine.dispose()


class Embeddings:
    model_id = "fake"

    def query(self, text):
        return [1.0] + [0.0] * 383


class Generator:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def reserve_cost(self):
        return 0.01

    def invoke(self, kind, payload, schema):
        self.calls.append((kind, payload))
        result = self.responses.pop(0)
        if callable(result):
            result = result(payload)
        return result, 0.001
