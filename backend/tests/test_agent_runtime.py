import pytest

from app.agent_runtime.builder import compose_instruction, get_or_build_agent
from app.agent_runtime.cache import agent_cache
from app.models.agents import Agent, AgentSkill
from app.models.skills import Skill


def test_compose_instruction_order():
    class FakeSkill:
        def __init__(self, name, text):
            self.name = name
            self.instruction_text = text

    result = compose_instruction(
        "BASE",
        [FakeSkill("first", "one"), FakeSkill("second", "two")],
    )
    assert result.index("BASE") < result.index("// skill: first") < result.index(
        "// skill: second"
    )
    assert "one" in result
    assert "two" in result


async def test_build_from_live_config_composes_attached_skills(db_session, unique_name):
    agent = Agent(
        name=unique_name("runtime_agent"),
        base_instruction="You are helpful.",
        model_config_json={"model": "gemini-3.5-flash", "temperature": 0.1},
    )
    skill_a = Skill(name=unique_name("skill_a"), instruction_text="Be terse.")
    skill_b = Skill(name=unique_name("skill_b"), instruction_text="Cite sources.")
    db_session.add_all([agent, skill_a, skill_b])
    await db_session.flush()

    db_session.add(AgentSkill(agent_id=agent.id, skill_id=skill_b.id, attach_order=1))
    db_session.add(AgentSkill(agent_id=agent.id, skill_id=skill_a.id, attach_order=0))
    await db_session.commit()

    built = await get_or_build_agent(db_session, agent.id, version=None)

    assert built.instruction.index("Be terse.") < built.instruction.index("Cite sources.")
    assert "You are helpful." in built.instruction


async def test_cache_hit_and_invalidation(db_session, unique_name):
    from app.models.agents import AgentVersion

    agent = Agent(
        name=unique_name("cached_agent"),
        base_instruction="Cached agent instruction.",
        model_config_json={"model": "gemini-3.5-flash"},
        status="published",
        current_version=1,
    )
    db_session.add(agent)
    await db_session.flush()
    version_row = AgentVersion(
        agent_id=agent.id,
        version=1,
        snapshot={
            "name": agent.name,
            "description": None,
            "base_instruction": agent.base_instruction,
            "model_config": {"model": "gemini-3.5-flash"},
            "tools": [],
            "skills": [],
            "sub_agents": [],
        },
    )
    db_session.add(version_row)
    await db_session.commit()

    agent_cache.invalidate(agent.id)
    assert agent_cache.get(agent.id, 1) is None

    first = await get_or_build_agent(db_session, agent.id, version=1)
    assert agent_cache.get(agent.id, 1) is first

    second = await get_or_build_agent(db_session, agent.id, version=1)
    assert second is first  # cache hit, not rebuilt

    agent_cache.invalidate(agent.id)
    assert agent_cache.get(agent.id, 1) is None

    third = await get_or_build_agent(db_session, agent.id, version=1)
    assert third is not first  # rebuilt after invalidation
