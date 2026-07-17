import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FewShotExample(BaseModel):
    input: str
    output: str


class SkillCreate(BaseModel):
    name: str
    instruction_text: str
    few_shot_examples: list[FewShotExample] | None = None
    tags: list[str] | None = None
    created_by: str | None = None
    workspace_id: uuid.UUID | None = None


class SkillUpdate(BaseModel):
    name: str | None = None
    instruction_text: str | None = None
    few_shot_examples: list[FewShotExample] | None = None
    tags: list[str] | None = None


class AddCollaboratorRequest(BaseModel):
    user_email: str


class CollaboratorEntry(BaseModel):
    user_email: str
    added_by: str | None
    created_at: datetime


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID | None
    name: str
    instruction_text: str
    few_shot_examples: list[FewShotExample] | None
    tags: list[str] | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
