"""Template-based deterministic routing: per-agent regex/slot patterns
(stored in the agent's own model_config.scil.templates — same JSONB config
surface as every other per-agent setting, no separate registry table) that
answer a matching request with ZERO LLM calls.

Template shape:
    {"pattern": "^ping$", "response_text": "pong"}
    {"pattern": "convert (?P<amount>\\d+) (?P<src>[a-z]{3}) to (?P<dst>[a-z]{3})",
     "response_text": "Use the converter at /tools/fx?amount={amount}&from={src}&to={dst}"}

Matching is case-insensitive against the normalized (trimmed, lowercased,
whitespace-collapsed) request and must consume the WHOLE message
(fullmatch) — a template firing on a substring of a longer, more nuanced
request would answer a question the user didn't ask. Named groups become
str.format slots in response_text; a template whose slots can't all be
resolved simply doesn't match (falls through to cache/LLM).
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def match_template(normalized_text: str, templates: list[dict[str, Any]]) -> str | None:
    for template in templates:
        pattern = template.get("pattern")
        response_text = template.get("response_text")
        if not pattern or not isinstance(response_text, str):
            continue
        try:
            match = re.fullmatch(pattern, normalized_text, re.IGNORECASE)
        except re.error:
            logger.warning("SCIL: invalid template pattern %r — skipping", pattern)
            continue
        if match is None:
            continue
        try:
            return response_text.format(**match.groupdict())
        except (KeyError, IndexError):
            # response_text references a slot the pattern doesn't capture —
            # a config mistake; skip rather than serve a broken answer.
            logger.warning("SCIL: template %r references missing slots — skipping", pattern)
            continue
    return None
