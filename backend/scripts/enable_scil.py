"""Enable SCIL (semantic cache + exemplar-augmented prompting) on the real
agents where response caching is SAFE, with a TTL matched to how fast each
domain's answers go stale.

    cd backend
    python scripts/enable_scil.py [--disable]

RLS-scoped agents (credit_facility_analyst) use cache_scope="user": each
cached answer is keyed by (agent, USER, question), so one persona's data
is never served to another — a GCM user's Tesla answer stays theirs.

Deliberately NOT enabled on the StudyBuddy family (studybuddy_orchestrator,
qa/quiz/flashcard/summarizer/simplifier agents) — retrieval is scoped by
session state (grade/subject/book), which even the user dimension doesn't
fully carry, and quiz/flashcard generation is *supposed* to vary between
runs.

Idempotent: re-running overwrites each listed agent's `scil` config block
(and only that block). Direct JSONB update, same pattern as the other
scripts/ seeders; no republish needed — SCIL config is read from the
agents row at request time, not from the built ADK tree.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db import async_session_factory  # noqa: E402

# agent name -> scil config. TTLs: market quotes go stale in minutes-hours
# (1h keeps repeat questions within a working session cheap without serving
# yesterday's price); fund/company data is dailyish (24h); translations and
# the static example agent are effectively deterministic (168h = 1 week).
#
# Validator choice, per agent SHAPE (not just "turn everything on" -- see the
# credit_facility_analyst postmortem below):
#   "hallucination" -- safe on any agent with tools attached: fails only when
#       tools_attached and zero tools were called this turn. A no-op (never
#       fails) on a pure-router orchestrator with no tools of its own.
#   "entity_resolution" -- safe on any agent, but only DOES anything for a
#       data_query_tool-shaped tool call ({row_count, columns, data} dict) on
#       a zero-row result with a confident near-miss in scil_entity_memory.
#       Silently a no-op against any other tool's output shape.
#   "sql" -- NOT included anywhere below. It validates the agent's own FINAL
#       RESPONSE TEXT as a raw SQL statement -- only correct for an agent
#       whose literal answer to the user IS a SQL string. Every agent here
#       (including the data_query_tool-based ones) answers in natural-
#       language prose synthesized FROM tool results; the SQL itself is a
#       tool-call argument already validated inside data_query_tool.py.
#       credit_facility_analyst was briefly misconfigured with "sql" and it
#       failed SQL:Syntax on 100% of turns (prose doesn't parse as SQL),
#       burning 3x LLM calls per turn via the retry loop and never caching
#       a single answer -- exactly backwards from the point of SCIL. Don't
#       repeat that: only attach "sql" to an agent whose reply IS bare SQL,
#       and none of the agents below are that shape today.
#   "json_schema" -- NOT included anywhere below either: a no-op unless the
#       agent has a declared output_schema, and none currently do.
#
# eval_sample_rate: fraction of successful turns passively scored by the LLM-
# judge groundedness check (app/scil/eval_runner.py), fire-and-forget, never
# blocking/retrying. Only set on agents that also carry "hallucination" --
# no tool calls to ground against otherwise. 0.2 balances signal against
# extra judge-call cost; tune down for a high-traffic agent, up for a new
# one you want closely watched.
ENABLE = {
    "stock_market_analyst": {"enabled": True, "cache_ttl_hours": 1, "validators": ["hallucination"], "eval_sample_rate": 0.2},
    "crypto_analyst": {"enabled": True, "cache_ttl_hours": 1, "validators": ["hallucination"], "eval_sample_rate": 0.2},
    "forex_metals_analyst": {"enabled": True, "cache_ttl_hours": 1, "validators": ["hallucination"], "eval_sample_rate": 0.2},
    # Pure router, no tools of its own -- hallucination check would be a
    # permanent no-op, left off for clarity rather than padding the config.
    "market_intelligence_orchestrator": {"enabled": True, "cache_ttl_hours": 1},
    "weather_agent": {"enabled": True, "cache_ttl_hours": 1, "validators": ["hallucination"], "eval_sample_rate": 0.2},
    "weather_forecasting_agent": {"enabled": True, "cache_ttl_hours": 1, "validators": ["hallucination"], "eval_sample_rate": 0.2},
    "fund_analyst_agent": {"enabled": True, "cache_ttl_hours": 24, "validators": ["hallucination", "entity_resolution"], "eval_sample_rate": 0.2},
    "fund_research_agent": {"enabled": True, "cache_ttl_hours": 24, "validators": ["hallucination", "entity_resolution"], "eval_sample_rate": 0.2},
    "india_fund_orchestrator": {"enabled": True, "cache_ttl_hours": 24},  # router, no own tools
    "company_research_copilot": {"enabled": True, "cache_ttl_hours": 24, "validators": ["hallucination"], "eval_sample_rate": 0.2},
    "sql_insights_agent": {"enabled": True, "cache_ttl_hours": 24, "validators": ["hallucination", "entity_resolution"], "eval_sample_rate": 0.2},
    "slide_reporting_agent": {"enabled": True, "cache_ttl_hours": 24, "validators": ["hallucination"], "eval_sample_rate": 0.2},
    "reporting_specialist": {"enabled": True, "cache_ttl_hours": 24, "validators": ["hallucination"], "eval_sample_rate": 0.2},
    "translator_agent": {"enabled": True, "cache_ttl_hours": 168},  # no tools -- pure LLM translation
    "example_agent": {"enabled": True, "cache_ttl_hours": 168},
    # RLS domain: answers differ per persona -> per-user cache partition.
    # "entity_resolution" is what actually populates scil_correction_memory
    # for this agent (a misspelled company literal like "Microsft" retried
    # against a known-good name from scil_entity_memory -- see Entity:NoMatch
    # in app/scil/entities.py); "hallucination" catches answering without
    # calling data_query_tool at all. "sql" deliberately NOT here -- see the
    # module docstring above.
    "credit_facility_analyst": {
        "enabled": True,
        "cache_ttl_hours": 24,
        "cache_scope": "user",
        "validators": ["hallucination", "entity_resolution"],
        "eval_sample_rate": 0.2,
    },
    # Second data_query_tool worked example (no RLS -- global cache is safe,
    # every user sees the same data). Newly added: was published but had no
    # SCIL config at all until now.
    "revenue_returns_analyst": {
        "enabled": True,
        "cache_ttl_hours": 24,
        "validators": ["hallucination", "entity_resolution"],
        "eval_sample_rate": 0.2,
    },
    # Onboarding-wizard worked example, same data_query_tool pattern. Newly
    # added: was published but had no SCIL config at all until now.
    "sales_analytics_analyst": {
        "enabled": True,
        "cache_ttl_hours": 24,
        "validators": ["hallucination", "entity_resolution"],
        "eval_sample_rate": 0.2,
    },
    # Router in front of sql_insights_agent -- no tools of its own. Newly
    # added: was published but had no SCIL config at all until now.
    "nl2sql_orchestrator": {"enabled": True, "cache_ttl_hours": 24},
    # Found live in the DB with 2 tools attached and no SCIL config, created
    # today -- looks like an in-progress duplicate of fund_analyst_agent
    # rather than a named part of the documented agent family. Included for
    # consistency since it's published with real tools attached; flag to
    # your team if it turns out to be a scratch/experimental agent instead.
    "mutual fund analyser": {"enabled": True, "cache_ttl_hours": 24, "validators": ["hallucination"], "eval_sample_rate": 0.2},
}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disable", action="store_true", help="Set scil.enabled=false on the same agents")
    args = parser.parse_args()

    async with async_session_factory() as session:
        for name, config in ENABLE.items():
            scil = {**config, "enabled": not args.disable}
            result = await session.execute(
                text(
                    """
                    UPDATE agents
                    SET model_config = jsonb_set(model_config, '{scil}', CAST(:scil AS jsonb), true)
                    WHERE trim(name) = :name AND status != 'archived'
                    """
                ),
                {"scil": json.dumps(scil), "name": name},
            )
            state = "disabled" if args.disable else f"enabled (ttl={config.get('cache_ttl_hours')}h)"
            print(f"{'OK ' if result.rowcount else 'MISS'} {name}: {state if result.rowcount else 'no matching agent'}")
        await session.commit()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
