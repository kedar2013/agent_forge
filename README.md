
# Agent Forge

UI-driven platform for composing, testing, and publishing Google ADK agents
from Postgres-backed configuration — no code required to wire up a tool,
attach a skill, or route between sub-agents.

## Status

**Backend and frontend are both built and working.** Built per
`C:\Users\Kedar\.claude\plans\swift-hatching-acorn.md` and extended since:

- Postgres schema (`agent_forge` schema inside the existing `studybuddy` DB),
  with workspaces, four user roles (`admin`/`viewer`/`chat_user`/`developer`),
  and a hash-chained config audit log
- A `developer` role: self-registers (admin-approved, like `chat_user`),
  builds/tests agents and sub-agents in the same Agent Builder + Playground
  as admin, gets chat access — but every agent they PUBLISH goes into an
  admin approval queue (`/agents/publish-requests`) instead of going live
  immediately. See `technical design document.txt` section 17 for the full
  role/permission matrix and publish-approval flow.
- A **Debug Console** (`/debug/traces`) for tracing multi-agent workflows:
  every playground/invoke/chat turn is captured as a waterfall (root
  invocation span + one child span per tool call, attributed to whichever
  specialist actually made it) — works standalone from Postgres, or against
  a real OpenTelemetry trace backend (Jaeger by default, or any OTLP
  endpoint — Tempo, Langfuse, Honeycomb, Datadog, ...) when `OTEL_ENABLED=true`.
  `docker compose up -d jaeger` brings up a local one in one command. See
  section 18 of the technical design document.
- `config_api` — CRUD for tools/skills/agents, attach/detach endpoints,
  circular sub-agent detection, publish + versioning
- `tool_registry` — `http_tool`, `sql_tool`, `mcp_tool`, `image_gen_tool`,
  and NL2SQL tools fully working; `retrieval_tool` implemented and used by
  the StudyBuddy import (pgvector-backed knowledge base search)
- `agent_runtime` — builds real `google.adk.agents.Agent` objects from
  config, with an in-memory cache invalidated on publish
- `playground_api` — runs a draft or published agent against a real Gemini
  call via ADK's `Runner`, returns the response + full tool-call trace
- `invocation_log` / `tool_call_log` / `config_audit_log` tables + write
  hooks are in place (fire-and-forget for invocations, synchronous for
  config audit)
- A React + TypeScript + Tailwind admin UI (`frontend/`) covering agent
  building, tool/skill libraries, a chat playground, monitoring/usage/audit
  dashboards, and user management, plus a separate white-labeled end-user
  chat surface (`/chat`)
- **Row-level security, generically**: `access_policies` resolves a logged-in
  user's persona (keyed by their Agent Forge account or by a corporate SOEID —
  `users.soeid`, admin-assignable on `/users`) and mechanically enforces a
  scope predicate on every query, regardless of what an LLM-generated query
  says. See "Capability library" below for the data-access tools that
  consume it, and `/onboarding/new-domain` for the UI wizard that composes
  a new domain (connection → access policy → data entity → tools → agent →
  publish) without writing SQL or Python.

### Capability library — generic pieces meant to be reused across domains

| Capability | Implementation | Generic or domain-bound | Used by |
|---|---|---|---|
| Query any table/collection, LLM writes the SQL | `data_query_tool` (`backend/app/tool_registry/data_query_tool.py`) — validates via a real `sqlglot` AST, AST-injects the access policy's predicate | **Generic** — schema + scope come from a `data_entities` row, not code | `credit_facility_analyst` (`query_companies`, `query_facility_data`) |
| Row-level access control | `access_policies` + `app/tool_registry/policy_engine.py` | **Generic** — persona rules are JSON config, not code | Any `data_query_tool`/`mysql_query_tool`/`mongo_query_tool` that sets `policy_id` |
| Data dictionary (columns, labels, format) | `data_entities` (`backend/app/models/data_entities.py`), with MySQL/Mongo introspection | **Generic** | `data_query_tool` instances |
| Chart image | `generate_chart_tool` (`mcp_servers/chart_server.py`) | **Generic** — arbitrary series in, PNG out | 5 market-intelligence specialists, `reporting_specialist` |
| Chart-type selection + slide outline | `chart_planner_tool` (`mcp_servers/slide_reporting_server.py`) | **Generic** — pure pandas shape classification on `{columns, data}` | `slide_reporting_agent`, `reporting_specialist` |
| PPTX rendering | `slide_builder_tool` (same file) | **Generic** | `slide_reporting_agent`, `reporting_specialist` |
| PDF / Excel export | `export_to_pdf`, `export_to_excel` (`mcp_servers/document_export_server.py`) | **Generic** | `reporting_specialist` |
| NL→SQL against one fixed schema | `nl_to_sql_tool`, `sql_execution_tool` (`mcp_servers/slide_reporting_server.py`) | **Domain-bound** to `sales_analytics` — superseded by `data_query_tool` for new domains, kept as-is for `slide_reporting_agent`'s existing behavior | `slide_reporting_agent` only |

`reporting_specialist` (`backend/scripts/seed_reporting_specialist.py`) is
the concrete proof this is reusable, not aspirational: the same published
agent — chart + slide + export tools, zero domain knowledge — is attached
as a sub-agent to both `market_intelligence_orchestrator` (finance) and
`credit_facility_analyst` (credit risk), and independently pulls its own
data via `credit_facility_analyst`'s own `data_query_tool` rows when
attached there.

**Orchestrator naming**: a published agent with sub-agents attached is an
*orchestrator* and is named `..._orchestrator` (`market_intelligence_orchestrator`,
`studybuddy_orchestrator`); a published agent with no sub-agents is a
*specialist* and is named for what it does (`credit_facility_analyst`,
`reporting_specialist`). `backend/scripts/rename_agent.py <old> <new>`
renames any agent and republishes it so the ADK build tree actually picks
up the new name.

### Market Intelligence agent family

A ready-to-use example of onboarding a new domain: three specialist agents
plus a routing orchestrator, all backed by free/no-API-key public data
sources, following the same MCP-server pattern as the existing weather and
mutual-fund tools:

| Agent | Domain | Data source |
|---|---|---|
| `stock_market_analyst` | Stocks, ETFs, indices — quotes, trailing returns | Yahoo Finance (unauthenticated `chart`/`search` endpoints) |
| `crypto_analyst` | Cryptocurrency prices, trends, trending coins | CoinGecko free API |
| `forex_metals_analyst` | Currency exchange rates/conversion, precious metals spot prices | frankfurter.app + gold-api.com |

Routed via `agent_forge_orchestrator` — see "Single orchestrator" below;
this family no longer has its own dedicated orchestrator.

MCP servers live in `backend/mcp_servers/{stocks,crypto,forex_metals}_server.py`.
Seed (or reseed) the agent family with:

```bash
cd backend
python scripts/seed_market_agents.py [--reset]
python scripts/seed_reporting_specialist.py [--reset]   # generic chart/slide/export specialist
```

### Domain onboarding wizard (`/onboarding/new-domain`)

Guided, end-to-end text-to-SQL domain onboarding: pick a connection
(discovered live from the backend's `.env` — `GET /data-entities/connections`),
test it, pick a table (listed live with row counts), and the columns are
introspected, labelled, and pre-tagged (search/filter/measure/format
heuristics from column types and names) with the primary key auto-detected.
One click creates all `data_query_tool`s, the agent name/instruction are
pre-filled, and publish is gated behind a **smoke test that requires at
least one real tool call** — an agent that "answers" without querying the
database is hallucinating, and the wizard refuses to publish it. Every
field carries an intelligent guide (ⓘ + a focus-following Guide rail):
what the value is, what it becomes downstream, live examples from your own
data, and the mistake to avoid. `sales_analytics_analyst` was onboarded
entirely through this wizard as the worked example.

### Credit Facility Analysis — worked example of onboarding via the generic RLS framework

A banking/credit-risk domain built entirely on the generic pieces above —
`access_policies` + `data_entities` + `data_query_tool` — rather than any
domain-specific code. Row-level access varies by persona (GCM: global,
GSG: no L2 visibility, Non-GSG: assigned-companies-only, CCB: exact-`gfcid`
reference only), resolved from either the user's Agent Forge account or their
SOEID. See `backend/app/domains/credit_facility/` for the data model and
seed scripts, or build an equivalent domain yourself with zero code via
`/onboarding/new-domain` in the admin UI.

```bash
cd backend
python -m app.domains.credit_facility.seed_data   [--reset]  # MySQL demo data + 8 demo logins
python -m app.domains.credit_facility.seed_agent  [--reset]  # access policies, data entities, tools, agent
```

### Revenue and Returns Analysis — second worked example, no RLS this time

A second domain on the same generic pieces (`data_entities` + `data_query_tool`,
no `access_policies` — every user sees all data), proving the pattern isn't
one-off: a 3-level product hierarchy (business unit → category → product)
plus 6 months of gross/net revenue, returns, refunds, and return-rate data
per product. `revenue_returns_analyst` answers questions like "what's the
return rate for Wireless Earbuds Pro over the last 3 months?" by writing
its own SQL against the tool-described schema, same as credit_facility.
See `backend/app/domains/revenue_and_returns/` for the data model, seed
scripts, and `REVENUE_AND_RETURNS_ONBOARDING.txt` (repo root) for the full
onboarding walkthrough this domain was built from.

```bash
cd backend
python -m app.domains.revenue_and_returns.seed_data   [--reset]  # MySQL demo data (no RLS/demo logins)
python -m app.domains.revenue_and_returns.seed_agent  [--reset]  # data entities, tools, agent
```

### SCIL — Self-Correcting Intelligence Layer

Full technical documentation (architecture, dashboard, schema, safety
design, config reference, measured benefits): `SCIL_technical_document.md`
in the repo root.

Cuts LLM token consumption and call volume by caching validated answers and
auto-correcting validation failures, per-agent and off by default. Three
cooperating pieces (all in `backend/app/scil/`, wrapped around
`playground_api`'s `_run_turn`/`_stream_turn`, which every agent entry point
— playground, `/invoke`, chat blocking + streaming — funnels through):

- **Semantic response cache** (`scil_semantic_cache`, pgvector): repeat or
  near-duplicate requests (exact sha256 match, else cosine similarity ≥
  `cache_similarity_threshold`, default 0.80) return the cached validated
  answer with **zero LLM calls**. Embeddings reuse the same 384-dim MiniLM
  model as the RAG retrieval tool (`app/embeddings.py`) — one embedding
  provider platform-wide.
- **Deterministic validators + self-correction loop** (`validators.py`,
  `corrector.py`): configured validators (`sql` — sqlglot AST, read-only
  single-SELECT guardrails; `json_schema` — the agent's own declared
  `output_schema`) check each successful turn. On failure, the SAME model is
  retried (up to `max_retries`, default 2) with structured error feedback —
  including a known-good fix from correction memory when one exists for the
  same error class on a similar input. Recovered turns write an
  `(input, mistake, fix)` pair to `scil_correction_memory`; answers that
  never validate are returned to the user but **never cached**. Error
  signatures: `SQL:Syntax`, `SQL:NotSingleSelect`, `SQL:GuardrailViolation`,
  `JSON:ParseError`, `JSON:SchemaMismatch`.
- **Correction-exemplar injection** (`exemplars.py`): before an agent's
  FIRST attempt, its top-k most-similar past corrections (cosine ≥ 0.85)
  are prepended to the outbound prompt as a compact budget-capped few-shot
  block — known mistakes get avoided up front instead of only recovered
  from. Only the prompt changes; transcript/cache keep the original message.
- **Template-based deterministic routing** (`templates.py`): per-agent
  regex/slot templates in `model_config.scil.templates` answer matching
  requests with **zero LLM calls** (route = `deterministic`). Fullmatch
  against the normalized message only — a template never fires on a
  substring of a longer question.
- **Metrics + admin surface**: every turn writes one `scil_metrics` row
  (route = `disabled` / `deterministic` / `cache_hit` / `llm` /
  `llm_retry`). The **SCIL Dashboard** (`/scil`, admin-only) shows LLM
  calls avoided, cache hit rate, retry success rate, route distribution,
  savings over time, and curation tables (delete/purge cache entries,
  delete corrections). API: `/api/scil/metrics/{summary,timeseries}`,
  `/api/scil/cache/entries`, `/api/scil/cache/purge`,
  `/api/scil/corrections`.

Enable per agent via `model_config` (absent/false = exact pre-SCIL behavior):

```json
"scil": { "enabled": true, "cache_similarity_threshold": 0.80,
          "cache_ttl_hours": 24, "max_retries": 2, "validators": ["sql"],
          "templates_enabled": true,
          "templates": [{"pattern": "^ping$", "response_text": "pong"}] }
```

`python scripts/enable_scil.py [--disable]` enables caching on the real
agents where it's safe, with domain-appropriate TTLs (market family 1h,
funds/company 24h, translator/example 168h). RLS domains use
`"cache_scope": "user"` — each cached answer is keyed by
(agent, **user**, question), so `credit_facility_analyst`'s per-persona
answers never leak across users (verified live: the same question from a
different user_id is a cache miss). A turn with any FAILED tool call is
never cached, so an "I encountered an error" apology can't become a cache
hit. **Deliberately NOT enabled** on the StudyBuddy family
(session-state-scoped retrieval that even the user dimension doesn't fully
carry; quiz/flashcard output is also supposed to vary between runs).

Not yet built (SCIL spec remainder): escalation-tier routing to a bigger
model and HITL escalation.

**Deferred to future sessions:** real OpenTelemetry export + Langfuse,
versioning diff/rollback UI, per-agent rate limiting beyond what's already
enforced, multi-tenancy hardening beyond the default workspace, live
retrieval/pgvector testing outside the StudyBuddy import, and market-news
sentiment agents (no reliable free/no-key news API was available).

### Durable Execution & Reliability

Checkpointing/resume-after-crash, idempotent tool-call replay, circuit
breakers, and saga/compensation — per-agent and off by default, mirroring
SCIL's `model_config.scil` opt-in shape exactly. Complements SCIL: SCIL
corrects wrong model *content*; this handles infrastructure failures
(process crashes, flaky downstream calls, partially-completed multi-step
turns). Builds on a real ADK 2.4.0 primitive
(`google.adk.apps.app.ResumabilityConfig`, `@experimental`) rather than a
hand-rolled checkpoint engine — the Postgres-native pieces here exist
specifically to close what ADK's own resumability contract leaves open
("tool call to resume needs to be idempotent because we only guarantee
at-least-once behavior once resumed") and to make a crashed turn
*discoverable and durably recorded*, not just theoretically resumable:

- **Eager, incremental checkpointing** (`app/logging_hooks.start_durable_run`/
  `set_durable_attempt`): for opted-in agents on a DB-backed session
  (`/agents/{id}/invoke`, `/chat/message` — never Playground, whose
  `InMemorySessionService` has nothing to resume, and never the streaming
  `/chat/message/stream`, which already has its own "simpler, no retry
  layer" precedent), `invocation_log` gets a `status='running'` row
  *before* the turn's first `runner.run_async()` call, not after the whole
  turn finishes — a crash mid-turn leaves a resumable trace instead of no
  row at all.
- **Durable, idempotent tool calls** (`app/agent_runtime/builder.py`'s
  `before_tool_callback`/`after_tool_callback`): each tool call's result is
  written to `tool_call_log` synchronously (awaited, not fire-and-forget)
  the moment it completes, keyed by an idempotency key ADK itself assigns
  (`invocation_id:function_call_id`). A resume that re-attempts the one
  call ADK only guarantees at-least-once for finds that key already
  recorded a success and replays the cached output instead of re-executing.
- **Explicit resume** (`POST /api/reliability/runs/{id}/resume`, admin-only):
  loads the stuck `running` row, rebuilds the agent, and calls
  `runner.run_async(invocation_id=..., new_message=None)` against the same
  ADK session — ADK's own resumability continues from the last persisted
  event. Deliberately explicit, not automatic/silent-on-next-message.
- **Circuit breaker + retry/backoff** (`app/reliability/circuit_breaker.py`,
  `resilient_call.py`): in-memory, per-tool, same single-instance caveat as
  `app/rate_limit.py` (a breaker resetting on redeploy is correct, not a
  gap). Wraps every tool-registry call site that had zero timeout/retry
  protection (`http_tool`, `sql_tool`, `mysql_tool`, `mongo_tool`,
  `nl2sql_tool`, `retrieval_tool`) — generalizes the retry-with-backoff
  pattern already proven in `mcp_servers/_http_retry.py`.
- **Saga/compensation** (`app/reliability/compensation.py`): on a turn
  ending in error, walks that turn's already-succeeded tool calls in
  reverse order and invokes any configured `compensation_tool_id` (a plain
  `tools.config` key, same convention as `context_params`/`policy_id`).
  Worked example proving it actually fires, not just structurally wired up:
  `reliability_demo_agent` (`scripts/seed_reliability_demo.py`) reserves
  demo inventory, then a deliberately-fragile "confirm" step — a failed
  confirmation automatically releases the reservation.

Enable per agent via `model_config`:

```json
"durable_execution": { "enabled": true }
```

**Known limitation, found during live verification, not yet fixed:** compensation
triggers on `outcome.status == "error"` (a technical/infrastructure
failure) — a turn where the model gracefully narrates a failed step as a
recovered "success" (no raised exception) does NOT trigger compensation,
even though the underlying saga didn't actually complete. Same class of
problem SCIL's hallucination validator exists for; solving it here would
need a saga-completion check independent of turn status, not just a bigger
compensation walk.

### Single orchestrator & Planner/ReAct

Every orchestrator-shaped agent (`market_intelligence_orchestrator`,
`studybuddy_orchestrator`, `nl2sql_orchestrator`, and a duplicate published
`india_fund_orchestrator`) was collapsed into ONE root,
`agent_forge_orchestrator` (`scripts/consolidate_orchestrators.py` — reused
`market_intelligence_orchestrator`'s existing id/rename mechanics rather
than creating a new agent). It routes across every real domain — market
intelligence, credit risk, revenue/sales analytics, StudyBuddy tutoring —
using the same generic router-prompt builder every orchestrator here already
used (`app/agent_runtime/orchestration_patterns.py`, no new prompt-building
code). The retired orchestrators are `archived`, not deleted, preserving
their version history; `chat_api`'s `CHATBOT_AGENT_NAME` default now points
at the new root. `revenue_query_orchestrator` (an older query-decomposition/
scratchpad pattern with its own real internal tool/child wiring) was kept
and demoted to a leaf rather than dismantled.

**Planner/ReAct** (`google.adk.planners.PlanReActPlanner` — not implemented
anywhere before this; ADK ships it as a real, fully-wired primitive,
confirmed by reading `flows/llm_flows/_nl_planning.py` directly) is enabled
per agent via `model_config.planning.enabled`, mirroring SCIL/durable-
execution's opt-in shape:

```json
"planning": { "enabled": true }
```

`app/agent_runtime/builder.py` passes `planner=PlanReActPlanner()` into
`AdkAgent(...)` when set — decided per-node from that agent's own config
(unlike durable execution, planning isn't inherited from a root; each agent
in a tree opts in independently). Turned on for `agent_forge_orchestrator`
and every real leaf specialist EXCEPT `flashcard_agent`/`quiz_agent` (their
`output_schema` needs strict JSON, which cannot coexist with the planner's
free-text `/*PLANNING*/…/*ACTION*/…/*FINAL_ANSWER*/` format) and
`reliability_demo_agent` (out of scope — a platform-capability demo, not a
business specialist).

ADK marks the planner's reasoning/plan/action text as `part.thought = True`
on the parts it yields — `_execute_run`/`_stream_turn`
(`app/playground_api/router.py`) split on that flag so raw ReAct tags never
reach the user-facing answer (still recorded as a `model_text`
`AgentEventLog` row with `detail.reasoning = true` for the Debug Console).
Confirmed live (real Gemini calls, not just unit tests): a cross-domain
question correctly transferred through `crypto_analyst` and
`fund_analyst_agent` and composed one clean answer with zero leaked tags.
**Honest caveat, not glossed over**: the planning instruction is genuinely
appended to every request for an opted-in agent (traced through ADK's
`_nl_planning.request_processor`, unconditional whenever `agent.planner` is
set) — but `PlanReActPlanner` is purely instructional (unlike
`BuiltInPlanner`, which wraps a model's native thinking-config support), so
whether the model actually emits the tagged format is model-compliance-
dependent; `gemini-3.5-flash` did not emit the format in this session's live
test, so no `reasoning: true` events have been observed yet in practice,
even though the wiring is correct and the leak-prevention path is real.

### Cleanup

`scripts/cleanup_verification_artifacts.py --confirm` removes test-suite-
accumulated debris (the pytest `unique_name()` fixture pattern — see
Testing Philosophy above) using referential orphan-detection for tools/
skills (not name matching, so a real-but-undocumented tool that happens to
lack a `created_by` marker is never caught) plus an explicit allowlist for
the handful of real agents that also lack one. `--dry-run` (the default)
only prints what would be deleted.

## Backend setup

```bash
cd backend
python -m venv ../.venv   # if not already created
source ../.venv/Scripts/activate
pip install -e ".[dev]"
cp .env.example .env      # then fill in real values
alembic upgrade head
uvicorn app.main:app --reload
```

All routes under `/api` require `Authorization: Bearer <AGENT_FORGE_API_TOKEN>`
(see `.env`), or a per-user session token issued via `/api/auth`.

Optional seed scripts (all idempotent, all support `--reset`):

```bash
python scripts/seed_demo_data.py                        # synthetic dashboard data
python scripts/seed_studybuddy_agents.py                # StudyBuddy's 7 sub-agents + orchestrator
python scripts/seed_market_agents.py                    # Market Intelligence agent family
python scripts/seed_reporting_specialist.py             # generic chart/slide/export specialist
python scripts/seed_reliability_demo.py                 # durable-execution saga/compensation worked example
python -m app.domains.credit_facility.seed_data          # Credit Facility MySQL demo data
python -m app.domains.credit_facility.seed_agent         # Credit Facility access policies/tools/agent
```

`scripts/rename_agent.py <old_name> <new_name>` renames any published
agent and republishes it so the ADK build tree actually picks up the new
name (not just a bare `UPDATE agents SET name = ...`).

## Frontend setup

```bash
cd frontend
npm install
cp .env.example .env      # point VITE_API_BASE_URL at the backend
npm run dev
```

The admin UI expects `AGENT_FORGE_API_TOKEN` (or an approved user login) to
sign in; the end-user chat surface at `/chat` uses its own register/login
flow instead.

## Tests

```bash
cd backend
python -m pytest
```

Tests run against the real local Postgres `agent_forge` schema (no mocked
DB) and make two kinds of real external calls: hermetic ones via
`httpx.MockTransport` for HTTP-tool unit tests, and one genuinely live call
in `test_playground.py` that exercises real Gemini + ADK + a real HTTP
GET to prove the full stack works end to end. Tests create rows with random
suffixes; a few (agent/version rows in particular) aren't deleted after the
run, so the schema will accumulate test data over repeated runs — safe to
truncate (`TRUNCATE agent_forge.<table> ... CASCADE`) whenever that's
inconvenient.
