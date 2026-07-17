import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AccessPolicyCreate(BaseModel):
    name: str
    description: str | None = None
    resolver_config: dict
    rules: dict
    workspace_id: uuid.UUID | None = None


class AccessPolicyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    resolver_config: dict | None = None
    rules: dict | None = None


class AccessPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID | None
    name: str
    description: str | None
    resolver_config: dict
    rules: dict
    created_at: datetime
    updated_at: datetime
