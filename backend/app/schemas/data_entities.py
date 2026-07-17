import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DataEntityCreate(BaseModel):
    name: str
    description: str | None = None
    connection: dict
    source: dict
    fields: list[dict]
    default_sort: dict | None = None
    default_limit: int = 20
    max_limit: int = 100
    workspace_id: uuid.UUID | None = None


class DataEntityUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    connection: dict | None = None
    source: dict | None = None
    fields: list[dict] | None = None
    default_sort: dict | None = None
    default_limit: int | None = None
    max_limit: int | None = None


class DataEntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID | None
    name: str
    description: str | None
    connection: dict
    source: dict
    fields: list[dict]
    default_sort: dict | None
    default_limit: int
    max_limit: int
    created_at: datetime
    updated_at: datetime


class IntrospectRequest(BaseModel):
    connection: dict
    table: str


class IntrospectedField(BaseModel):
    name: str
    type: str


class IntrospectResponse(BaseModel):
    fields: list[IntrospectedField]
    # First PRIMARY KEY column, when the source can report one (MySQL) —
    # lets the onboarding wizard prefill the primary-key box.
    primary_key: str | None = None


class ConnectionInfo(BaseModel):
    """One usable MySQL connection discovered from the backend's env —
    a `{PREFIX}_HOST` with a `{PREFIX}_DATABASE`/`{PREFIX}_NAME` sibling."""

    prefix: str
    database: str
    host: str
    port: int


class TestConnectionRequest(BaseModel):
    connection_env_prefix: str


class TestConnectionResponse(BaseModel):
    ok: bool
    database: str
    table_count: int


class TableInfo(BaseModel):
    name: str
    column_count: int
    row_estimate: int


class ListTablesRequest(BaseModel):
    connection_env_prefix: str


class ListTablesResponse(BaseModel):
    tables: list[TableInfo]
