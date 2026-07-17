import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TOOL_TYPES = (
    "http_tool",
    "sql_tool",
    "mcp_tool",
    "retrieval_tool",
    "image_gen_tool",
    "db_schema_tool",
    "nl2sql_query_tool",
    "mongo_query_tool",
    "mysql_query_tool",
    "data_query_tool",
    # Self-healing execution loop (error reflection): catches a SQL
    # execution/validation error and feeds the raw error text back to the
    # model as the tool's own result, capped at a configurable retry count
    # — see app/tool_registry/self_healing_sql_tool.py.
    "self_healing_sql_tool",
    # Query decomposition: a stateless read of the scratchpad slots
    # self_healing_sql_tool writes to when called with `scratchpad_slot` —
    # see app/tool_registry/read_scratchpad_tool.py.
    "read_scratchpad_tool",
)


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = (CheckConstraint(f"tool_type IN {TOOL_TYPES}", name="tools_tool_type_check"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    tool_type: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
