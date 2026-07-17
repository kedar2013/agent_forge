import decimal
import uuid
from typing import Any


def to_json_safe(value: Any) -> Any:
    """Recursively convert DB-driver types into JSON-serializable Python values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (decimal.Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    try:
        import json

        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)
