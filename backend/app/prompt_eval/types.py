"""Shared result shape both deterministic_checks.py and judge.py produce,
merged by service.py into one rubric report. Kept in its own module (not
rubric.py, which is the static catalog) since both the deterministic and
judged sides need to import it without importing each other.
"""

from dataclasses import dataclass
from typing import Literal

Severity = Literal["info", "warning", "critical"]


@dataclass
class CriterionResult:
    id: str
    # None when `applicable` is False — a criterion that doesn't apply to
    # this particular input (e.g. tool_usage_guidance for a tool-less agent)
    # is excluded from the weighted score entirely, not penalized as if it
    # scored zero.
    score: int | None
    applicable: bool
    severity: Severity
    rationale: str
    suggestion: str | None = None

    @classmethod
    def not_applicable(cls, criterion_id: str, rationale: str) -> "CriterionResult":
        return cls(id=criterion_id, score=None, applicable=False, severity="info", rationale=rationale)
