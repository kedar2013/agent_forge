from types import SimpleNamespace

from app.agent_runtime.builder import _MAX_TRANSFERS_PER_TURN, _build_before_tool_callback


def _fake_tool_context(invocation_id: str) -> SimpleNamespace:
    return SimpleNamespace(state={}, invocation_id=invocation_id)


async def test_transfer_hop_limit_blocks_after_max_within_one_turn():
    callback = _build_before_tool_callback(tools_rows=[], policies_by_id={})
    tool = SimpleNamespace(name="transfer_to_agent")
    ctx = _fake_tool_context("turn-1")

    for _ in range(_MAX_TRANSFERS_PER_TURN):
        result = await callback(tool, {"agent_name": "some_specialist"}, ctx)
        assert result is None

    blocked = await callback(tool, {"agent_name": "some_specialist"}, ctx)
    assert blocked is not None
    assert "error" in blocked
    assert "too many" in blocked["error"].lower()


async def test_transfer_hop_limit_resets_for_a_new_turn():
    callback = _build_before_tool_callback(tools_rows=[], policies_by_id={})
    tool = SimpleNamespace(name="transfer_to_agent")

    ctx_1 = _fake_tool_context("turn-1")
    for _ in range(_MAX_TRANSFERS_PER_TURN + 3):
        await callback(tool, {"agent_name": "some_specialist"}, ctx_1)
    exhausted = await callback(tool, {"agent_name": "some_specialist"}, ctx_1)
    assert exhausted is not None  # confirm turn-1 is indeed exhausted

    # A brand-new turn (different invocation_id) starts its own count at zero.
    ctx_2 = _fake_tool_context("turn-2")
    result = await callback(tool, {"agent_name": "some_specialist"}, ctx_2)
    assert result is None


async def test_non_transfer_tool_calls_are_unaffected_by_the_hop_counter():
    callback = _build_before_tool_callback(tools_rows=[], policies_by_id={})
    other_tool = SimpleNamespace(name="query_companies")
    ctx = _fake_tool_context("turn-1")

    for _ in range(_MAX_TRANSFERS_PER_TURN + 10):
        result = await callback(other_tool, {"sql": "SELECT 1"}, ctx)
        assert result is None
