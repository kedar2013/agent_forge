"""Schema-validated tool I/O — the output half of `Tool.input_schema`
(already enforced implicitly, since that's what ADK builds the function
declaration from). `Tool.output_schema` is optional and off by default
(NULL, a no-op) — an author opts a specific tool into it once they know
its real response shape, so a malformed/misbehaving tool response (a
flaky MCP server, a backend API that changed shape) can't silently corrupt
what the model sees as ground truth.
"""

import jsonschema


def validate_tool_output(response: object, schema: dict) -> str | None:
    """Returns None if `response` matches `schema`, else a short
    human-readable reason. A malformed schema itself (author error, not a
    tool-response problem) is treated as "nothing to validate" — same
    "don't retry-loop on an unfixable error" reasoning as
    scil.validators.validate_json_schema."""
    try:
        jsonschema.validate(response, schema)
    except jsonschema.ValidationError as exc:
        return exc.message
    except jsonschema.SchemaError:
        return None
    return None
