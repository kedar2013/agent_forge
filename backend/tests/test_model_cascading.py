from google.adk.agents import Agent as AdkAgent

from app.agent_runtime.cascade import build_escalated_agent, is_escalation_over_budget
from app.scil.runner import get_scil_config


def _fake_agent_row(model_config: dict) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(model_config_json=model_config)


# --- ScilConfig round-trip ---------------------------------------------------


def test_get_scil_config_reads_escalation_fields():
    agent_row = _fake_agent_row(
        {
            "scil": {
                "enabled": True,
                "validators": ["sql"],
                "escalation_model": "gemini-2.5-pro",
                "escalation_max_cost_usd": 0.05,
            }
        }
    )
    config = get_scil_config(agent_row)
    assert config.escalation_model == "gemini-2.5-pro"
    assert config.escalation_max_cost_usd == 0.05


def test_get_scil_config_defaults_escalation_off():
    config = get_scil_config(_fake_agent_row({"scil": {"enabled": True}}))
    assert config.escalation_model is None
    assert config.escalation_max_cost_usd is None


# --- is_escalation_over_budget ----------------------------------------------


def test_over_budget_when_estimate_exceeds_ceiling():
    assert is_escalation_over_budget(estimated_cost=0.10, max_cost=0.05) is True


def test_not_over_budget_when_estimate_is_within_ceiling():
    assert is_escalation_over_budget(estimated_cost=0.02, max_cost=0.05) is False


def test_not_over_budget_when_no_ceiling_configured():
    assert is_escalation_over_budget(estimated_cost=1000.0, max_cost=None) is False


def test_not_over_budget_when_no_estimate_available():
    assert is_escalation_over_budget(estimated_cost=None, max_cost=0.01) is False


# --- build_escalated_agent ---------------------------------------------------


def test_build_escalated_agent_swaps_model_without_mutating_original():
    original = AdkAgent(name="stock_market_analyst", model="gemini-2.0-flash", instruction="You are helpful.")

    escalated = build_escalated_agent(original, "gemini-2.5-pro")

    assert escalated is not None
    assert escalated.model == "gemini-2.5-pro"
    assert original.model == "gemini-2.0-flash"  # untouched -- may be a shared cached instance
    assert escalated is not original


def test_build_escalated_agent_wraps_anthropic_models_via_litellm():
    original = AdkAgent(name="agent", model="gemini-2.0-flash", instruction="You are helpful.")

    escalated = build_escalated_agent(original, "anthropic/claude-opus-4-8")

    assert escalated is not None
    # _resolve_model wraps an "anthropic/..." string in ADK's LiteLlm
    # adapter rather than passing the bare string through -- same
    # resolution builder.py itself uses at normal build time.
    assert escalated.model.model == "anthropic/claude-opus-4-8"


def test_build_escalated_agent_declines_agents_with_sub_agents():
    child = AdkAgent(name="specialist", model="gemini-2.0-flash", instruction="You are a specialist.")
    orchestrator = AdkAgent(
        name="orchestrator", model="gemini-2.0-flash", instruction="You route.", sub_agents=[child]
    )

    assert build_escalated_agent(orchestrator, "gemini-2.5-pro") is None
