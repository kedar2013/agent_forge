import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator


class PromptEvalCriterionInfo(BaseModel):
    id: str
    label: str
    category: str
    method: Literal["deterministic", "judged"]
    weight: int
    description: str


class PromptEvalRequest(BaseModel):
    agent_id: uuid.UUID | None = None
    prompt_text: str | None = None
    # "effective" (base_instruction + attached skills, composed exactly as
    # the runtime sends it) is the more useful default for an agent-scoped
    # evaluation — it's what the model actually receives. Ignored (always
    # treated as "static") when evaluating raw pasted text, since there are
    # no skills to compose against.
    scope: Literal["static", "effective"] = "effective"
    model: str | None = None

    @model_validator(mode="after")
    def _require_exactly_one_input(self) -> "PromptEvalRequest":
        has_agent = self.agent_id is not None
        has_text = bool(self.prompt_text and self.prompt_text.strip())
        if not has_agent and not has_text:
            raise ValueError("Provide either agent_id or prompt_text.")
        if has_agent and has_text:
            raise ValueError("Provide only one of agent_id or prompt_text, not both.")
        return self


class CriterionResultOut(BaseModel):
    id: str
    label: str
    category: str
    method: Literal["deterministic", "judged"]
    weight: int
    score: int | None
    max_score: int
    applicable: bool
    severity: Literal["info", "warning", "critical"]
    rationale: str
    suggestion: str | None = None


class PromptEvalResult(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None
    scope: str
    source_text: str
    overall_score: float
    criteria: list[CriterionResultOut]
    summary: str | None
    suggested_rewrite: str | None
    model_used: str | None
    judge_error: str | None
    created_at: datetime


class PromptEvalRunSummary(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None
    scope: str
    overall_score: float
    summary: str | None
    model_used: str | None
    judge_error: str | None
    created_by: str | None
    created_at: datetime
