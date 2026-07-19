"""Deterministic (no LLM call, no I/O) guardrail checks — same "cheap,
always run" constraint as `app.scil.validators`. Toxicity is deliberately
NOT handled here: a lexical slur/profanity list is both incomplete and not
something to hardcode into source; see `app.guardrails.judge.check_toxicity`
for the model-based check instead.

Every `check_*` function returns a `Finding` — `matched=False` (the
`_NO_FINDING` singleton) is the overwhelmingly common case and callers
should treat it as free to check.
"""

import re
from dataclasses import dataclass


@dataclass
class Finding:
    matched: bool
    check_name: str = ""
    reason: str = ""
    matched_preview: str = ""
    # Only set for output checks that support partial redaction (PII/MNPI):
    # the input text with the offending span(s) masked, for callers running
    # in `action="redact"` mode instead of a full block.
    redacted_text: str | None = None


_NO_FINDING = Finding(matched=False)

# --- Input: prompt-injection / jailbreak heuristics -------------------------
# A coarse net on purpose — these are the cheap first line of defense, not
# the whole story. `judge.py`'s LLM-based checks catch what phrasing these
# regexes miss; an agent can enable both.

_INJECTION_PATTERNS = [
    re.compile(r"ignore (all|any|the)?\s*(previous|prior|above)\s+instructions", re.I),
    re.compile(r"disregard (all|any|the)?\s*(previous|prior|above)", re.I),
    re.compile(r"you are no longer\b", re.I),
    re.compile(r"reveal (your|the) (system|hidden) prompt", re.I),
    re.compile(r"(print|show|repeat) (your|the) (system|initial) (prompt|instructions)", re.I),
    re.compile(r"what (is|are) your (system|initial) (prompt|instructions)", re.I),
    re.compile(r"new instructions?\s*:", re.I),
    re.compile(r"act as (if you (were|are)|an?)\s+.*\bwith no (restrictions|rules|filters)", re.I),
]

_JAILBREAK_PATTERNS = [
    re.compile(r"pretend (you|there) (are|is) no (rules|guidelines|restrictions)", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"bypass (your|the) (safety|content) (filter|guidelines|restrictions)", re.I),
    re.compile(r"\bDAN\b.{0,20}\bmode\b", re.I),
    re.compile(r"\bdo anything now\b", re.I),
]


def _first_match(text: str, patterns: list[re.Pattern], check_name: str, label: str) -> Finding:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return Finding(
                matched=True,
                check_name=check_name,
                reason=f"Input matched a {label} heuristic.",
                matched_preview=match.group(0)[:200],
            )
    return _NO_FINDING


def check_prompt_injection(text: str) -> Finding:
    return _first_match(text, _INJECTION_PATTERNS, "prompt_injection", "prompt-injection")


def check_jailbreak(text: str) -> Finding:
    return _first_match(text, _JAILBREAK_PATTERNS, "jailbreak", "jailbreak")


# --- Output: PII ------------------------------------------------------------

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
# 13-19 digits (covers Amex/Visa/MC/Discover/Diners lengths), optionally
# grouped by spaces/dashes — narrowed to actual card numbers via a Luhn
# check below rather than flagging every long digit run, since this
# platform's own domain (credit-facility/revenue data) is numeric-heavy and
# an un-checksummed regex would false-positive constantly on account/invoice
# ids and dollar amounts.
_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def check_pii(text: str) -> Finding:
    match = _SSN_RE.search(text)
    if match:
        return Finding(
            matched=True,
            check_name="pii:ssn",
            reason="Output contains a likely Social Security Number.",
            matched_preview="[redacted, never logged]",
            redacted_text=_SSN_RE.sub("[REDACTED-SSN]", text),
        )

    for candidate in _CARD_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"[ -]", "", candidate.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            return Finding(
                matched=True,
                check_name="pii:credit_card",
                reason="Output contains a likely credit card number (Luhn-valid).",
                matched_preview="[redacted, never logged]",
                redacted_text=text.replace(candidate.group(0), "[REDACTED-CARD]"),
            )

    match = _EMAIL_RE.search(text)
    if match:
        return Finding(
            matched=True,
            check_name="pii:email",
            reason="Output contains an email address.",
            matched_preview="[redacted, never logged]",
            redacted_text=_EMAIL_RE.sub("[REDACTED-EMAIL]", text),
        )

    match = _PHONE_RE.search(text)
    if match:
        return Finding(
            matched=True,
            check_name="pii:phone",
            reason="Output contains a likely phone number.",
            matched_preview="[redacted, never logged]",
            redacted_text=_PHONE_RE.sub("[REDACTED-PHONE]", text),
        )

    return _NO_FINDING


def check_mnpi(text: str, terms: list[str]) -> Finding:
    """`terms` is the merged platform + per-agent confidential-term list
    (see `guardrails.config.get_guardrails_config`) — plain substring
    matching, case-insensitive, deliberately simple since this list is
    operator/author-curated (exact phrases they know are sensitive), not a
    general classification problem."""
    lowered = text.lower()
    for term in terms:
        idx = lowered.find(term.lower())
        if idx != -1:
            pattern = re.compile(re.escape(term), re.I)
            return Finding(
                matched=True,
                check_name="mnpi",
                reason="Output contains a configured confidential/MNPI term.",
                matched_preview="[redacted, never logged]",
                redacted_text=pattern.sub("[REDACTED-CONFIDENTIAL]", text),
            )
    return _NO_FINDING
