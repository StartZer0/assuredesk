import pytest
from app import evaluation, policy
from app.config import Settings
from app.db import Attempt, Run
from app.workflow import Engine
from conftest import Generator, Embeddings
from test_boundaries import start


def test_candidate_corpus_is_grouped_and_not_human_gold(tmp_path):
    evaluation.build(tmp_path)
    cases, sources = evaluation.validate(tmp_path)
    assert len(cases) == 120 and len(sources) == 48
    assert all(c["label_status"] == "candidate_unreviewed" for c in cases)
    with pytest.raises(policy.Rejected, match="independent_label_review_required"):
        evaluation.freeze(tmp_path, Settings("sqlite://"))


def test_family_leakage_is_rejected(tmp_path):
    evaluation.build(tmp_path)
    cases = evaluation.read_lines(tmp_path / "cases.jsonl")
    cases[0]["split"] = "test"
    evaluation.write_lines(tmp_path / "cases.jsonl", cases)
    with pytest.raises(policy.Rejected, match="family_leakage"):
        evaluation.validate(tmp_path)


def test_campaign_cap_is_shared_across_batches(env):
    a = start(env)
    b = start(env)
    with env.db.transaction() as s:
        s.get(Run, a).record = {"evaluation_campaign": "same", "evaluation_batch": "a"}
        s.get(Run, b).record = {"evaluation_campaign": "same", "evaluation_batch": "b"}
        # Old spend avoids the independent UTC-day cap; campaign still includes it.
        s.add(Attempt(run_id=a, workbook_id="old", kind="generation", reserved=29.999, created=1))
    with pytest.raises(policy.Rejected, match="spend_limit"):
        Engine(env.db, Generator([]), Embeddings()).reserve(b, "generation")


def test_batch_cap_is_shared_across_questions(env):
    a = start(env)
    b = start(env)
    with env.db.transaction() as s:
        s.get(Run, a).record = {"evaluation_campaign": "one", "evaluation_batch": "batch"}
        s.get(Run, b).record = {"evaluation_campaign": "one", "evaluation_batch": "batch"}
        s.add(Attempt(run_id=a, workbook_id="old", kind="generation", reserved=14.999, created=1))
    with pytest.raises(policy.Rejected, match="spend_limit"):
        Engine(env.db, Generator([]), Embeddings()).reserve(b, "generation")
