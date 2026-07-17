"""SCIL eval framework: two independent correctness signals neither
scil_metrics nor scil_correction_memory provide, since both of those only
ever see traffic that actually happened and only flag what a configured
validator can detect deterministically.

1. Sampled live-traffic groundedness (`sample_groundedness_fire_and_forget`)
   -- reuses the same LLM-judge check the blocking hallucination validator
   uses (app/scil/hallucination.check_groundedness), but out of the request
   path: never retries, never delays the response, just scores a
   configurable fraction of successful turns and logs the verdict. Passive
   monitoring for agents that don't want the cost/latency of blocking
   groundedness checks on every turn.

2. Golden-question regression grading (`judge_regression_case`) -- given a
   curated (question, expected_criteria) pair and what the agent actually
   answered when asked that question just now, judges whether the answer
   satisfies the criteria. Free-text criteria + an LLM judge rather than an
   exact-match string compare, since the same correct fact can be phrased
   many valid ways ("90.54%" vs "about 91%" are both fine; the wrong number
   is not, regardless of phrasing).

Both fail open (never raise) -- a broken judge must never take down a real
request or a regression run; it just produces no signal for that one turn.
"""

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from typing import Any

from app.db import async_session_factory
from app.models.scil import ScilGroundednessSample
from app.observability.rca import cap_payload
from app.scil.hallucination import check_groundedness

logger = logging.getLogger(__name__)


def sample_groundedness_fire_and_forget(
    *,
    agent_id: uuid.UUID,
    request_id: uuid.UUID,
    input_text: str,
    response_text: str,
    tool_calls: list[Any],
    sample_rate: float,
    agent_row: Any,
) -> None:
    """Rolls the sampling dice synchronously (cheap, no I/O) so an agent at
    sample_rate=0 costs nothing beyond the random() call; only schedules the
    actual judge call + DB write for turns that land in the sample."""
    if sample_rate <= 0.0 or random.random() >= sample_rate:
        return
    asyncio.create_task(_score_and_write(agent_id, request_id, input_text, response_text, tool_calls, agent_row))


async def _score_and_write(
    agent_id: uuid.UUID,
    request_id: uuid.UUID,
    input_text: str,
    response_text: str,
    tool_calls: list[Any],
    agent_row: Any,
) -> None:
    try:
        result = await check_groundedness(response_text, tool_calls, agent_row)
        async with async_session_factory() as session:
            session.add(
                ScilGroundednessSample(
                    agent_id=agent_id,
                    request_id=request_id,
                    input_text=input_text,
                    grounded=result.ok,
                    reason=result.error_detail,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("SCIL eval: groundedness sampling failed")


@dataclass
class RegressionVerdict:
    passed: bool
    reasoning: str


_REGRESSION_JUDGE_PROMPT = """You are grading one answer from an AI agent's regression test suite.

Question asked:
{question}

What a correct answer MUST contain:
{expected_criteria}

The agent's actual answer:
{actual_response}

Does the actual answer satisfy the required criteria? Minor differences in phrasing, formatting, \
or the inclusion of extra (correct) detail are fine -- only fail it if a required fact is missing, \
wrong, or contradicted. Reply with exactly one line: "PASS" if it satisfies the criteria, or \
"FAIL: <brief reason>" if it does not."""


async def judge_regression_case(question: str, expected_criteria: str, actual_response: str, model: str) -> RegressionVerdict:
    """Fails open as FAIL-with-reason (not PASS) on a judge error -- unlike
    the live groundedness/hallucination checks, a broken judge here should
    surface as a visibly failed regression case for someone to investigate,
    not silently report a clean test suite."""
    try:
        from google import genai

        prompt = _REGRESSION_JUDGE_PROMPT.format(
            question=question, expected_criteria=expected_criteria, actual_response=cap_payload(actual_response)
        )
        client = genai.Client()
        result = await client.aio.models.generate_content(model=model, contents=prompt)
        verdict = (result.text or "").strip()
    except Exception as exc:  # noqa: BLE001 — the failure IS the finding
        logger.exception("SCIL eval: regression judge call failed")
        return RegressionVerdict(passed=False, reasoning=f"Judge call failed: {exc}")

    if verdict.upper().startswith("PASS"):
        return RegressionVerdict(passed=True, reasoning=verdict)
    reasoning = verdict.split(":", 1)[1].strip() if ":" in verdict else verdict or "Judge marked this FAIL with no reason given."
    return RegressionVerdict(passed=False, reasoning=reasoning)