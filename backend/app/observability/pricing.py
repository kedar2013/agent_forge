"""Rough $/1M-token pricing for cost estimation.

These are approximate published rates and will drift out of date — every
number this module produces should be presented to users as an *estimate*,
never as a billing-accurate figure.
"""

# {model_prefix: (input $/1M tokens, output $/1M tokens)}
_PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
    # Claude models, run via ADK's LiteLlm adapter — stored/reported as
    # "anthropic/<model-id>" (see agent_runtime/builder.py._resolve_model).
    "anthropic/claude-opus-4-8": (5.00, 25.00),
    "anthropic/claude-opus-4-7": (5.00, 25.00),
    "anthropic/claude-sonnet-5": (3.00, 15.00),
    "anthropic/claude-sonnet-4-6": (3.00, 15.00),
    "anthropic/claude-haiku-4-5": (1.00, 5.00),
}
_DEFAULT_RATE = (0.30, 2.50)


def estimate_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None and output_tokens is None:
        return None

    input_rate, output_rate = next(
        (rate for prefix, rate in _PRICING_PER_MILLION_TOKENS.items() if model.startswith(prefix)),
        _DEFAULT_RATE,
    )
    cost = ((input_tokens or 0) / 1_000_000) * input_rate + ((output_tokens or 0) / 1_000_000) * output_rate
    return round(cost, 6)
