import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AccessPolicy(Base):
    """A reusable, declarative row-level-security policy.

    Not tied to any one domain: `resolver_config` describes how to look up a
    principal's scope attributes (e.g. persona, a coverage list) from
    wherever that data lives, and `rules` maps each possible value of the
    resolved "discriminator" attribute to either a filter to AND onto every
    query, `{"__deny": true}`, or `{"__require_arg": "<name>"}` for
    exact-reference-only access. See `app.tool_registry.policy_engine` for
    how a `mongo_query_tool` (or any future tool type) consumes this.

    `resolver_config` shape:
        {
          "connection_env": "CREDIT_FACILITY_MONGO_URI",
          "database": "credit_facility",
          "discriminator": "persona",
          "persona_lookup": {"collection": "user_persona", "match_field": "user_id", "project": "persona"},
          "scope_lookups": {
            "coverage": {"collection": "user_company_coverage", "match_field": "user_id", "project": "company_id", "many": true}
          }
        }

    `rules` shape (keyed by the resolved discriminator value). A `"$name"`
    string references the flattened list/value a `scope_lookups["name"]`
    entry resolved to; a `"{{arg}}"` string binds a value straight from the
    LLM's tool call args (only meaningful under `__require_arg`, where that
    arg's presence is itself the authorization check):
        {
          "GCM": {},
          "GSG": {"company_level": {"$in": ["L3", "L4"]}},
          "NON_GSG": {"company_id": {"$in": "$coverage"}},
          "CCB": {"__require_arg": "gfcid", "filter": {"gfcid": "{{gfcid}}"}}
        }
    """

    __tablename__ = "access_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolver_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rules: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
