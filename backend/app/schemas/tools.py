import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ToolType = Literal[
    "http_tool", "sql_tool", "mcp_tool", "retrieval_tool", "image_gen_tool",
    "db_schema_tool", "nl2sql_query_tool", "mongo_query_tool", "mysql_query_tool",
    "data_query_tool", "self_healing_sql_tool", "read_scratchpad_tool",
]

ToolAccessScope = Literal["workspace", "restricted"]


class ToolCreate(BaseModel):
    name: str
    tool_type: ToolType
    config: dict
    input_schema: dict
    output_schema: dict | None = None
    access_scope: ToolAccessScope = "workspace"
    description: str | None = None
    created_by: str | None = None
    workspace_id: uuid.UUID | None = None


class ToolUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    access_scope: ToolAccessScope | None = None
    description: str | None = None


class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID | None
    name: str
    tool_type: str
    config: dict
    input_schema: dict
    output_schema: dict | None
    access_scope: str
    current_version: int
    description: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class ToolVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tool_id: uuid.UUID
    version: int
    snapshot: dict
    created_by: str | None
    created_at: datetime


class ToolGrantCreate(BaseModel):
    agent_id: uuid.UUID


class ToolGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tool_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str | None = None
    granted_by: str | None
    created_at: datetime
