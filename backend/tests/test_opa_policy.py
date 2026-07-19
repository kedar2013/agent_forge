from types import SimpleNamespace

import httpx

from app.agent_runtime import builder as builder_module
from app.agent_runtime.builder import _build_before_tool_callback
from app.tool_registry import opa_client
from app.tool_registry.opa_client import evaluate_opa_policy
from app.tool_registry.policy_engine import PolicyResult, ScopeResolution


def _fake_settings(**overrides):
    defaults = dict(opa_enabled=True, opa_url="http://opa.test:8181", opa_timeout_seconds=2.0, opa_fail_closed=True)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=httpx.Response(self.status_code))

    def json(self):
        return self._payload


async def test_opa_disabled_denies_and_does_not_attempt_a_network_call(monkeypatch):
    monkeypatch.setattr(opa_client, "get_settings", lambda: _fake_settings(opa_enabled=False))

    async def _unexpected_post(self, url, **kwargs):
        raise AssertionError("should never reach the network when opa_enabled=false")

    monkeypatch.setattr(httpx.AsyncClient, "post", _unexpected_post)

    result = await evaluate_opa_policy("credit_facility.query_access", {"persona": "GCM"})
    assert result.allowed is False


async def test_opa_allowed_decision_maps_to_policy_result(monkeypatch):
    monkeypatch.setattr(opa_client, "get_settings", lambda: _fake_settings())

    async def _fake_post(self, url, **kwargs):
        assert url == "http://opa.test:8181/v1/data/credit_facility/query_access"
        assert kwargs["json"]["input"]["persona"] == "GSG"
        return _FakeResponse(200, {"result": {"allowed": True, "filter": {"_policy_mode": "ATTRIBUTE_SCOPED"}}})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    result = await evaluate_opa_policy("credit_facility.query_access", {"persona": "GSG"})
    assert result.allowed is True
    assert result.filter == {"_policy_mode": "ATTRIBUTE_SCOPED"}


async def test_opa_denied_decision_carries_the_reason(monkeypatch):
    monkeypatch.setattr(opa_client, "get_settings", lambda: _fake_settings())

    async def _fake_post(self, url, **kwargs):
        return _FakeResponse(200, {"result": {"allowed": False, "reason": "CCB cannot browse."}})

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    result = await evaluate_opa_policy("credit_facility.search_access", {"persona": "CCB"})
    assert result.allowed is False
    assert result.reason == "CCB cannot browse."


async def test_opa_unreachable_fails_closed_by_default(monkeypatch):
    monkeypatch.setattr(opa_client, "get_settings", lambda: _fake_settings(opa_fail_closed=True))

    async def _fake_post(self, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    result = await evaluate_opa_policy("credit_facility.query_access", {"persona": "GCM"})
    assert result.allowed is False


async def test_opa_unreachable_fails_open_when_explicitly_configured(monkeypatch):
    monkeypatch.setattr(opa_client, "get_settings", lambda: _fake_settings(opa_fail_closed=False))

    async def _fake_post(self, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    result = await evaluate_opa_policy("credit_facility.query_access", {"persona": "GCM"})
    assert result.allowed is True
    assert result.filter == {}


async def test_opa_malformed_response_fails_closed(monkeypatch):
    monkeypatch.setattr(opa_client, "get_settings", lambda: _fake_settings(opa_fail_closed=True))

    async def _fake_post(self, url, **kwargs):
        return _FakeResponse(200, {"nonsense": True})  # no "result" key

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    result = await evaluate_opa_policy("credit_facility.query_access", {"persona": "GCM"})
    assert result.allowed is False


# --- builder.py's _before_tool routing (engine="opa" vs. default) ----------


def _fake_tool_row(name: str, policy_id):
    return SimpleNamespace(name=name, config={"policy_id": str(policy_id)})


def _fake_tool_context():
    return SimpleNamespace(state={"_principal_user_id": "user-1"}, invocation_id="turn-1", function_call_id="fc-1")


async def test_before_tool_routes_to_opa_when_policy_engine_is_opa(monkeypatch):
    policy_id = "11111111-1111-1111-1111-111111111111"
    policy = SimpleNamespace(
        resolver_config={"engine": "opa", "opa_package": "credit_facility.query_access"},
        rules={},
    )

    async def _fake_resolve_scope(pol, user_id):
        return ScopeResolution(found=True, discriminator="GSG", scope={})

    called_with = {}

    async def _fake_evaluate_opa_policy(opa_package, input_doc):
        called_with["opa_package"] = opa_package
        called_with["input_doc"] = input_doc
        return PolicyResult(allowed=True, filter={"_policy_mode": "ATTRIBUTE_SCOPED", "_attr_values": ["L3", "L4"]})

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("apply_policy (Python engine) should not be called when engine='opa'")

    monkeypatch.setattr(builder_module, "resolve_scope", _fake_resolve_scope)
    monkeypatch.setattr(builder_module, "evaluate_opa_policy", _fake_evaluate_opa_policy)
    monkeypatch.setattr(builder_module, "apply_policy", _fail_if_called)

    callback = _build_before_tool_callback([_fake_tool_row("query_facility_data", policy_id)], {policy_id: policy})
    args = {"sql": "SELECT 1"}
    result = await callback(SimpleNamespace(name="query_facility_data"), args, _fake_tool_context())

    assert result is None  # allowed -- callback returns None to let the real tool run
    assert args["_policy_mode"] == "ATTRIBUTE_SCOPED"
    assert args["_attr_values"] == ["L3", "L4"]
    assert called_with["opa_package"] == "credit_facility.query_access"
    assert called_with["input_doc"]["persona"] == "GSG"


async def test_before_tool_denies_when_opa_denies(monkeypatch):
    policy_id = "22222222-2222-2222-2222-222222222222"
    policy = SimpleNamespace(
        id=policy_id,
        resolver_config={"engine": "opa", "opa_package": "credit_facility.search_access"},
        rules={},
    )

    async def _fake_resolve_scope(pol, user_id):
        return ScopeResolution(found=True, discriminator="CCB", scope={})

    async def _fake_evaluate_opa_policy(opa_package, input_doc):
        return PolicyResult(allowed=False, reason="CCB access requires an exact gfcid.")

    denial_calls = []

    async def _fake_record_policy_denial(**kwargs):
        denial_calls.append(kwargs)

    monkeypatch.setattr(builder_module, "resolve_scope", _fake_resolve_scope)
    monkeypatch.setattr(builder_module, "evaluate_opa_policy", _fake_evaluate_opa_policy)
    monkeypatch.setattr(builder_module, "record_policy_denial", _fake_record_policy_denial)

    callback = _build_before_tool_callback([_fake_tool_row("query_companies", policy_id)], {policy_id: policy})
    result = await callback(SimpleNamespace(name="query_companies"), {}, _fake_tool_context())

    assert result == {"error": "CCB access requires an exact gfcid."}
    assert len(denial_calls) == 1
    assert denial_calls[0]["engine"] == "opa"
    assert denial_calls[0]["persona"] == "CCB"
    assert denial_calls[0]["tool_name"] == "query_companies"


async def test_before_tool_uses_python_engine_when_no_engine_configured(monkeypatch):
    """The default (no `engine` key at all) must keep using apply_policy,
    not silently start routing through OPA -- confirms per-policy opt-in,
    not a platform-wide behavior change."""
    policy_id = "33333333-3333-3333-3333-333333333333"
    policy = SimpleNamespace(
        resolver_config={},  # no "engine" key -- the default, every existing policy today
        rules={"GCM": {"_policy_mode": "GLOBAL"}},
    )

    async def _fake_resolve_scope(pol, user_id):
        return ScopeResolution(found=True, discriminator="GCM", scope={})

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("evaluate_opa_policy should not be called for a policy with no engine='opa'")

    monkeypatch.setattr(builder_module, "resolve_scope", _fake_resolve_scope)
    monkeypatch.setattr(builder_module, "evaluate_opa_policy", _fail_if_called)

    callback = _build_before_tool_callback([_fake_tool_row("query_facility_data", policy_id)], {policy_id: policy})
    args = {}
    result = await callback(SimpleNamespace(name="query_facility_data"), args, _fake_tool_context())

    assert result is None
    assert args["_policy_mode"] == "GLOBAL"
