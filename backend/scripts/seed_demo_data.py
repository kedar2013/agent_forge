"""Seeds ~30 days of realistic synthetic dashboard data.

Idempotent: re-running without --reset just adds today's data on top of
whatever demo rows already exist. --reset deletes everything this script
previously created (identified by created_by/invoked_by/actor == 'demo-seed')
before reseeding.

Usage:
    python scripts/seed_demo_data.py [--reset]
"""

import argparse
import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.models.agents import Agent, AgentSkill, AgentTool  # noqa: E402
from app.models.logs import ConfigAuditLog, InvocationLog, ToolCallLog  # noqa: E402
from app.models.skills import Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402
from app.observability.pricing import estimate_cost_usd  # noqa: E402

SEED_MARKER = "demo-seed"
DAYS = 30
MODEL = "gemini-2.5-flash"

DEMO_TOOLS = [
    {
        "name": "demo_weather_lookup",
        "tool_type": "http_tool",
        "description": "Fetches current weather for a city.",
        "config": {"base_url": "https://api.example.com", "method": "GET", "path_template": "/weather/{city}"},
        "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
        "flaky": False,
    },
    {
        "name": "demo_company_lookup",
        "tool_type": "sql_tool",
        "description": "Looks up company records by industry.",
        "config": {"connection_env": "DATABASE_URL", "query_template": "SELECT 1"},
        "input_schema": {"type": "object", "properties": {"industry": {"type": "string"}}},
        "flaky": False,
    },
    {
        "name": "demo_flaky_search",
        "tool_type": "mcp_tool",
        "description": "An intentionally unreliable external search integration, for the Monitoring demo.",
        "config": {"server_url": "https://mcp.example.com/mcp", "tool_name": "search"},
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "flaky": True,
    },
    {
        "name": "demo_doc_retrieval",
        "tool_type": "retrieval_tool",
        "description": "Retrieves relevant document chunks for a query.",
        "config": {"connection_env": "DATABASE_URL", "table": "public.document_chunks"},
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "flaky": False,
    },
]

DEMO_SKILLS = [
    {"name": "demo_grade_level_simplify", "instruction_text": "Explain answers using simple, grade-8-level language."},
    {"name": "demo_citation_formatting", "instruction_text": "Always cite sources in APA format."},
]

DEMO_AGENTS = [
    {"name": "demo_support_bot", "status": "published", "tools": [0], "skills": [0]},
    {"name": "demo_research_assistant", "status": "published", "tools": [2, 3], "skills": [1]},
    {"name": "demo_data_analyst", "status": "published", "tools": [1], "skills": []},
    {"name": "demo_draft_experiment", "status": "draft", "tools": [0], "skills": [0]},
]


async def reset(session):
    print("Resetting previously-seeded demo data...")
    demo_agent_ids = (
        (await session.execute(select(Agent.id).where(Agent.created_by == SEED_MARKER))).scalars().all()
    )
    if demo_agent_ids:
        invocation_ids = (
            (
                await session.execute(
                    select(InvocationLog.id).where(InvocationLog.agent_id.in_(demo_agent_ids))
                )
            )
            .scalars()
            .all()
        )
        if invocation_ids:
            await session.execute(delete(ToolCallLog).where(ToolCallLog.invocation_id.in_(invocation_ids)))
            await session.execute(delete(InvocationLog).where(InvocationLog.id.in_(invocation_ids)))

    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor == SEED_MARKER))
    await session.execute(delete(Agent).where(Agent.created_by == SEED_MARKER))
    await session.execute(delete(Tool).where(Tool.created_by == SEED_MARKER))
    await session.execute(delete(Skill).where(Skill.created_by == SEED_MARKER))
    await session.commit()


async def ensure_demo_entities(session) -> tuple[list[Tool], list[Skill], list[Agent]]:
    existing_tools = (
        (await session.execute(select(Tool).where(Tool.created_by == SEED_MARKER))).scalars().all()
    )
    if existing_tools:
        print(f"Demo tools already exist ({len(existing_tools)}), skipping creation.")
        tools = existing_tools
    else:
        tools = [
            Tool(
                name=t["name"],
                tool_type=t["tool_type"],
                description=t["description"],
                config=t["config"],
                input_schema=t["input_schema"],
                created_by=SEED_MARKER,
            )
            for t in DEMO_TOOLS
        ]
        session.add_all(tools)
        await session.flush()
        print(f"Created {len(tools)} demo tools.")

    existing_skills = (
        (await session.execute(select(Skill).where(Skill.created_by == SEED_MARKER))).scalars().all()
    )
    if existing_skills:
        print(f"Demo skills already exist ({len(existing_skills)}), skipping creation.")
        skills = existing_skills
    else:
        skills = [
            Skill(name=s["name"], instruction_text=s["instruction_text"], created_by=SEED_MARKER)
            for s in DEMO_SKILLS
        ]
        session.add_all(skills)
        await session.flush()
        print(f"Created {len(skills)} demo skills.")

    existing_agents = (
        (await session.execute(select(Agent).where(Agent.created_by == SEED_MARKER))).scalars().all()
    )
    if existing_agents:
        print(f"Demo agents already exist ({len(existing_agents)}), skipping creation.")
        agents = existing_agents
    else:
        agents = []
        for spec in DEMO_AGENTS:
            agent = Agent(
                name=spec["name"],
                description=f"Demo agent seeded for dashboard testing ({spec['name']}).",
                base_instruction="You are a helpful assistant.",
                model_config_json={"model": MODEL, "temperature": 0.3},
                status=spec["status"],
                created_by=SEED_MARKER,
            )
            session.add(agent)
            await session.flush()
            for tool_idx in spec["tools"]:
                session.add(AgentTool(agent_id=agent.id, tool_id=tools[tool_idx].id))
            for order, skill_idx in enumerate(spec["skills"]):
                session.add(AgentSkill(agent_id=agent.id, skill_id=skills[skill_idx].id, attach_order=order))
            session.add(
                ConfigAuditLog(entity_type="agent", entity_id=agent.id, action="create", actor=SEED_MARKER)
            )
            agents.append(agent)
        await session.commit()
        print(f"Created {len(agents)} demo agents.")

    return tools, skills, agents


def _weighted_status() -> str:
    return random.choices(["success", "error", "timeout"], weights=[90, 7, 3])[0]


async def seed_logs(session, tools: list[Tool], agents: list[Agent]) -> None:
    flaky_tools = [t for t, spec in zip(tools, DEMO_TOOLS) if spec["flaky"]]
    normal_tools = [t for t, spec in zip(tools, DEMO_TOOLS) if not spec["flaky"]]
    now = datetime.now(timezone.utc)
    total_invocations = 0
    total_tool_calls = 0

    for day_offset in range(DAYS):
        day_start = now - timedelta(days=DAYS - day_offset)
        for agent in agents:
            per_day = random.randint(3, 18)
            for _ in range(per_day):
                created_at = day_start + timedelta(
                    hours=random.uniform(0, 23), minutes=random.uniform(0, 59)
                )
                status = _weighted_status()
                latency_ms = int(random.gauss(2500, 900))
                latency_ms = max(200, latency_ms)
                input_tokens = random.randint(200, 2000)
                output_tokens = random.randint(50, 800)
                cost = estimate_cost_usd(MODEL, input_tokens, output_tokens)

                invocation = InvocationLog(
                    agent_id=agent.id,
                    agent_version=agent.current_version,
                    trace_id=str(uuid.uuid4()),
                    status=status,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_cost_usd=cost,
                    error_message="Simulated timeout" if status == "timeout" else (
                        "Simulated tool error" if status == "error" else None
                    ),
                    invoked_by=SEED_MARKER,
                    transcript={"message": "demo message", "response_text": "demo response"},
                    created_at=created_at,
                )
                session.add(invocation)
                await session.flush()
                total_invocations += 1

                # Attach 0-2 tool calls per invocation, using this agent's
                # actual attached tools when possible, else a random demo tool.
                num_calls = random.randint(0, 2)
                for _ in range(num_calls):
                    use_flaky = flaky_tools and random.random() < 0.3
                    tool = random.choice(flaky_tools if use_flaky else normal_tools or tools)
                    call_failed = use_flaky and random.random() < 0.35
                    session.add(
                        ToolCallLog(
                            invocation_id=invocation.id,
                            tool_id=tool.id,
                            status="error" if call_failed else "success",
                            latency_ms=int(random.gauss(400, 150)) if not call_failed else int(random.gauss(4000, 500)),
                            error_message="Simulated upstream failure" if call_failed else None,
                            created_at=created_at,
                        )
                    )
                    total_tool_calls += 1

        await session.commit()
        print(f"  seeded day {day_offset + 1}/{DAYS}")

    print(f"Seeded {total_invocations} invocations and {total_tool_calls} tool calls.")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Delete previously-seeded demo data first")
    args = parser.parse_args()

    async with async_session_factory() as session:
        if args.reset:
            await reset(session)

        tools, skills, agents = await ensure_demo_entities(session)
        await seed_logs(session, tools, agents)

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
