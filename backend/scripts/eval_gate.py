"""CI quality gate: runs the SCIL golden-question regression suite
(POST /api/scil/eval/run) and the System Prompt Evaluator (POST
/api/prompt-eval/evaluate) for every published agent that has active golden
cases, and exits non-zero if any agent falls below a configurable threshold
on either. Wired into CI via .github/workflows/eval-gate.yml — a PR that
regresses trajectory accuracy or prompt quality fails the build instead of
merging silently.

Talks to the FastAPI app in-process over ASGI transport — the same harness
tests/conftest.py already uses — against a real Postgres, so no separately
running backend is needed in CI; just DATABASE_URL/GEMINI_API_KEY/
AGENT_FORGE_API_TOKEN in the environment, same as the test suite. This also
means it runs real LLM calls (the agent under test AND the judge), so it
costs real tokens per run — scope it with --agent in a PR workflow if you
don't want to gate on every agent on every push.

Every threshold and the agent scope are configurable, since different
teams/agents warrant different bars — a brand-new agent with a thin golden
set shouldn't be held to the same bar as a mature, heavily-curated one:

    python scripts/eval_gate.py
    python scripts/eval_gate.py --min-pass-rate 0.9 --min-prompt-score 75
    python scripts/eval_gate.py --agent credit_facility_analyst --agent revenue_returns_analyst
    EVAL_GATE_MIN_PASS_RATE=0.9 EVAL_GATE_MIN_PROMPT_SCORE=75 python scripts/eval_gate.py
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models.agents import Agent  # noqa: E402
from app.models.scil import ScilEvalCase  # noqa: E402

DEFAULT_MIN_PASS_RATE = float(os.environ.get("EVAL_GATE_MIN_PASS_RATE", "0.8"))
DEFAULT_MIN_PROMPT_SCORE = float(os.environ.get("EVAL_GATE_MIN_PROMPT_SCORE", "70"))


async def _agents_in_scope(agent_names: list[str] | None) -> list[Agent]:
    async with async_session_factory() as session:
        query = (
            select(Agent)
            .join(ScilEvalCase, ScilEvalCase.agent_id == Agent.id)
            .where(Agent.status == "published", ScilEvalCase.is_active.is_(True))
            .distinct()
        )
        if agent_names:
            query = query.where(Agent.name.in_(agent_names))
        return list((await session.execute(query)).scalars().all())


async def run_gate(agent_names: list[str] | None, min_pass_rate: float, min_prompt_score: float) -> bool:
    settings = get_settings()
    agents = await _agents_in_scope(agent_names)
    if not agents:
        scope_note = f" matching {agent_names}" if agent_names else ""
        print(f"No published agents{scope_note} with active eval cases found — nothing to gate on.")
        return True

    all_ok = True
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://eval-gate",
        headers={"Authorization": f"Bearer {settings.agent_forge_api_token}"},
        timeout=120.0,
    ) as client:
        for agent in agents:
            print(f"\n=== {agent.name} ===")

            regression_resp = await client.post("/api/scil/eval/run", json={"agent_id": str(agent.id)})
            if regression_resp.status_code != 200:
                print(f"  REGRESSION SUITE: request failed ({regression_resp.status_code}): {regression_resp.text}")
                all_ok = False
            else:
                summary = regression_resp.json()
                pass_rate = summary["passed"] / summary["total"] if summary["total"] else 1.0
                ok = pass_rate >= min_pass_rate
                all_ok = all_ok and ok
                print(
                    f"  REGRESSION SUITE: {summary['passed']}/{summary['total']} passed ({pass_rate:.0%}) "
                    f"-- threshold {min_pass_rate:.0%} -- {'PASS' if ok else 'FAIL'}"
                )
                if not ok:
                    for r in summary["results"]:
                        if not r["passed"]:
                            print(f"    - FAILED: {r['question']!r}")
                            print(f"      judge: {r['judge_reasoning']}")

            eval_resp = await client.post(
                "/api/prompt-eval/evaluate", json={"scope": "effective", "agent_id": str(agent.id)}
            )
            if eval_resp.status_code != 200:
                print(f"  PROMPT EVAL: request failed ({eval_resp.status_code}): {eval_resp.text}")
                all_ok = False
                continue
            prompt_result = eval_resp.json()
            score = prompt_result["overall_score"]
            ok = score >= min_prompt_score
            all_ok = all_ok and ok
            print(f"  PROMPT EVAL: {score:.1f}/100 -- threshold {min_prompt_score:.1f} -- {'PASS' if ok else 'FAIL'}")
            if not ok and prompt_result.get("summary"):
                print(f"    judge summary: {prompt_result['summary']}")

    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--agent",
        action="append",
        dest="agents",
        help="Limit the gate to this agent name (repeatable). Default: every published agent with active eval cases.",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=DEFAULT_MIN_PASS_RATE,
        help=f"Minimum golden-set regression pass rate, 0-1 (default {DEFAULT_MIN_PASS_RATE}, or $EVAL_GATE_MIN_PASS_RATE).",
    )
    parser.add_argument(
        "--min-prompt-score",
        type=float,
        default=DEFAULT_MIN_PROMPT_SCORE,
        help=f"Minimum System Prompt Evaluator score, 0-100 (default {DEFAULT_MIN_PROMPT_SCORE}, or $EVAL_GATE_MIN_PROMPT_SCORE).",
    )
    args = parser.parse_args()

    ok = asyncio.run(run_gate(args.agents, args.min_pass_rate, args.min_prompt_score))
    print("\n" + ("ALL GATES PASSED" if ok else "GATE FAILED — see failures above"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
