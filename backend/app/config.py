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
