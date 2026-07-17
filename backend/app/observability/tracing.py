"""OpenTelemetry wiring for the Debug Console (see app/debug_api).

Deliberately vendor-neutral: this exports spans over OTLP/gRPC, so it plugs
into whatever trace backend already exists in the surrounding infra — Jaeger,
Grafana Tempo, Langfuse (via its OTel endpoint), Honeycomb, Datadog, or a
managed collector — by pointing `otel_exporter_otlp_endpoint` at it. Nothing
here is Jaeger-specific except the optional Debug Console query integration
in app/debug_api/router.py, which is a bonus convenience, not a requirement:
the spans themselves are captured/exported correctly either way.

Off by default (`otel_enabled=False`) so a fresh dev checkout without a
tracing backend running doesn't get noisy connection-refused retries in the
logs. `docker-compose.yml` in the repo root brings up a local
Jaeger-all-in-one (OTLP receiver on :4317, UI+Query API on :16686) in one
command for anyone who wants the full experience.
"""

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from app.config import get_settings

logger = logging.getLogger(__name__)

_tracer: Tracer = trace.get_tracer("agent-forge.noop")


def get_tracer() -> Tracer:
    """Always safe to call and use, even when tracing is disabled — the
    no-op tracer returned by `opentelemetry.trace.get_tracer` before any
    TracerProvider is installed produces spans that are cheap no-ops with
    the exact same API surface, so call sites never need an `if enabled`
    branch of their own."""
    return _tracer


def setup_tracing(app: FastAPI) -> None:
    global _tracer
    settings = get_settings()
    if not settings.otel_enabled:
        logger.info("OpenTelemetry tracing disabled (OTEL_ENABLED=false)")
        return

    provider = TracerProvider(resource=Resource.create({"service.name": settings.otel_service_name}))
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("agent-forge")

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    logger.info("OpenTelemetry tracing enabled -> %s", settings.otel_exporter_otlp_endpoint)
