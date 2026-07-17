import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DataEntity(Base):
    """A reusable data dictionary: what table/collection a domain's data
    lives in, what columns exist, and how each should be treated (labeled,
    searched, filtered, displayed). Not tied to any one tool — a "browse"
    tool and an "exact-lookup" tool on the same underlying table both
    reference the same DataEntity instead of each re-describing its columns.

    `connection` shape:
        {"type": "mysql", "connection_env_prefix": "CREDIT_FACILITY_MYSQL"}
        {"type": "mongo", "connection_env": "...", "database": "..."}

    `source` shape: {"table": "cf_company_master", "primary_key": "company_id"}
    (or `"collection"` instead of `"table"` for Mongo.)

    `fields` shape: list of
        {"name": "company_level", "label": "Level", "type": "string",
         "searchable": false, "filterable": true, "visible": true,
         "measure": false, "format": "text", "enum": ["L2","L3","L4"]}
    — see `app.tool_registry.data_query_tool` for how these drive the
    schema description an LLM writes SQL against, and
    `docs/`-adjacent AccessPolicyForm.tsx for how `format`/`label` are the
    "business rules on how to display data."
    """

    __tablename__ = "data_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    connection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fields: Mapped[list] = mapped_column(JSONB, nullable=False)
    default_sort: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    default_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    max_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
