"""One-off corrective script from a static audit of agent orchestration
(names/descriptions/instructions), run after the user reported growing
"hallucinations" in routing. Fixes, in order:

1. market_intelligence: rewrites base_instruction to (a) integrate
   slide_reporting_agent into the main specialist list instead of leaving it
   tacked on after the "pick exactly one" rule, and (b) sharpen the
   stock_market_analyst vs. company_research_copilot split (heavy tool
   overlap was making routing between them inconsistent), and (c) mention
   fund_analyst_agent's SIP-projection/sector-scan capabilities, which its
   routing bullet previously omitted.
2. orchestrator (StudyBuddy): removes the fund_analyst_agent and
   weather_agent cross-wiring per user decision -- a school-study persona
   routing finance questions (with investment-advice disclaimers) and
   weather was a scope/tone mismatch. This also incidentally fixes a real
   bug: the instruction told the model to transfer to "fund_research_agent",
   which was never actually attached as a sub_agent -- that transfer would
   have failed outright.
3. fund_analyst_agent: expands its description to mention SIP projection
   and sector-comparison, which it can already do but its description
   didn't say -- orchestrators route off this text, so omitting it risked
   missed/incorrect routing.
4. Archives 3 non-functional test agents that were live, published, and
   directly selectable as real chat targets: dev_test_agent, and two
   pytest-artifact agents (agent_448bcfd9, agent_b888b5cc) whose entire
   instruction is "You are a test agent."

Idempotent: safe to re-run -- each step checks current state first. Follows
the same ancestor-cache-invalidation pattern established in
seed_chart_tool.py (only bumps PUBLISHED ancestors; archived/draft ones are
skipped since bumping them would incorrectly resurrect/republish them).

Usage (from the backend/ directory):
    python scripts/audit_fix_agents.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

ACTOR = "agent-orchestration-audit"

MARKET_INTELLIGENCE_INSTRUCTION = """You are the Market Intelligence orchestrator. You never
answer market-data questions yourself -- you always transfer to the right specialist:

- stock_market_analyst: fast, single-ticker lookups on stocks, ETFs, and indices -- ticker search, live price/quote, trailing-return performance. Pick this for "what's X trading at", "how has X performed", or a quick fundamentals/news check on one ticker.
- company_research_copilot: broad, multi-angle company research that goes beyond price -- overview, financials, analyst sentiment, quarterly earnings/revenue trends, regulatory filings, news, all in one place. Pick this for "tell me about Infosys" or any request combining several of the above into one deep-dive answer, not just a single figure.
- crypto_analyst: cryptocurrencies (prices, trends, what's trending).
- forex_metals_analyst: currency exchange rates/conversion, gold/silver/platinum/palladium prices.
- fund_analyst_agent: Indian mutual funds -- finding scheme codes, analyzing performance and risk, comparing multiple funds, sector-level performance comparisons, and SIP (systematic investment plan) growth projections.
- slide_reporting_agent: turns a sales/orders/revenue question into a chart + downloadable PowerPoint deck -- pick this over a plain data answer when the user asks to "show me a slide/deck/presentation of X", "chart/visualize X", or "summarize sales/orders/revenue by X".

Pick exactly one specialist per message and transfer to it. Once transferred,
that specialist stays in charge of the conversation and cannot hand off to a
different specialist itself -- so if a request spans more than one domain
(e.g. "compare gold to Bitcoin this year"), transfer to whichever specialist
matches the first asset mentioned; it will answer what it can and let the
user know, in plain language, that the rest needs a separate follow-up
question. If the request is ambiguous, ask a brief clarifying question
yourself instead of transferring. Never mention internal agent or tool names
in anything you say to the user."""

STUDYBUDDY_ORCHESTRATOR_INSTRUCTION = """You are StudyBuddy, a friendly learning assistant helping a
school student study from their textbook. You never answer content questions
yourself -- you always transfer to the right specialist sub-agent:

- qa_agent: a direct question about a topic in the book ("what is X", "why
  does Y happen").
- summarizer_agent: "summarize chapter N", "what's this chapter about".
- simplifier_agent: "explain like I'm in grade X", "explain that simpler",
  "I don't get it, explain differently".
- translator_agent: "explain this in Hindi/Marathi/...", "translate that"
  (an explicit one-off translation request, distinct from the student's
  persistent language setting, which the other agents already honor).
- example_agent: "give me N more examples of X", "show me another way to
  think about it".
- quiz_agent: "give me practice questions", "quiz me on chapter N" (a
  structured quiz, not a text explanation).
- flashcard_agent: "make flashcards for chapter N", "give me flashcards for
  this chapter" (structured term/definition pairs, not a text explanation).

Pick exactly one sub-agent per student message and transfer to it. If the
request is ambiguous (e.g. just "chapter 3" with no verb), ask a brief
clarifying question yourself instead of transferring."""

FUND_ANALYST_DESCRIPTION = (
    "Analyzes historical performance, returns, and risk for Indian mutual "
    "fund schemes -- including sector-level comparisons and SIP "
    "(systematic investment plan) growth projections."
)

TEST_AGENT_NAMES_TO_ARCHIVE = ["dev_test_agent", "agent_448bcfd9", "agent_b888b5cc"]


def _publish_snapshot(agent: Agent, tools: list[Tool], sub_agents: list[Agent]) -> dict:
    return {
        "name": agent.name,
        "description": agent.description,
        "base_instruction": agent.base_instruction,
        "model_config": agent.model_config_json,
        "output_schema": agent.output_schema,
        "output_key": agent.output_key,
        "tools": [{"id": str(t.id), "name": t.name} for t in tools],
        "skills": [],
        "sub_agents": [{"id": str(a.id), "name": a.name} for a in sub_agents],
    }


async def _republish(session, agent: Agent) -> None:
    tool_rows = (
        (await session.execute(
            select(Tool).join(AgentTool, AgentTool.tool_id == Tool.id).where(AgentTool.agent_id == agent.id)
        )).scalars().all()
    )
    sub_agent_rows = (
        (await session.execute(
            select(Agent).join(AgentSubagent, AgentSubagent.child_agent_id == Agent.id)
            .where(AgentSubagent.parent_agent_id == agent.id)
        )).scalars().all()
    )

    agent.current_version += 1
    snapshot = _publish_snapshot(agent, tool_rows, sub_agent_rows)
    session.add(
        AgentVersion(agent_id=agent.id, version=agent.current_version, snapshot=snapshot, published_by=ACTOR)
    )
    agent.status = "published"
    await write_audit_log(
        session, entity_type="agent", entity_id=agent.id, action="publish",
        actor=ACTOR, diff={"version": agent.current_version}, workspace_id=DEFAULT_WORKSPACE_ID,
    )


async def _find_ancestor_ids(session, agent_id) -> set:
    ancestors: set = set()
    frontier = [agent_id]
    while frontier:
        result = await session.execute(
            select(AgentSubagent.parent_agent_id).where(AgentSubagent.child_agent_id.in_(frontier))
        )
        next_frontier = []
        for (node,) in result:
            if node not in ancestors:
                ancestors.add(node)
                next_frontier.append(node)
        frontier = next_frontier
    return ancestors


async def _bump_published_ancestors(session, changed_agent_ids: set) -> None:
    ancestor_ids: set = set()
    for agent_id in changed_agent_ids:
        ancestor_ids |= await _find_ancestor_ids(session, agent_id)
    ancestor_ids -= changed_agent_ids

    for ancestor_id in ancestor_ids:
        ancestor = await session.get(Agent, ancestor_id)
        if ancestor is None or ancestor.status != "published":
            continue
        await _republish(session, ancestor)
        print(f"  bumped ancestor '{ancestor.name}' (now version {ancestor.current_version}) to invalidate its cache")


async def main() -> None:
    async with async_session_factory() as session:
        changed_ids: set = set()

        # --- 1. market_intelligence: restructure routing instruction -----
        mi = (await session.execute(select(Agent).where(Agent.name == "market_intelligence_orchestrator"))).scalar_one()
        if mi.base_instruction != MARKET_INTELLIGENCE_INSTRUCTION:
            mi.base_instruction = MARKET_INTELLIGENCE_INSTRUCTION
            await _republish(session, mi)
            changed_ids.add(mi.id)
            print(f"Rewrote market_intelligence instruction (now version {mi.current_version}).")
        else:
            print("market_intelligence instruction already up to date.")

        # --- 2. StudyBuddy orchestrator: drop finance/weather cross-wiring
        sb = (await session.execute(select(Agent).where(Agent.name == "orchestrator"))).scalar_one()
        fund_analyst = (await session.execute(select(Agent).where(Agent.name == "fund_analyst_agent"))).scalar_one()
        weather = (await session.execute(select(Agent).where(Agent.name == "weather_agent"))).scalar_one()

        sb_changed = False
        for child in (fund_analyst, weather):
            link = (
                await session.execute(
                    select(AgentSubagent).where(
                        AgentSubagent.parent_agent_id == sb.id, AgentSubagent.child_agent_id == child.id
                    )
                )
            ).scalar_one_or_none()
            if link is not None:
                await session.execute(
                    delete(AgentSubagent).where(
                        AgentSubagent.parent_agent_id == sb.id, AgentSubagent.child_agent_id == child.id
                    )
                )
                sb_changed = True
                print(f"  detached '{child.name}' from StudyBuddy orchestrator.")

        if sb.base_instruction != STUDYBUDDY_ORCHESTRATOR_INSTRUCTION:
            sb.base_instruction = STUDYBUDDY_ORCHESTRATOR_INSTRUCTION
            sb_changed = True

        if sb_changed:
            await _republish(session, sb)
            changed_ids.add(sb.id)
            print(f"Rewrote StudyBuddy orchestrator instruction (now version {sb.current_version}).")
        else:
            print("StudyBuddy orchestrator already up to date.")

        # --- 3. fund_analyst_agent: expand description --------------------
        if fund_analyst.description != FUND_ANALYST_DESCRIPTION:
            fund_analyst.description = FUND_ANALYST_DESCRIPTION
            await _republish(session, fund_analyst)
            changed_ids.add(fund_analyst.id)
            print(f"Expanded fund_analyst_agent's description (now version {fund_analyst.current_version}).")
        else:
            print("fund_analyst_agent description already up to date.")

        if changed_ids:
            await _bump_published_ancestors(session, changed_ids)

        # --- 4. Archive leftover test agents ------------------------------
        for name in TEST_AGENT_NAMES_TO_ARCHIVE:
            agent = (await session.execute(select(Agent).where(Agent.name == name))).scalar_one_or_none()
            if agent is None:
                continue
            if agent.status == "archived":
                print(f"'{name}' already archived.")
                continue
            agent.status = "archived"
            await write_audit_log(
                session, entity_type="agent", entity_id=agent.id, action="archive",
                actor=ACTOR, diff={"reason": "leftover test agent, publicly reachable"},
                workspace_id=DEFAULT_WORKSPACE_ID,
            )
            print(f"Archived '{name}'.")

        await session.commit()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
