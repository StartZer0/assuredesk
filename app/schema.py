from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Answer = Literal["Yes", "No", "Partial", "Not applicable", "Unknown", "Declined"]
ANSWERS = ["Yes", "No", "Partial", "Not applicable", "Unknown", "Declined"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requirement(Strict):
    text: str = Field(min_length=1, max_length=1000)
    coverage: Literal["supported", "missing", "conflict"]
    evidence_ids: list[str] = Field(max_length=12)


class Proposal(Strict):
    status: Literal["needs_evidence", "needs_clarification", "conflict", "draft_proposed", "cannot_answer"]
    requirements: list[Requirement] = Field(min_length=1, max_length=12)
    next_queries: list[str] = Field(max_length=2)
    answer: Answer | None = Field(
        description="Use a response category only for draft_proposed. For every other status emit the JSON literal null, never a response category or the string null."
    )
    explanation: str = Field(max_length=6000)

    @model_validator(mode="after")
    def consistent(self):
        if any(not q.strip() or len(q) > 2000 for q in self.next_queries):
            raise ValueError("Invalid corrective query")
        if self.status == "draft_proposed":
            if self.answer is None or any(
                r.coverage != "supported" or not r.evidence_ids for r in self.requirements
            ):
                raise ValueError("Incomplete draft")
        elif self.answer is not None:
            raise ValueError("Non-draft answer")
        return self


class Support(Strict):
    supported: bool
    missing: list[str] = Field(max_length=12)
    next_queries: list[str] = Field(max_length=2)


class DraftInput(Strict):
    expected_revision: int
    answer: Answer
    explanation: str = Field(min_length=1, max_length=6000)
    evidence: list[str] = Field(max_length=24)
    claims: list[dict] | None = Field(default=None, max_length=12)
