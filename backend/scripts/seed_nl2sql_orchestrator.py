"""Seeds `nl2sql_orchestrator` — the single entry point for every
structured-data (NL2SQL) domain on this platform, and attaches the
CURRENTLY onboarded domain specialists (`credit_facility_analyst`,
`revenue_returns_analyst`) to it as sub-agents.

This is a pure router, same shape as `market_intelligence_orchestrator`
(scripts/seed_market_agents.py) — zero tools of its own, `base_instruction`
lists each specialist and when to transfer to it. No new ADK/transfer
mechanism is needed for specialists to invoke EACH OTHER: Google ADK's
`transfer_to_agent` already allows any agent to transfer to its own
children, its parent, AND its parent's other children (siblings) by
default (`disallow_transfer_to_peers` defaults False, and
`app/agent_runtime/builder.py` never sets it) — the only thing this script
adds on top of that built-in mechanism is explicit routing/collaboration
sentences on the orchestrator AND on each specialist's own instruction, so
the model reliably uses that path instead of only relying on ADK's
auto-generated transfer-target list. This mirrors the existing convention
in `seed_reporting_specialist.py`.

Designed to scale past two specialists: `SPECIALISTS` below is the single
source of truth for both the orchestrator's routing bullets and which
agents get attached — onboarding a third domain (see
`backend/app/domains/<name>/` for the pattern any domain already follows)
means adding one entry here and re-running this script, nothing else.

Idempotent: `--reset` detaches the specialists, strips the appended
collaboration clauses back out of their instructions, republishes them,
and deletes `nl2sql_orchestrator` itself (mirrors
`seed_reporting_specialist.py`'s reset pattern).

Usage (from backend/, so `app.*` imports resolve):
    python scripts/seed_nl2sql_orchestrator.py [--reset]
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.agent_runtime.cache import agent_cache  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.logs import ConfigAuditLog, InvocationLog, ToolCallLog  # noqa: E402
from app.models.skills import Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

SEED_MARKER = "nl2sql-orchestrator-import"
MODEL_CONFIG = {"model": "gemini-2.5-flash", "temperature": 0.1}

AGENT_NAME = "nl2sql_orchestrator"
AGENT_DESCRIPTION = (
    "Single entry point for every structured-data (NL2SQL) domain on this platform — "
    "routes to the right domain specialist and combines their answers for cross-domain "
    "questions. Currently onboarded: credit facility, revenue & returns."
)

# Single source of truth: one entry per onboarded domain specialist. Adding
# a new domain later = add one entry here (+ re-run this script) — nothing
# else about the orchestrator's instruction needs hand-editing.
#   name              -> the published agent's exact name
#   directory_line     -> the orchestrator's routing bullet for it
#   peer_clause         -> appended to THIS specialist's own base_instruction,
#                          naming every OTHER specialist it can hand off to
SPECIALISTS = {
    "credit_facility_analyst": {
        "directory_line": (
            "- credit_facility_analyst: companies' credit facility usage — limits, utilization, "
            "outstanding balances, overdue amounts. Access is scoped by the logged-in user's "
            "persona (GCM/GSG/Non-GSG/CCB); the specialist handles that itself."
        ),
    },
    "revenue_returns_analyst": {
        "directory_line": (
            "- revenue_returns_analyst: product revenue, returns, and refunds — gross/net revenue, "
            "return rates, units sold/returned, by business unit/category/product/region."
        ),
    },
}


def _orchestrator_instruction() -> str:
    directory = "\n".join(spec["directory_line"] for spec in SPECIALISTS.values())
    return f"""You are the NL2SQL orchestrator — the single entry point for every
structured-data domain on this platform. You never answer a data question yourself;
you always transfer to the right domain specialist. Each specialist writes its own
real SQL against its own tables and enforces its own access rules — you don't need
to know any of that, only which specialist owns which topic.

Specialists currently onboarded:
{directory}

Routing rules:
1. Identify which specialist's domain the question belongs to and transfer to
   exactly that one. If the domain is unambiguous, transfer immediately — don't
   ask the user to pick.
2. If a question spans more than one specialist's domain (e.g. "show me both the
   credit facility exposure and the revenue for a company" or "compare this
   product's returns to that company's overdue balance"), transfer to the first
   relevant specialist for its part. Each specialist is instructed to transfer
   BACK to you (rather than guess or decline) once it notices the question needs
   data outside its own domain — when that happens, you'll see its partial answer
   in the conversation already; transfer to the second relevant specialist for the
   remaining part, then present ONE combined final answer that clearly attributes
   each figure to its source domain rather than just concatenating two separate
   replies or dropping the part you already have.
3. If the request doesn't clearly belong to any onboarded specialist's domain, say
   so plainly and list what you can currently help with — don't guess or transfer
   to a specialist that isn't a good fit.
4. Never fabricate figures yourself; you have no data tools of your own by design,
   only transfer targets.

When a new domain is onboarded, it gets a new bullet in this list and a new
sub-agent attachment — nothing else about this instruction changes."""


# Wraps the appended clause so `_strip_peer_clause` can find and remove it
# by MARKER rather than by exact text match — the clause's wording has
# already changed once during live testing (see git history / this
# session), and matching on literal text meant `reset()` silently failed to
# remove the old wording and a second, different clause got appended on
# top of it instead of replacing it. Markers make wording changes safe.
_PEER_CLAUSE_START = "\n\n<!-- nl2sql-peer-clause:start -->"
_PEER_CLAUSE_END = "<!-- nl2sql-peer-clause:end -->"


def _peer_clause(this_specialist: str) -> str:
    """Deliberately points every specialist back at the ORCHESTRATOR
    (its parent), never sideways at a named peer directly — each specialist
    only ever needs to know ONE fact ("go back to nl2sql_orchestrator for
    anything outside my domain"), not the full roster of every other
    onboarded domain. This is what keeps SPECIALISTS the single place a new
    domain gets added: a new specialist's own instruction never has to be
    rewritten when a further domain shows up later, only this same generic
    clause. (An earlier version had each specialist name every peer
    directly and transfer sideways — verified live to be less reliable:
    the model would often just decline the out-of-domain part instead of
    invoking transfer_to_agent a second time. Routing back through the
    orchestrator, which explicitly expects and handles this handoff in its
    own instruction above, tests more reliably.)

    Explicitly forbids narrating the handoff ("I will now transfer...") —
    verified live: `_resolve_response_text` concatenates every agent's text
    output across a multi-hop turn (the same reason AgentEventLog has a
    dedicated `model_text` event type, see app/models/logs.py), so a
    specialist thinking out loud about transferring leaks that narration
    (plus a duplicate of its own answer) into what the user sees as one
    reply. Silent transfer avoids it without touching that shared code path."""
    if len(SPECIALISTS) < 2:
        return ""
    body = (
        "If the user's question ALSO needs data outside your own domain, do not decline "
        "or guess and do not narrate what you're about to do — first answer the part you "
        "can, then silently call transfer_to_agent to transfer back to nl2sql_orchestrator "
        "(your parent) with a brief note on what still needs answering, so it can route the "
        "rest to the right specialist. Never silently drop the out-of-domain part, and never "
        "tell the user you're transferring — just do it."
    )
    return f"{_PEER_CLAUSE_START}\n{body}\n{_PEER_CLAUSE_END}"


def _strip_peer_clause(instruction: str) -> str:
    return re.sub(
        re.escape(_PEER_CLAUSE_START) + r".*?" + re.escape(_PEER_CLAUSE_END),
        "",
        instruction,
        flags=re.DOTALL,
    )


async def _get_agent(session, name: str) -> Agent | None:
    return await session.scalar(select(Agent).where(Agent.name == name))


async def _full_snapshot(session, agent: Agent) -> dict:
    tools = (
        await session.execute(
            select(Tool).join(AgentTool, AgentTool.tool_id == Tool.id).where(AgentTool.agent_id == agent.id)
        )
    ).scalars().all()
    skill_rows = (
        await session.execute(
            select(Skill, AgentSkill.attach_order)
            .join(AgentSkill, AgentSkill.skill_id == Skill.id)
            .where(AgentSkill.agent_id == agent.id)
            .order_by(AgentSkill.attach_order)
        )
    ).all()
    sub_ids = (
        await session.execute(select(AgentSubagent.child_agent_id).where(AgentSubagent.parent_agent_id == agent.id))
    ).scalars().all()
    sub_agents = [a for a in [await session.get(Agent, cid) for cid in sub_ids] if a is not None]
    return {
        "name": agent.name,
        "description": agent.description,
        "base_instruction": agent.base_instruction,
        "model_config": agent.model_config_json,
        "output_schema": agent.output_schema,
        "output_key": agent.output_key,
        "tools": [{"id": str(t.id), "name": t.name} for t in tools],
        "skills": [{"id": str(s.id), "name": s.name, "attach_order": order} for s, order in skill_rows],
        "sub_agents": [{"id": str(a.id), "name": a.name} for a in sub_agents],
    }


async def _republish(session, agent: Agent) -> None:
    snapshot = await _full_snapshot(session, agent)
    new_version = agent.current_version + 1
    session.add(AgentVersion(agent_id=agent.id, version=new_version, snapshot=snapshot, published_by=SEED_MARKER))
    agent.current_version = new_version
    agent.status = "published"
    await session.flush()
    agent_cache.invalidate(agent.id)


async def reset(session) -> None:
    print("Resetting previously-seeded nl2sql_orchestrator...")
    orchestrator = await _get_agent(session, AGENT_NAME)
    for specialist_name in SPECIALISTS:
        specialist = await _get_agent(session, specialist_name)
        if specialist is None:
            continue
        stripped = _strip_peer_clause(specialist.base_instruction)
        if stripped != specialist.base_instruction:
            specialist.base_instruction = stripped
            await _republish(session, specialist)
            print(f"  Removed peer-collaboration clause from '{specialist_name}'.")
        if orchestrator is not None:
            await session.execute(
                delete(AgentSubagent).where(
                    AgentSubagent.parent_agent_id == orchestrator.id, AgentSubagent.child_agent_id == specialist.id
                )
            )
    if orchestrator is not None:
        invocation_ids = (
            (await session.execute(select(InvocationLog.id).where(InvocationLog.agent_id == orchestrator.id)))
            .scalars().all()
        )
        if invocation_ids:
            await session.execute(delete(ToolCallLog).where(ToolCallLog.invocation_id.in_(invocation_ids)))
            await session.execute(delete(InvocationLog).where(InvocationLog.id.in_(invocation_ids)))
        await session.execute(delete(AgentTool).where(AgentTool.agent_id == orchestrator.id))
        await session.execute(delete(AgentVersion).where(AgentVersion.agent_id == orchestrator.id))
        await session.execute(delete(Agent).where(Agent.id == orchestrator.id))
    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor == SEED_MARKER))
    await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    async with async_session_factory() as session:
        if args.reset:
            await reset(session)

        existing = await _get_agent(session, AGENT_NAME)
        if existing is not None:
            print(f"'{AGENT_NAME}' already seeded. Use --reset to reseed.")
            return

        missing = [name for name in SPECIALISTS if await _get_agent(session, name) is None]
        if missing:
            print(f"Expected these specialists to already be published, but found none: {missing}")
            print("Run their owning domain's seed_agent.py first.")
            return

        orchestrator = Agent(
            name=AGENT_NAME,
            workspace_id=DEFAULT_WORKSPACE_ID,
            description=AGENT_DESCRIPTION,
            base_instruction=_orchestrator_instruction(),
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(orchestrator)
        await session.flush()

        # Attach every specialist BEFORE the orchestrator's own first publish —
        # a snapshot freezes `sub_agents` at publish time (see
        # `_full_snapshot`), so publishing before attaching would ship an
        # orchestrator with zero transfer targets in its own published
        # version (only the always-fresh Playground/draft build would show
        # the attachments; `/chat`, which builds from the published snapshot,
        # would silently have nothing to transfer to).
        for specialist_name in SPECIALISTS:
            specialist = await _get_agent(session, specialist_name)
            session.add(AgentSubagent(parent_agent_id=orchestrator.id, child_agent_id=specialist.id))

            clause = _peer_clause(specialist_name)
            stripped = _strip_peer_clause(specialist.base_instruction)
            if clause and stripped + clause != specialist.base_instruction:
                # Strip-then-append (rather than a not-in check) so a wording
                # change to _peer_clause replaces the old clause instead of
                # stacking a second one alongside it — see _strip_peer_clause.
                specialist.base_instruction = stripped + clause
                await _republish(session, specialist)
                print(f"  Added/updated peer-collaboration clause on '{specialist_name}' (now version {specialist.current_version}).")

            await session.flush()
            print(f"  Attached '{specialist_name}' as a sub-agent of '{AGENT_NAME}'.")

        await _republish(session, orchestrator)
        await write_audit_log(
            session, entity_type="agent", entity_id=orchestrator.id, action="publish", actor=SEED_MARKER,
            diff={"version": orchestrator.current_version}, workspace_id=DEFAULT_WORKSPACE_ID,
        )
        print(f"Created and published '{AGENT_NAME}' (version {orchestrator.current_version}), with {len(SPECIALISTS)} sub-agents.")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
