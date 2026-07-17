"""Shared `"{{name}}"` leaf-substitution used by every tool type that binds
LLM-supplied *values* into a structurally-fixed query (never structure) —
`mongo_tool.py`'s `filter_template`/`limit` and `policy_engine.py`'s
`__require_arg` rule filters both use this, so there is exactly one place
that decides what counts as a safe substitution.
"""

from typing import Any

UNSET = object()


def bind_template(template: Any, args: dict[str, Any]) -> Any:
    """Recursively resolves `"{{name}}"` leaves from `args`. A dict entry
    whose value resolves to `UNSET` (the arg was not supplied) is dropped
    from the output — this is what makes an optional filter field a no-op
    rather than a `{"field": null}` match-nothing clause."""
    if isinstance(template, str) and template.startswith("{{") and template.endswith("}}"):
        name = template[2:-2].strip()
        return args.get(name, UNSET)
    if isinstance(template, dict):
        out = {}
        for key, value in template.items():
            bound = bind_template(value, args)
            if bound is not UNSET:
                out[key] = bound
        return out
    if isinstance(template, list):
        return [v for v in (bind_template(item, args) for item in template) if v is not UNSET]
    return template
