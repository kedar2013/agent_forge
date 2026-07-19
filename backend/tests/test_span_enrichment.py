import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import app.observability.tracing as tracing_module
from app.playground_api.router import _emit_scil_cache_span


@pytest.fixture
def span_exporter():
    """Swaps the module-level tracer (normally a no-op unless OTEL_ENABLED)
    for a real in-memory one, so span name/attributes can be asserted on
    directly without a live Jaeger/OTLP collector. Restored after each test
    so this doesn't leak into unrelated tests exercising the same code."""
    original_tracer = tracing_module._tracer
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracing_module._tracer = provider.get_tracer("test")
    yield exporter
    tracing_module._tracer = original_tracer


def test_scil_cache_span_records_route_and_attributes(span_exporter):
    _emit_scil_cache_span("cache_hit", agent_name="my_agent", session_id="sess-1", latency_ms=42)

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "scil.cache"
    assert span.attributes["scil.route"] == "cache_hit"
    assert span.attributes["agent.name"] == "my_agent"
    assert span.attributes["session.id"] == "sess-1"
    assert span.attributes["scil.latency_ms"] == 42


def test_scil_cache_span_distinguishes_deterministic_route(span_exporter):
    _emit_scil_cache_span("deterministic", agent_name="my_agent", session_id="sess-1", latency_ms=3)

    span = span_exporter.get_finished_spans()[0]
    assert span.attributes["scil.route"] == "deterministic"


async def test_playground_template_match_emits_scil_cache_span_with_zero_llm_calls(
    client, unique_name, span_exporter
):
    """The SCIL template short-circuit (see README's "^ping$" -> "pong"
    example) matches before any model call — this exercises the real
    playground endpoint end-to-end with zero LLM calls (no API quota
    needed) and confirms the span this task added actually fires from the
    real request path, not just when called directly."""
    agent_resp = await client.post(
        "/api/agents",
        json={
            "name": unique_name("scil_span_template_agent"),
            "base_instruction": "You are a helpful assistant.",
            "model_config": {
                "scil": {
                    "enabled": True,
                    "templates_enabled": True,
                    "templates": [{"pattern": "^ping$", "response_text": "pong"}],
                }
            },
        },
    )
    agent = agent_resp.json()

    resp = await client.post("/api/playground/run", json={"agent_id": agent["id"], "message": "ping"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["response_text"] == "pong"

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "scil.cache"]
    assert len(spans) == 1
    assert spans[0].attributes["scil.route"] == "deterministic"
    assert spans[0].attributes["agent.name"] == agent["name"]
