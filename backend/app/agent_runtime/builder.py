import logging
import uuid

from google.adk.agents import Agent as AdkAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.planners import PlanReActPlanner
from google.adk.tools.base_toolset import BaseToolset
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.byok import ContextAwareLiteLLMClient
from app.agent_runtime.cache import agent_cache
from app.agent_runtime.planning_config import get_planning_config
from app.agent_runtime.schema_utils import build_output_schema_model
from app.db import async_session_factory
from app.models.access_policies import AccessPolicy
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool, AgentVersion
from app.models.logs import InvocationLog, ToolCallLog
from app.models.skills import Skill
from app.models.tools import Tool
from app.observability.rca import cap_payload, tool_call_error
from app.tool_registry.factory import build_tool
from app.tool_registry.policy_engine import ScopeResolution, apply_policy, resolve_scope

logger = logging.getLogger(__name__)


async def _load_policies(
    db: AsyncSession, tools_rows: list[Tool], workspace_id: uuid.UUID | None
) -> dict[str, AccessPolicy]:
    policy_ids = {t.config["policy_id"] for t in tools_rows if t.config.get("policy_id")}
    if not policy_ids:
        return {}
    # Same cross-tenant defense-in-depth as every other recursive load in
    # this file: a policy_id belonging to a different workspace is excluded
    # silently rather than trusted just because a tool row referenced it.
    result = await db.execute(
        select(AccessPolicy).where(AccessPolicy.id.in_(policy_ids), AccessPolicy.workspace_id == workspace_id)
    )
    return {str(p.id): p for p in result.scalars().all()}


#  A router orchestrator built with orchestration_patterns.build_router_
# instruction() is instructed to never transfer to the same specialist twice
# for one question — this is the hard backstop if a model ignores that.
# Generous enough for a question that legitimately needs several
# specialists (each one costs 2 transfers: out to it, back to the parent),
# while still bounding a model that starts cycling regardless of the
# instruction. Keyed per-turn (see _before_tool below), never across turns.
_MAX_TRANSFERS_PER_TURN = 8


async def _resolve_durable_invocation_id(tool_context) -> uuid.UUID | None:
    """Looks up the Agent Forge `InvocationLog` row this ADK invocation_id
    belongs to — set eagerly by `app.logging_hooks.start_durable_run` before
    the turn's first `runner.run_async()` call (see
    `playground_api/router.py`'s `_run_turn`) — or None if this turn never
    got a durable checkpoint row (every agent that hasn't opted into
    `model_config.durable_execution`, plus Playground runs even when it has,
    since Playground's InMemorySessionService has nothing to resume).
    Cached on `tool_context.state` so a multi-tool-call turn pays for this
    lookup once, not once per tool call — `tool_context.state` is reset on
    resume (ADK's own resumability contract: "any temporary/in-memory state
    will be lost upon resumption"), which is fine, it just means one extra
    lookup on the first tool call after a resume."""
    cache_key = f"_durable_invocation_log_id:{tool_context.invocation_id}"
    if cache_key in tool_context.state:
        cached = tool_context.state[cache_key]
        return uuid.UUID(cached) if cached else None
    async with async_session_factory() as session:
        result = await session.execute(
            select(InvocationLog.id).where(InvocationLog.adk_invocation_id == tool_context.invocation_id)
        )
        row_id = result.scalar_one_or_none()
    tool_context.state[cache_key] = str(row_id) if row_id else ""
    return row_id


def _build_before_tool_callback(
    tools_rows: list[Tool], policies_by_id: dict[str, AccessPolicy], durable_execution_enabled: bool = False
):
    """One callback, registered on every agent this platform builds, that
    generically (a) caps how many agent-to-agent hand-offs can happen in a
    single turn (see _MAX_TRANSFERS_PER_TURN above) — applies to every
    agent uniformly, not just ones deliberately built as a multi-specialist
    router, since ADK's transfer_to_agent is itself just another
    FunctionTool and so already flows through this same callback; (b)
    injects trusted, server-verified session-state values (e.g. the
    caller's principal id) into any tool whose config lists them under
    `context_params`; and (c) for any tool whose config carries a
    `policy_id`, mechanically enforces that `AccessPolicy`'s row-level
    filter — or denies the call outright — before the tool ever runs; and
    (d), when `durable_execution_enabled` (this turn opted into
    `model_config.durable_execution` AND is running on a durable session —
    see `_run_turn`), checks whether this exact tool-call attempt was
    already durably recorded by a prior, crashed run of this same
    invocation — if so, returns its cached output directly instead of
    re-executing, closing the one gap ADK's own resumability explicitly
    disclaims ("tool call to resume needs to be idempotent because we only
    guarantee at-least-once behavior once resumed").

    None of these four are specific to any one tool type or domain: a
    future domain/orchestrator opts in purely through its own config (or,
    for the hop cap, simply by existing) — no code here changes.
    """
    context_params_by_tool = {
        t.name: t.config["context_params"] for t in tools_rows if t.config.get("context_params")
    }
    policy_by_tool = {t.name: t.config["policy_id"] for t in tools_rows if t.config.get("policy_id")}

    async def _before_tool(tool, args, tool_context):
        if tool.name == "transfer_to_agent":
            # invocation_id is unique per top-level runner.run_async() call
            # (one user turn) and never reused across turns, so this counter
            # needs no explicit reset — a brand-new turn always starts at 0.
            state_key = f"_transfer_hops:{tool_context.invocation_id}"
            hops = tool_context.state.get(state_key, 0) + 1
            tool_context.state[state_key] = hops
            if hops > _MAX_TRANSFERS_PER_TURN:
                return {
                    "error": (
                        "Too many agent hand-offs for this single question. Stop "
                        "transferring and answer now with whatever has already been "
                        "gathered, noting plainly anything you weren't able to resolve."
                    )
                }
        elif durable_execution_enabled and tool_context.function_call_id:
            invocation_log_id = await _resolve_durable_invocation_id(tool_context)
            if invocation_log_id is not None:
                idempotency_key = f"{tool_context.invocation_id}:{tool_context.function_call_id}"
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(ToolCallLog.output).where(
                            ToolCallLog.invocation_id == invocation_log_id,
                            ToolCallLog.idempotency_key == idempotency_key,
                            ToolCallLog.status == "success",
                        )
                    )
                    cached_output = result.scalar_one_or_none()
                # A resume re-attempting the one tool call ADK only
                # guarantees at-least-once for finds it already succeeded
                # here and skips real execution — the actual output was
                # already durably written by _after_tool before the crash.
                if cached_output is not None:
                    return cached_output

        mapping = context_params_by_tool.get(tool.name)
        if mapping:
            for arg_name, state_key in mapping.items():
                if state_key in tool_context.state:
                    args[arg_name] = tool_context.state[state_key]

        policy_id = policy_by_tool.get(tool.name)
        if not policy_id:
            return None

        policy = policies_by_id.get(policy_id)
        if policy is None:
            logger.error("Tool '%s' references unknown access_policy %s", tool.name, policy_id)
            return {"error": "Misconfigured tool: referenced access policy not found."}

        # A policy decides which trusted identity it matches persona/coverage
        # data against — the raw Agent Forge user id by default, or a corporate
        # id (e.g. SOEID) for domains whose own data is keyed by that instead
        # (see chat_api/router.py's _ensure_session_state for what's on state).
        identity_key = policy.resolver_config.get("identity_state_key", "_principal_user_id")
        user_id = tool_context.state.get(identity_key)
        if not user_id:
            return {"error": "No authenticated identity on this session — cannot authorize this request."}

        cache_key = f"_policy_scope:{policy_id}"
        cached = tool_context.state.get(cache_key)
        if cached is not None:
            scope = ScopeResolution.from_state(cached)
        else:
            scope = await resolve_scope(policy, user_id)
            tool_context.state[cache_key] = scope.to_state()

        result = apply_policy(policy, scope, args)
        if not result.allowed:
            return {"error": result.reason}
        # `result.filter` is opaque here by design: whatever reserved keys a
        # policy's rule produced get merged straight into the tool's args.
        # A Mongo-flavored rule might produce a single `_enforced_filter`
        # dict key; a SQL-flavored rule (see mysql_tool.py) produces several
        # named bind-parameter keys instead. Neither this callback nor
        # policy_engine.py needs to know which — that convention lives
        # entirely between a domain's `rules` config and its tool's query.
        args.update(result.filter or {})
        return None

    return _before_tool


def _build_after_tool_callback(tools_rows: list[Tool], durable_execution_enabled: bool = False):
    """Counterpart to `_build_before_tool_callback`'s durable-execution
    branch: on every REAL (non-replayed) tool execution, synchronously
    (awaited, not fire-and-forget — durability is the entire point) writes
    one `ToolCallLog` row keyed by this exact attempt's idempotency key, so
    a later resume's `_before_tool` lookup can find it. A no-op whenever
    durable execution isn't enabled for this turn, or this turn never got a
    durable checkpoint row in the first place (e.g. Playground) — same cost
    as today (zero) for every agent that hasn't opted in.

    `tool_id` is resolved by name against this agent's own `tools_rows`
    (already loaded once at build time, same as `context_params_by_tool`/
    `policy_by_tool` above) rather than a second query per call.
    """
    tool_id_by_name = {t.name: t.id for t in tools_rows}

    async def _after_tool(tool, args, tool_context, tool_response):
        if not durable_execution_enabled or tool.name == "transfer_to_agent" or not tool_context.function_call_id:
            return None

        invocation_log_id = await _resolve_durable_invocation_id(tool_context)
        if invocation_log_id is None:
            return None

        idempotency_key = f"{tool_context.invocation_id}:{tool_context.function_call_id}"
        counter_key = f"_durable_call_index:{tool_context.invocation_id}"
        call_index = tool_context.state.get(counter_key, 0)
        tool_context.state[counter_key] = call_index + 1
        error = tool_call_error(tool_response)

        async with async_session_factory() as session:
            session.add(
                ToolCallLog(
                    invocation_id=invocation_log_id,
                    tool_id=tool_id_by_name.get(tool.name),
                    call_index=call_index,
                    status="error" if error else "success",
                    latency_ms=0,
                    error_message=error,
                    input=cap_payload(args),
                    output=cap_payload(tool_response),
                    idempotency_key=idempotency_key,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                # Already durably recorded — the unique (invocation_id,
                # idempotency_key) constraint makes a duplicate write here a
                # harmless no-op, not a real conflict.
                await session.rollback()
        return None

    return _after_tool


def _resolve_model(model: str) -> str | LiteLlm:
    """ADK's `Agent(model=...)` accepts either a bare Gemini model-string
    (its native path) or a `BaseLlm` instance. A model_config.model value of
    "anthropic/<claude-model-id>" — the litellm provider-routing convention,
    and exactly what the Agent Builder's model dropdown stores for every
    Claude option — is wrapped in ADK's LiteLlm adapter so the agent runs on
    Claude instead of Gemini; any other string (e.g. "gemini-2.5-flash")
    passes through unchanged for ADK's native Gemini path — a bare string
    resolves to `app.agent_runtime.byok.ContextualGemini` at call time
    instead of ADK's stock `Gemini`, since that subclass is registered as
    the handler for every `gemini-*` model string at app startup (see
    `byok.register()`, called from `app/main.py`).

    The Claude branch passes `llm_client=ContextAwareLiteLLMClient()` so
    this cached, shared-across-users `LiteLlm` instance (built once here,
    reused by agent_cache) sources its API key from a per-request
    ContextVar at call time rather than a value frozen at construction —
    see app/agent_runtime/byok.py's module docstring for why the two model
    providers need different fixes for the same "don't burn the operator's
    own key on public traffic" requirement.
    """
    if model.startswith("anthropic/"):
        return LiteLlm(model=model, llm_client=ContextAwareLiteLLMClient())
    return model


def compose_instruction(base_instruction: str, skills: list[Skill]) -> str:
    """base_instruction + each attached skill's instruction_text, in order.

    Mirrors the frontend's "effective prompt preview" format exactly, so what
    you see in that panel is what the model actually receives.
    """
    parts = [base_instruction]
    for skill in skills:
        parts.append(f"\n\n// skill: {skill.name}\n{skill.instruction_text}")
    return "".join(parts)


async def _load_live_skills(db: AsyncSession, agent_id: uuid.UUID, workspace_id: uuid.UUID | None) -> list[Skill]:
    result = await db.execute(
        select(Skill)
        .join(AgentSkill, AgentSkill.skill_id == Skill.id)
        .where(AgentSkill.agent_id == agent_id, Skill.workspace_id == workspace_id)
        .order_by(AgentSkill.attach_order)
    )
    return list(result.scalars().all())


async def _load_live_tools(db: AsyncSession, agent_id: uuid.UUID, workspace_id: uuid.UUID | None) -> list[Tool]:
    result = await db.execute(
        select(Tool)
        .join(AgentTool, AgentTool.tool_id == Tool.id)
        .where(AgentTool.agent_id == agent_id, Tool.workspace_id == workspace_id)
    )
    return list(result.scalars().all())


async def _load_live_subagent_ids(db: AsyncSession, agent_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(
        select(AgentSubagent.child_agent_id).where(AgentSubagent.parent_agent_id == agent_id)
    )
    return [row[0] for row in result]


async def _build_from_live_config(
    db: AsyncSession,
    agent_id: uuid.UUID,
    _building: set[uuid.UUID],
    workspace_id: uuid.UUID | None = None,
    durable_execution_enabled: bool = False,
) -> AdkAgent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"Agent {agent_id} not found")
    # The root call establishes the tenant boundary from the agent's own row
    # (its caller already verified this matches the requesting principal —
    # see playground_api/chat_api). Every recursive call re-verifies each
    # tool/skill/sub-agent it pulls in belongs to that SAME workspace, so a
    # cross-tenant reference (e.g. a legacy NULL-workspace row, or a future
    # bug in the attach-time check) can never silently end up inside a built
    # agent tree — defense in depth beyond the entry-point check.
    if workspace_id is None:
        workspace_id = agent.workspace_id

    skills = await _load_live_skills(db, agent_id, workspace_id)
    tools_rows = await _load_live_tools(db, agent_id, workspace_id)
    subagent_ids = await _load_live_subagent_ids(db, agent_id)

    tools: list = [build_tool(t) for t in tools_rows]
    policies_by_id = await _load_policies(db, tools_rows, workspace_id)
    before_tool_callback = _build_before_tool_callback(tools_rows, policies_by_id, durable_execution_enabled)
    after_tool_callback = _build_after_tool_callback(tools_rows, durable_execution_enabled)

    sub_agents: list[AdkAgent] = []
    for child_id in subagent_ids:
        if child_id in _building:
            continue  # defense in depth; config_api already rejects cycles on write
        child_row = await db.get(Agent, child_id)
        if child_row is None or child_row.workspace_id != workspace_id:
            continue  # missing or cross-tenant — excluded silently, not a hard failure
        sub_agents.append(
            await _build_from_live_config(
                db, child_id, _building | {agent_id}, workspace_id, durable_execution_enabled
            )
        )

    return AdkAgent(
        name=_safe_agent_name(agent.name),
        description=agent.description or "",
        model=_resolve_model(agent.model_config_json.get("model", "gemini-3.5-flash")),
        instruction=compose_instruction(agent.base_instruction, skills),
        tools=tools,
        sub_agents=sub_agents,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
        output_schema=build_output_schema_model(agent.output_schema),
        output_key=agent.output_key,
        # Decided per-node from this agent's OWN model_config, not inherited
        # from a parent/root the way durable_execution is — Planner/ReAct is
        # a property of how one agent reasons, not of the whole turn, so
        # each agent in a tree opts in independently. See
        # agent_runtime/planning_config.py; ADK's own flows/llm_flows/
        # _nl_planning.py does the rest whenever `planner` is set.
        planner=PlanReActPlanner() if get_planning_config(agent).enabled else None,
        # Allowing transfer back to the parent is what lets a specialist that
        # can't help with a message hand back to its orchestrator to re-route
        # — without this, once a session resumes a given specialist (ADK
        # always continues with whichever agent last answered), that
        # specialist is stuck answering everything for the rest of the
        # conversation, even requests entirely outside its domain.
        disallow_transfer_to_parent=False,
    )


async def _build_from_snapshot(
    db: AsyncSession,
    agent_id: uuid.UUID,
    version: int,
    _building: set[uuid.UUID],
    workspace_id: uuid.UUID | None = None,
    durable_execution_enabled: bool = False,
) -> AdkAgent:
    agent_row = await db.get(Agent, agent_id)
    if agent_row is None:
        raise ValueError(f"Agent {agent_id} not found")
    # Same tenant-boundary defense-in-depth as _build_from_live_config — the
    # snapshot JSON itself carries no workspace info, so this is derived from
    # the agent's own row and threaded down through recursion.
    if workspace_id is None:
        workspace_id = agent_row.workspace_id

    result = await db.execute(
        select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version == version)
    )
    version_row = result.scalar_one_or_none()
    if version_row is None:
        raise ValueError(f"Agent {agent_id} has no version {version}")
    snapshot = version_row.snapshot

    skill_ids = [uuid.UUID(s["id"]) for s in snapshot.get("skills", [])]
    skills: list[Skill] = []
    if skill_ids:
        result = await db.execute(select(Skill).where(Skill.id.in_(skill_ids), Skill.workspace_id == workspace_id))
        by_id = {s.id: s for s in result.scalars().all()}
        # Skill *content* is not itself versioned in this schema — only the
        # set/order attached to this agent version is frozen; live edits to a
        # skill's instruction_text are picked up by every version that uses it.
        order = {uuid.UUID(s["id"]): s["attach_order"] for s in snapshot.get("skills", [])}
        skills = sorted((by_id[i] for i in skill_ids if i in by_id), key=lambda s: order[s.id])

    tool_ids = [uuid.UUID(t["id"]) for t in snapshot.get("tools", [])]
    tools_rows: list[Tool] = []
    if tool_ids:
        result = await db.execute(select(Tool).where(Tool.id.in_(tool_ids), Tool.workspace_id == workspace_id))
        tools_rows = list(result.scalars().all())

    tools: list = [build_tool(t) for t in tools_rows]
    policies_by_id = await _load_policies(db, tools_rows, workspace_id)
    before_tool_callback = _build_before_tool_callback(tools_rows, policies_by_id, durable_execution_enabled)
    after_tool_callback = _build_after_tool_callback(tools_rows, durable_execution_enabled)

    sub_agents: list[AdkAgent] = []
    for sub in snapshot.get("sub_agents", []):
        child_id = uuid.UUID(sub["id"])
        if child_id in _building:
            continue
        child_agent_row = await db.get(Agent, child_id)
        if child_agent_row is None or child_agent_row.workspace_id != workspace_id:
            continue  # missing or cross-tenant — excluded silently, not a hard failure
        # Built fresh, never from agent_cache: ADK sets a mutable parent_agent
        # reference on a child the moment it's passed into sub_agents=[...], so
        # a cached (already-parented) instance can't be reused as anyone's
        # child a second time — including the same parent rebuilt after a
        # republish, or a second parent that also attaches this agent.
        # durable_execution_enabled is inherited from the ROOT agent being
        # run, not re-derived from each sub-agent's own config — durability
        # is a property of the whole turn/workflow, decided once.
        sub_agents.append(
            await _build_from_snapshot(
                db,
                child_id,
                child_agent_row.current_version,
                _building | {agent_id},
                workspace_id,
                durable_execution_enabled,
            )
        )

    return AdkAgent(
        name=_safe_agent_name(snapshot["name"]),
        description=snapshot.get("description") or "",
        model=_resolve_model(snapshot["model_config"].get("model", "gemini-3.5-flash")),
        instruction=compose_instruction(snapshot["base_instruction"], skills),
        tools=tools,
        sub_agents=sub_agents,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
        output_schema=build_output_schema_model(snapshot.get("output_schema")),
        output_key=snapshot.get("output_key"),
        # Same per-node planning opt-in as _build_from_live_config, read from
        # the frozen snapshot's own model_config here instead of a live row.
        planner=PlanReActPlanner() if (snapshot["model_config"] or {}).get("planning", {}).get("enabled") else None,
        disallow_transfer_to_parent=False,
    )


def _safe_agent_name(name: str) -> str:
    # ADK agent names must be valid identifiers (no spaces/punctuation).
    return "".join(c if c.isalnum() else "_" for c in name) or "agent"


async def get_or_build_agent(
    db: AsyncSession,
    agent_id: uuid.UUID,
    version: int | None,
    _building: set[uuid.UUID] | None = None,
    durable_execution_enabled: bool = False,
) -> AdkAgent:
    """Builds (or returns cached) a `google.adk.agents.Agent` for this config.

    version=None builds straight from the live/draft tables and is never
    cached — used by the playground, where you're actively iterating.
    version=<int> builds from the frozen `agent_versions.snapshot` and is
    cached until the next publish evicts it.

    `durable_execution_enabled` is baked into the built agent's before/after
    tool callbacks (see `_build_before_tool_callback`/`_build_after_tool_
    callback`) — unlike SCIL's config (read fresh on every turn in
    `_run_turn`, never cached), this one lives inside the cached build
    itself, so for a published agent (version=<int>) toggling
    `model_config.durable_execution.enabled` only takes effect on the next
    publish, same as any other model_config change (instruction, tools,
    model) — not a gap, just the existing agent_cache contract.
    """
    building = set(_building or ())

    if version is not None:
        cached = agent_cache.get(agent_id, version)
        if cached is not None:
            return cached
        built = await _build_from_snapshot(
            db, agent_id, version, building, durable_execution_enabled=durable_execution_enabled
        )
        agent_cache.set(agent_id, version, built)
        return built

    return await _build_from_live_config(db, agent_id, building, durable_execution_enabled=durable_execution_enabled)


async def close_agent_toolsets(agent: AdkAgent) -> None:
    """Closes every `BaseToolset` (e.g. `McpToolset`, which owns a live MCP
    subprocess/session) reachable from this agent tree — itself plus every
    sub_agent, recursively.

    Only ever call this on a tree built with version=None (the playground's
    "always rebuild from live config, never cache" path) — a version=<int>
    build is cached in `agent_cache` and reused across requests, so closing
    its toolsets would kill the subprocess out from under a later request
    still using that cached agent.

    Without this, every playground/live-build call leaks one subprocess per
    distinct mcp_tool used in that turn: McpToolset's MCPSessionManager
    happily pools/reuses a session across repeated calls on the SAME
    instance, but a live build constructs a brand new McpToolset (hence a
    brand new session manager, hence a brand new subprocess) every single
    call, and nothing was ever closing the previous one. Confirmed live: 124
    orphaned mcp_servers/*.py subprocesses accumulated over one session's
    worth of playground testing before this fix.
    """
    seen: set[int] = set()

    async def _walk(node: AdkAgent) -> None:
        for tool in getattr(node, "tools", None) or []:
            if isinstance(tool, BaseToolset) and id(tool) not in seen:
                seen.add(id(tool))
                try:
                    await tool.close()
                except Exception:
                    logger.warning("Error closing toolset for agent '%s'", node.name, exc_info=True)
        for sub_agent in getattr(node, "sub_agents", None) or []:
            await _walk(sub_agent)

    await _walk(agent)
