"""Converts a stored JSON-schema dict into a real Pydantic BaseModel class.

ADK's `output_schema` accepts a raw dict in principle, but its "output_schema
+ tools together" workaround (used whenever an agent has both) only has a
working code path for an actual `type[BaseModel]` — a bare dict hits a bug
where it's used directly as a function-parameter type annotation. Since
StudyBuddy's own agents (quiz_agent, flashcard_agent) use real Pydantic
classes for exactly this combination, building an equivalent class dynamically
from Agent Forge's stored JSON schema is what actually works here, not a
workaround around a limitation of Agent Forge's own design.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, create_model

_JSON_TYPE_MAP: dict[str, Any] = {
    "integer": int,
    "number": float,
    "boolean": bool,
    "string": str,
}


def _resolve_type(schema: dict, name_hint: str) -> Any:
    if "enum" in schema:
        return Literal[tuple(schema["enum"])]  # type: ignore[valid-type]

    json_type = schema.get("type", "string")
    if isinstance(json_type, list):
        json_type = next((t for t in json_type if t != "null"), "string")

    if json_type == "object":
        return _build_model(schema, name_hint)
    if json_type == "array":
        item_schema = schema.get("items", {"type": "string"})
        item_type = _resolve_type(item_schema, f"{name_hint}Item")
        return list[item_type]
    return _JSON_TYPE_MAP.get(json_type, str)


def _build_model(schema: dict, name_hint: str) -> type[BaseModel]:
    properties: dict[str, dict] = schema.get("properties", {})
    required = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        field_type = _resolve_type(prop_schema, f"{name_hint}_{prop_name}".title().replace("_", ""))
        is_nullable = prop_schema.get("nullable", False)
        if is_nullable:
            field_type = Optional[field_type]

        is_required = prop_name in required and not is_nullable
        default = ... if is_required else None
        fields[prop_name] = (
            field_type,
            Field(default=default, description=prop_schema.get("description")),
        )

    return create_model(name_hint or "Model", **fields)  # type: ignore[call-overload]


def build_output_schema_model(schema: dict | None) -> type[BaseModel] | None:
    """Turns a stored JSON-schema dict into a dynamically-built Pydantic model.

    Returns None if no schema is configured, in which case the agent has no
    forced structured output — the common case.
    """
    if not schema:
        return None
    return _build_model(schema, "AgentOutput")
