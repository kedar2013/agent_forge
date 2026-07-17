"""One-off fix: nl2sql_orchestrator and its specialists (credit_facility_
analyst, revenue_returns_analyst) were seeded before
scripts/seed_nl2sql_orchestrator.py switched to the shared, N-way-generic
app.agent_runtime.orchestration_patterns module — their live rows still
carry the old hardcoded "transfer to the first relevant specialist...
transfer to the second relevant specialist" wording (and the old
`<!-- nl2sql-peer-clause:start/end -->`-marked clause on each specialist),
not the new loop-until-covered instruction that scales past two.

Re-running seed_nl2sql_orchestrator.py alone does nothing here — its
main() no-ops once nl2sql_orchestrator already exists, by design (it's a
"create if missing" seed script, not a migration). --reset would work too,
but deletes and recreates the orchestrator's Agent row outright, which
would orphan any ScilEvalCase rows already seeded against its old agent_id
(see scripts/seed_eval_cases.py). This script instead updates the existing
rows in place, republishing each so the live change actually reaches
/chat and /invoke (which build from the published snapshot, not the live
draft — see scripts/migrate_gemini_model.py's docstring for the same
trap).

Usage (from the backend/ directory):
    python scripts/migrate_nl2sql_orchestrator_instructions.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.agent_runtime.cache import agent_cache  # noqa: E402
from app.agent_runtime.orchestration_patterns import build_peer_clause, strip_peer_clause  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.logging_hooks import write_audit_log  # noqa: E402
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.skills import Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.models.workspaces import DEFAULT_WORKSPACE_ID  # noqa: E402

# Import after sys.path is set up, same as every other seed/migration script.
from seed_nl2sql_orchestrator import AGENT_NAME, SPECIALISTS, _orchestrator_instruction  # noqa: E402

ACTOR = "nl2sql-orchestrator-instruction-migration"

# The OLD marker this script's own predecessor (seed_nl2sql_orchestrator.py,
# before it moved to orchestration_patterns) wrapped its peer clause in —
# strip_peer_clause (the current, shared one) looks for a DIFFERENT marker
# now, so it can't find or remove this old text on its own.
_OLD_PEER_CLAUSE_START = "\n\n<!-- nl2sql-peer-clause:start -->"
_OLD_PEER_CLAUSE_END = "<!-- nl2sql-peer-clause:end -->"


def _strip_old_peer_clause(instruction: str) -> str:
    import re

    return re.sub(
        re.escape(_OLD_PEER_CLAUSE_START) + r".*?" + re.escape(_OLD_PEER_CLAUSE_END),
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
    session.add(AgentVersion(agent_id=agent.id, version=new_version, snapshot=snapshot, published_by=ACTOR))
    agent.current_version = new_version
    agent.status = "published"
    await write_audit_log(
        session, entity_type="agent", entity_id=agent.id, action="publish", actor=ACTOR,
        diff={"version": new_version, "reason": "generic N-way router instruction migration"},
        workspace_id=DEFAULT_WORKSPACE_ID,
    )
    await session.flush()
    agent_cache.invalidate(agent.id)


async def main() -> None:
    async with async_session_factory() as session:
        orchestrator = await _get_agent(session, AGENT_NAME)
        if orchestrator is None:
            print(f"'{AGENT_NAME}' isn't seeded yet — nothing to migrate. Run seed_nl2sql_orchestrator.py first.")
            return

        changed = False

        new_instruction = _orchestrator_instruction()
        if orchestrator.base_instruction != new_instruction:
            orchestrator.base_instruction = new_instruction
            await _republish(session, orchestrator)
            changed = True
            print(f"Updated '{AGENT_NAME}' to the generic N-way router instruction (now version {orchestrator.current_version}).")
        else:
            print(f"'{AGENT_NAME}' already has the current instruction.")

        for specialist_name in SPECIALISTS:
            specialist = await _get_agent(session, specialist_name)
            if specialist is None:
                continue
            stripped = strip_peer_clause(_strip_old_peer_clause(specialist.base_instruction))
            new_clause = build_peer_clause() if len(SPECIALISTS) >= 2 else ""
            new_specialist_instruction = stripped + new_clause
            if specialist.base_instruction != new_specialist_instruction:
                specialist.base_instruction = new_specialist_instruction
                await _republish(session, specialist)
                changed = True
                print(f"  Migrated peer-collaboration clause on '{specialist_name}' (now version {specialist.current_version}).")
            else:
                print(f"  '{specialist_name}' already has the current peer clause.")

        if changed:
            await session.commit()
            print("Done.")
        else:
            print("Nothing to do — everything already matches the current instructions.")


if __name__ == "__main__":
    asyncio.run(main())
