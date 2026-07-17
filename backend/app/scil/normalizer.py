"""Deterministic request normalization for the semantic cache's exact-match
fast path (input_hash) and as the text that gets embedded for the
similarity fallback.

`entities` stays an empty stub HERE on purpose -- it would only ever widen
cache-hit rates (folding "HDFC bank ltd" and "HDFC Bank Ltd" into the same
cache key), which is a nice-to-have, not correctness-bearing. The
correctness-bearing half of entity canonicalization -- catching a
misspelled entity ("Tesslla") that makes a tool call return zero rows
instead of the data it should have -- is a different mechanism entirely,
scil_entity_memory + app.scil.entities, wired into the retry loop rather
than the cache key. See that module's docstring for why.
"""

import hashlib
import re
from dataclasses import dataclass, field

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class NormalizedRequest:
    raw: str
    normalized_text: str
    entities: list[str] = field(default_factory=list)
    input_hash: str = ""


def normalize(text: str) -> NormalizedRequest:
    normalized_text = _WHITESPACE_RE.sub(" ", text.strip()).lower()
    input_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return NormalizedRequest(raw=text, normalized_text=normalized_text, entities=[], input_hash=input_hash)
