import os
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    db_schema: str = "agent_forge"

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg_driver(cls, v: str) -> str:
        """Managed-Postgres hosts (Railway, Heroku, ...) hand out
        "postgres://"/"postgresql://" with no driver, which SQLAlchemy
        resolves to the sync psycopg2 dialect — not installed here since
        app/db.py's create_async_engine needs an async driver. Rewrite to
        asyncpg so those hosts' connection strings work unmodified."""
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v

    gemini_api_key: str
    # gemini-2.5-flash 404s on new API keys/projects ("no longer available to
    # new users") even though it's still nominally a stable model for older
    # ones -- gemini-3.5-flash is the current default new keys actually get.
    gemini_model: str = "gemini-3.5-flash"

    # Optional — only needed if an agent's model_config.model is set to one of
    # the "anthropic/claude-..." options in the Agent Builder's model
    # dropdown. Left blank, Claude-model agents fail at build time with a
    # clear litellm auth error rather than the backend refusing to boot.
    anthropic_api_key: str = ""

    embedding_provider: str = "local"
    embedding_dim: int = 384

    agent_forge_api_token: str
    user_token_secret: str = "dev-only-insecure-secret-change-me"

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    env: str = "development"

    # Used only when an admin explicitly calls POST /api/data-retention/purge
    # (see app/retention.py) — never automatic, there's no scheduler in this
    # app that would run it on a timer. 90 days is a conventional default for
    # this kind of "how long do we keep raw conversation/PII data" policy;
    # override per your own retention policy.
    data_retention_days: int = 90

    # --- Debugging / distributed tracing -----------------------------------
    # Off by default so a fresh dev checkout doesn't need Jaeger running just
    # to boot the backend. The Debug Console (GET /debug/traces/*) works even
    # with this off — it reconstructs a waterfall from invocation_log/
    # tool_call_log directly — but you lose real span-level timing and the
    # "Open in Jaeger" deep link. See docker-compose.yml for a one-command
    # local Jaeger, or point otel_exporter_otlp_endpoint at any OTLP-
    # compatible backend (Jaeger, Tempo, Langfuse, Honeycomb, Datadog, ...).
    otel_enabled: bool = False
    otel_service_name: str = "agent-forge-backend"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    jaeger_query_url: str = "http://localhost:16686"

    # --- Guardrails (see app/guardrails/) -----------------------------------
    # Platform-wide default for every agent that doesn't set its own
    # model_config.guardrails.enabled — unlike otel/durable_execution/SCIL,
    # this defaults ON: guardrails are an operator-owned safety control, not
    # a per-agent opt-in feature. Set false for local dev if you don't want
    # the deterministic checks running on every playground turn.
    guardrails_enabled: bool = True
    # Master switch for the LLM-judge-based checks (jailbreak/topical-scope
    # judges) — separate from guardrails_enabled, and OFF by default, unlike
    # it: those deterministic regex checks (injection heuristics, PII, MNPI)
    # are free and always run as the safety floor, but a judge check costs a
    # real extra model call on every single agent turn (every hop, for a
    # multi-specialist turn) — silently defaulting that on would double
    # every already-published agent's LLM spend the moment this ships, the
    # same reason SCIL's hallucination_groundedness_check/durable_execution/
    # planning are all opt-in elsewhere in this codebase. An operator (or an
    # individual agent, via model_config.guardrails.input.topical_scope_check)
    # opts in deliberately once they've budgeted for it.
    guardrails_judge_enabled: bool = False
    # Comma-separated platform-wide confidential/MNPI term list, merged with
    # (not replaced by) each agent's own model_config.guardrails.output.
    # mnpi_terms. Empty by default — an operator fills this in per their own
    # compliance list; ships empty rather than with a guessed example list
    # that would give a false sense of coverage.
    guardrails_mnpi_terms_raw: str = ""

    @field_validator("guardrails_mnpi_terms_raw")
    @classmethod
    def _strip_mnpi_terms(cls, v: str) -> str:
        return v.strip()

    @property
    def guardrails_mnpi_terms(self) -> list[str]:
        return [t.strip() for t in self.guardrails_mnpi_terms_raw.split(",") if t.strip()]

    # --- Policy-as-code / OPA (see app/tool_registry/opa_client.py) --------
    # Off by default, same "fresh checkout doesn't need extra infra" reasoning
    # as otel_enabled — the existing in-process policy_engine.apply_policy
    # stays every AccessPolicy's engine unless it explicitly opts in via
    # resolver_config["engine"] = "opa" (see backend/policies/*.rego for a
    # worked example, and scripts/migrate_policy_to_opa.py to switch a named
    # policy over once a real OPA is reachable). `docker compose up -d opa`
    # brings up a local one loaded with backend/policies/ in one command.
    opa_enabled: bool = False
    opa_url: str = "http://localhost:8181"
    opa_timeout_seconds: float = 2.0
    # An OPA-engine policy is still an access-control decision -- unlike a
    # judge-based guardrail check (where failing open protects a real user
    # from a broken judge), failing OPEN here means letting a request
    # through UNFILTERED. Defaults fail-CLOSED (deny) for that reason; an
    # operator who'd rather degrade to "let it through" during an OPA
    # outage can opt into that explicitly and it's logged loudly either way
    # (see opa_client.evaluate_opa_policy).
    opa_fail_closed: bool = True

    # --- Tool sandboxing / egress control (see app/tool_registry/egress.py) -
    # Comma-separated platform-wide hostname allowlist for http_tool's
    # outbound calls (a leading "." means "this domain or any subdomain",
    # e.g. ".example.com" matches both example.com and api.example.com).
    # Empty (the default) means unrestricted — every http_tool call site
    # already existed before this, so this ships as a pure opt-in an
    # operator turns on once they've enumerated what SHOULD be reachable,
    # not a default that would break every existing tool config. A tool's
    # own `config.egress_allowlist` (see http_tool.py) overrides this list
    # entirely for that one tool rather than being merged with it — a
    # tool-specific allowlist is a deliberate, tighter scope, not an
    # addition to the platform default.
    tool_egress_allowlist_raw: str = ""

    @property
    def tool_egress_allowlist(self) -> list[str]:
        return [h.strip().lower() for h in self.tool_egress_allowlist_raw.split(",") if h.strip()]

    # --- Multi-tenancy: rate limiting + per-workspace config -----------------
    # "memory" (default): app/rate_limit_backends.InMemoryBackend, exactly
    # today's per-process behavior — a fresh checkout needs nothing extra.
    # "redis": RedisBackend, for a multi-instance deployment where every
    # process must enforce the SAME budget against shared state (an
    # in-memory backend would silently give every instance its own
    # allowance, which is wrong the moment there's more than one). Requires
    # `redis_url` and the `redis` package installed.
    rate_limit_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    # Platform-wide default aggregate budget across every principal in one
    # workspace (catches "this whole tenant is unusually busy", distinct
    # from rate_limit_principal's per-user budget which catches one abusive
    # caller within a tenant) — a specific workspace's own
    # WorkspaceConfig.max_requests_per_minute (see app/models/workspaces.py),
    # if set, overrides this default for just that workspace.
    workspace_max_requests_per_minute: int = 200

    # --- Temporal-backed durable workflows (see app/durable_workflow/) -----
    # A SEPARATE, heavier-weight durable-execution spine from
    # app.reliability.durable_execution_config's existing one: that one
    # resumes a single crashed CHAT TURN via ADK's own resumability +
    # Postgres checkpoints (see the "Durable Execution & Reliability"
    # README section) — this one is for a genuinely long-running,
    # multi-step BUSINESS PROCESS with real side effects (the saga/
    # compensation worked example, reservation_demo_tool, ported to a real
    # Temporal workflow in app/durable_workflow/workflows.py) that needs to
    # survive a WORKER process crash, not just resume one ADK invocation.
    # Off by default -- requires `pip install -e ".[temporal]"` (a separate
    # extra, not a main dependency, since the temporalio package itself is
    # a heavy binary wheel) AND a real Temporal server reachable at
    # `temporal_target` (`docker compose up -d temporal` for a local one).
    temporal_enabled: bool = False
    temporal_target: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "agent-forge-reliability"

    @model_validator(mode="after")
    def _fail_fast_on_weak_config_outside_dev(self) -> "Settings":
        """`env` defaults to "development", so a fresh local checkout is
        never touched by this — these checks only fire once ENV is
        explicitly set to something else (staging/production/...). That's
        the deliberate split: local stays exactly as permissive as before,
        any "higher" environment refuses to boot rather than silently
        serving traffic with a dev-grade secret. Checked here (not
        documented only in a deploy checklist) so it's enforced by the code
        itself, not by whoever remembers to read the checklist."""
        if self.env == "development":
            return self

        problems: list[str] = []

        if self.user_token_secret == "dev-only-insecure-secret-change-me":
            problems.append(
                "USER_TOKEN_SECRET is still the insecure default — set a real "
                "secret, e.g. `python -c \"import secrets; print(secrets.token_urlsafe(32))\"`."
            )
        elif len(self.user_token_secret) < 32:
            problems.append("USER_TOKEN_SECRET is too short for a non-development environment (need >= 32 chars).")

        if len(self.agent_forge_api_token) < 32:
            problems.append("AGENT_FORGE_API_TOKEN is too short for a non-development environment (need >= 32 chars).")

        localhost_origins = sorted(o for o in self.cors_origins if "localhost" in o or "127.0.0.1" in o)
        if localhost_origins:
            problems.append(
                f"CORS_ORIGINS still includes localhost/127.0.0.1 origin(s) ({', '.join(localhost_origins)}) "
                "in a non-development environment — set it to the real frontend origin(s)."
            )

        if problems:
            raise ValueError(
                f"Refusing to start with ENV={self.env!r} and an insecure configuration:\n- "
                + "\n- ".join(problems)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # google-genai (used internally by google-adk) reads its API key from
    # GOOGLE_API_KEY; we keep GEMINI_API_KEY as the .env name for clarity
    # and consistency with the sibling StudyBuddy project, then bridge it here.
    os.environ.setdefault("GOOGLE_API_KEY", settings.gemini_api_key)
    # Same bridge for Claude: litellm's Anthropic provider (used by ADK's
    # LiteLlm wrapper — see agent_runtime/builder.py) and the anthropic SDK
    # itself (see scil/hallucination.py) both read ANTHROPIC_API_KEY from the
    # environment. Guarded on truthy so an unset/blank key doesn't shadow a
    # real ANTHROPIC_API_KEY already exported in the process environment.
    if settings.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
    # pydantic-settings loads .env into this Settings object only — it never
    # touches os.environ. sql_tool/retrieval_tool configs reference a
    # connection by *env var name* (e.g. "DATABASE_URL") so the tool row
    # itself never stores a real DSN, so that lookup needs the var to
    # actually exist in the process environment.
    os.environ.setdefault("DATABASE_URL", settings.database_url)
    return settings
