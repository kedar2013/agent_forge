"""Per-request, in-process-memory-only "bring your own key" credentials for
the two model providers this platform supports (Gemini, Claude via ADK's
LiteLlm adapter). Deliberately NOT built on the same pattern as
chat_api._identity_state_delta / playground_api._current_date_state — those
are re-asserted into ADK session state every turn, which for /chat is
Postgres-persisted (DatabaseSessionService). Exactly right for identity/date
(trusted, not secret). Exactly wrong for an API key: it would write the
visitor's key into agent_forge.sessions/agent_forge.events on every message.

Instead: HTTP header in -> contextvars.ContextVar for the request's duration
-> read by the model classes at call time -> written nowhere. ContextVar,
not os.environ: os.environ is process-global and would race across
concurrent requests from different users; a ContextVar is isolated per
asyncio Task, and every inbound ASGI request runs as its own Task.

Two different fixes for the two provider paths, because ADK treats them
differently (see class docstrings below for the specifics):
  - Gemini: a fresh `Gemini` instance is reconstructed on EVERY LLM call
    (LlmAgent.canonical_model -> LLMRegistry.new_llm for a bare model
    string), so registering a ContextualGemini subclass is enough — no
    change needed to agent_runtime/builder.py's caching for this path.
  - Claude/LiteLlm: the SAME LiteLlm instance is baked into the cached
    agent tree at build time and shared by every concurrent user of that
    agent — a fresh-per-call approach doesn't apply. Fix: override the
    LiteLLMClient it delegates to instead (a stateless passthrough with no
    shared instance state to race on).
"""

import contextvars
from contextlib import contextmanager
from functools import cached_property
from typing import Any, Iterator, Literal

from fastapi import HTTPException
from google.adk.models.google_llm import Gemini
from google.adk.models.lite_llm import LiteLLMClient, LiteLlm
from google.adk.models.registry import LLMRegistry
from google.genai import Client, types

Provider = Literal["gemini", "anthropic"]

_PROVIDER_LABEL: dict[Provider, str] = {"gemini": "Gemini (Google)", "anthropic": "Claude (Anthropic)"}

gemini_api_key_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("gemini_api_key", default=None)
anthropic_api_key_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("anthropic_api_key", default=None)


@contextmanager
def use_api_keys(gemini_key: str | None, anthropic_key: str | None) -> Iterator[None]:
    """Scopes both ContextVars to exactly the block that actually drives the
    ADK Runner. MUST wrap the code that iterates the run, not just the
    synchronous part of a request handler — chat_api.send_chat_message_stream
    in particular returns a StreamingResponse whose generator body is driven
    by Starlette AFTER the endpoint function has already returned; wrapping
    only the `return StreamingResponse(...)` line would reset these before a
    single token is generated. Wrap the `async for event in _stream_turn(...)`
    loop inside that generator instead."""
    g_token = gemini_api_key_ctx.set(gemini_key)
    a_token = anthropic_api_key_ctx.set(anthropic_key)
    try:
        yield
    finally:
        gemini_api_key_ctx.reset(g_token)
        anthropic_api_key_ctx.reset(a_token)


def required_providers(adk_agent: Any) -> set[Provider]:
    """Walks root + every sub_agent recursively; returns every provider that
    agent tree can reach, so a multi-specialist router demands all needed
    keys up front (on the first message) rather than surprising the user
    mid-conversation after an internal transfer to a differently-provider'd
    specialist."""
    providers: set[Provider] = set()
    seen: set[int] = set()

    def walk(agent: Any) -> None:
        if id(agent) in seen:
            return
        seen.add(id(agent))
        if isinstance(agent.model, LiteLlm):
            providers.add("anthropic")
        elif isinstance(agent.model, str) and agent.model:
            providers.add("gemini")
        for sub in agent.sub_agents or []:
            walk(sub)

    walk(adk_agent)
    return providers


class MissingApiKeyError(HTTPException):
    """`detail` is a dict, not FastAPI's usual plain string — the frontend
    needs `provider` to know which key to prompt the visitor for (see
    frontend/src/api/chat.ts's parseError and MissingApiKeyError)."""

    def __init__(self, provider: Provider) -> None:
        super().__init__(
            status_code=400,
            detail={
                "error": "missing_api_key",
                "provider": provider,
                "message": (
                    f"This bot uses {_PROVIDER_LABEL[provider]}. "
                    f"Add your {_PROVIDER_LABEL[provider]} API key to continue."
                ),
            },
        )


def resolve_request_api_keys(
    required: set[Provider],
    user_gemini_key: str | None,
    user_anthropic_key: str | None,
    *,
    allow_operator_fallback: bool,
) -> tuple[str | None, str | None]:
    """The one place that decides whether the operator's own .env key may be
    used as a fallback.

    allow_operator_fallback=False for real end-user chat (/chat/message,
    /chat/message/stream) — per product decision, public traffic must never
    silently spend the operator's own quota.

    allow_operator_fallback=True for Playground (/playground/run) and
    /invoke — both are require_role("admin"/"developer")-gated internal
    tooling, not public traffic, so falling back to the operator's key there
    is the right default (lets a developer iterate on a Claude-model agent
    without needing their own Anthropic key on hand). A caller who supplies
    their own key anyway still takes priority over the operator fallback —
    the header mechanism works identically either way.
    """
    from app.config import get_settings

    settings = get_settings() if allow_operator_fallback else None
    gemini_key = user_gemini_key or (settings.gemini_api_key if settings else None)
    anthropic_key = user_anthropic_key or ((settings.anthropic_api_key or None) if settings else None)
    if "gemini" in required and not gemini_key:
        raise MissingApiKeyError("gemini")
    if "anthropic" in required and not anthropic_key:
        raise MissingApiKeyError("anthropic")
    return gemini_key, anthropic_key


class ContextualGemini(Gemini):
    """Mirrors google.adk.models.google_llm.Gemini.api_client construction
    exactly (verified against the installed 2.4.0 source), except api_key
    comes from gemini_api_key_ctx instead of being left for
    google.genai.Client() to read GOOGLE_API_KEY/GEMINI_API_KEY from the
    process environment. Gemini's own docstring documents subclassing +
    overriding this exact property as the supported customization point.

    @cached_property is safe here (matching the base class's own choice,
    including its own noted asyncio-lock caveat for long-lived shared
    instances) because a FRESH instance of this class is constructed on
    every single LLM call — LlmAgent.canonical_model calls
    LLMRegistry.new_llm(self.model) fresh each time for a bare model string,
    it's never reused across calls or across users."""

    @cached_property
    def api_client(self) -> Client:
        base_url, api_version = self._base_url_and_api_version
        kwargs_for_http_options: dict[str, Any] = {
            "headers": self._tracking_headers(),
            "retry_options": self.retry_options,
            "base_url": base_url,
        }
        if api_version:
            kwargs_for_http_options["api_version"] = api_version

        kwargs: dict[str, Any] = {"http_options": types.HttpOptions(**kwargs_for_http_options)}
        if self.model.startswith("projects/"):
            kwargs["enterprise"] = True
        if self.client_kwargs:
            kwargs.update(self.client_kwargs)
        kwargs["api_key"] = gemini_api_key_ctx.get()

        return Client(**kwargs)


class ContextAwareLiteLLMClient(LiteLLMClient):
    """LiteLlm.generate_content_async's only call site — both its streaming
    and non-streaming branches — is `await self.llm_client.acompletion(...)`
    (verified against the installed 2.4.0 source; the sibling sync
    `completion()` method on LiteLLMClient exists but is never called by
    generate_content_async, so it doesn't need overriding here). Overriding
    just this one stateless passthrough method is simpler and safer than
    overriding generate_content_async itself, which would mean
    reimplementing its full streaming-aggregation logic — and it's a real
    fix (not a race) because LiteLLMClient itself holds no per-call state to
    collide on: completion_args is a fresh local dict built by
    generate_content_async on every call, and it's THAT dict this method
    receives as **kwargs."""

    async def acompletion(self, model: str, messages: list, tools: list, **kwargs: Any):
        api_key = anthropic_api_key_ctx.get()
        if api_key:
            kwargs["api_key"] = api_key
        return await super().acompletion(model, messages, tools, **kwargs)


def register() -> None:
    """Call once at startup (app/main.py), NOT lazily — LLMRegistry.resolve()
    is @lru_cache'd; registering after the first request would leave
    already-resolved model strings pointing at the stock Gemini class
    forever for that process's lifetime."""
    LLMRegistry.register(ContextualGemini)
