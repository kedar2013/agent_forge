# SCIL — Self-Correcting Intelligence Layer
## Complete Technical Documentation (System + Dashboard)

*Eärendil (Agent Forge) — July 2026*

---

## 1. What SCIL is and why it exists

Every agent turn in Eärendil — playground test runs, published `/invoke`
calls, and both chat surfaces — used to result in one or more full Gemini
LLM calls, **even when**:

1. The same (or nearly the same) question had already been answered and
   validated before,
2. The request was trivially answerable without a model at all
   ("what are your support hours?"), or
3. The model produced an output with a deterministically-detectable defect
   (broken SQL, JSON that violates the agent's declared schema) that a
   cheap retry-with-feedback would fix — but instead the user retried
   manually, paying for the same mistake twice.

SCIL is a layer wrapped around agent invocation that eliminates all three
wastes. It is **per-agent, config-driven, and off by default** — an agent
with no `scil` key in its `model_config` behaves byte-identically to the
pre-SCIL platform.

The **SCIL Dashboard** (`/scil` in the admin console, admin-only) is the
observability and curation surface for this layer: it proves the savings
(LLM calls avoided, latency deltas), exposes the learned knowledge (cached
answers, correction memory), and gives admins the controls to curate it
(delete/purge).

---

## 2. Request flow — the decision ladder

Every turn on a SCIL-enabled agent walks this ladder, cheapest first.
The single integration point is `_run_turn` / `_stream_turn` in
`backend/app/playground_api/router.py` — verified to be the funnel for
**all four** entry points (playground `/run`, published
`/agents/{id}/invoke`, chat blocking, chat streaming), since nothing else
in the codebase constructs an ADK `Runner`.

**Entry point → function mapping** (verified live, this session):

| Entry point | Route | Function | Steps [1]-[5], [7], [8] | Step [6] retry loop |
|---|---|---|---|---|
| Playground | `POST /agents/playground/run` | `_run_turn` | ✅ | ✅ |
| Published invoke | `POST /agents/{id}/invoke` | `_run_turn` | ✅ | ✅ |
| Chat, blocking | `POST /chat/message` | `_run_turn` | ✅ | ✅ |
| **Chat, streaming** | `POST /chat/message/stream` | `_stream_turn` | ✅ | **❌ — never retries** |

**This matters in practice**: the browser `/chat` UI (`frontend/src/pages/ChatPage.tsx`)
calls `sendChatMessageStream`, which hits `/chat/message/stream` exclusively
— there is no UI toggle to use the blocking endpoint. So **for anyone
testing SCIL by typing into `/chat`, the self-correction/retry loop
(step [6] below) will never fire**, no matter how the question is phrased
or which validators are configured on the agent. `_stream_turn` still runs
the configured validators, but only to decide whether the answer is safe
to cache (step [7]) — a failed validation on the streaming path just skips
the cache write and returns the answer as-is; it does not retry, does not
write to `scil_correction_memory`, and logs route `llm` (not `llm_retry`)
in `scil_metrics`. The literal comment in the code
(`playground_api/router.py`, in `_stream_turn`):

> "No retry loop on the streaming path (matching the stale-session/
> hallucination self-heals, which are also non-streaming-only) — but the
> validators still gate the cache, so an invalid streamed answer can't
> become a future cache hit."

To actually observe a retry/correction happen for a chat-facing agent, call
`POST /chat/message` (the non-streaming twin, same auth — any logged-in
persona/chat_user token works) directly, e.g. via `curl`, rather than the
`/chat` browser UI. See the worked example in §7 (item 8) for a full
walkthrough.

```
User request
   │
   ▼
[1] Normalizer (app/scil/normalizer.py)
    trim → collapse whitespace → lowercase → sha256 input_hash
   │
   ▼
[2] Template router (app/scil/templates.py)          route="deterministic"
    regex fullmatch against per-agent templates  ──► 0 LLM calls, ~1ms
   │ miss
   ▼
[3] Semantic cache (app/scil/cache.py)               route="cache_hit"
    a. exact input_hash match                    ──► 0 LLM calls, ~15-80ms
    b. pgvector cosine similarity ≥ threshold
    (both scoped by TTL + validated flag + user partition where configured)
   │ miss
   ▼
[4] LLM call, exemplar-augmented (app/scil/exemplars.py)
    top-k similar past corrections prepended to the prompt
    so known mistakes are avoided on the FIRST attempt
   │
   ▼
[5] Validator chain (app/scil/validators.py)  — deterministic, no LLM
    sql / json_schema / hallucination (zero-tool-call check, free)
    │
    ▼
[5b] Groundedness judge (app/scil/hallucination.py) — LLM-judge, opt-in
    only runs if [5] passed AND "hallucination" in validators AND
    hallucination_groundedness_check=true AND at least one tool was called
    this turn. Costs one extra model call. Fails open on judge error.
    │
    ▼
[5c] Entity resolution (app/scil/entities.py) — embedding lookup, opt-in,
    no LLM call. Only runs if [5]/[5b] passed AND "entity_resolution" in
    validators AND a data_query_tool call this turn ran clean SQL but
    matched zero rows. Blends sentence-transformer cosine similarity with
    lexical (difflib) similarity against scil_entity_memory — an agent-
    scoped, self-growing memory of entity strings ("Tesla Inc") seen in
    past SUCCESSFUL lookups. Cold start (no memory yet) passes through
    unflagged; only fires a retry when a genuine scored candidate exists.
   │ pass                    │ fail (from [5], [5b], or [5c])
   ▼                         ▼
[7] Cache write         [6] Self-correction loop (app/scil/corrector.py)
    (validated only)        retry SAME model with structured error feedback
                            + known fix for this error class if one exists
                            max N retries (default 2)    route="llm_retry"
                            ├─ pass → store correction pair → cache write
                            └─ still failing → answer returned, NOT cached
                            NON-STREAMING PATH ONLY — see §2 entry-point
                            table; _stream_turn never reaches step [6]
   │
   ▼
[8] Metrics row (app/scil/metrics.py) — written for EVERY turn,
    including scil-disabled ones (route="disabled"), so baseline volume
    is visible before an agent is ever enabled.
```

---

## 3. Database schema

Three tables in the `agent_forge` Postgres schema, created by Alembic
migrations `e2f9a6c1b8d4` (initial) and `f4b8d2e9a713` (user scoping).
The initial migration also runs `CREATE EXTENSION IF NOT EXISTS vector` —
the first pgvector enablement in this repo's own migration history.

### 3.1 `scil_semantic_cache`
| Column | Purpose |
|---|---|
| `agent_id` (FK → agents) | Cache entries never cross agents |
| `scope_key` | `""` for globally-shared answers; the asking user's id when the agent's config says `cache_scope: "user"` (RLS domains) |
| `input_hash` | sha256 of the normalized input — the exact-match fast path |
| `input_text` | Original (un-normalized) question, shown in the dashboard |
| `input_embedding VECTOR(384)` | HNSW cosine index for the similarity fallback |
| `output_payload JSONB` | `{response_text, tool_calls[]}` — the validated answer |
| `hit_count`, `last_hit_at` | Incremented per hit; the dashboard's curation signal |
| `validated` | Always true today (only validated outputs are written); exists so a future re-validator can flip rows without a migration |
| `ttl_expires_at` | Stamped from `cache_ttl_hours`; expired rows are invisible to lookups and overwritten in place by the next validated answer |

Unique upsert key: `(agent_id, scope_key, input_hash)` — two concurrent
misses on the same input can never duplicate rows.

### 3.2 `scil_correction_memory`
`(input_text, input_embedding, failed_output, error_signature,
error_detail, corrected_output, correction_source, reuse_count)` — one row
per turn the self-correction loop **recovered**. Written with
`correction_source='auto_retry'`; `'hitl'`/`'user_feedback'` are reserved.
`reuse_count` increments every time the row is served as an exemplar or a
retry hint — the dashboard sorts curation decisions by it.

### 3.3 `scil_entity_memory`
`(agent_id, entity_text, entity_embedding, use_count, last_used_at)` — the
self-growing memory app/scil/entities.py reads and writes. Starts empty per
agent; a row is written (or `use_count` bumped via `ON CONFLICT DO UPDATE`)
every time a `data_query_tool` call's WHERE-clause literal appears in a
lookup that came back with ≥1 row. Unique upsert key: `(agent_id,
entity_text)`.

### 3.4 `scil_metrics`
One row per turn: `route`, `llm_calls`, `retries`, `input_tokens`,
`output_tokens`, `latency_ms`. Routes written today:

| Route | Meaning | LLM calls |
|---|---|---|
| `disabled` | Agent has no/false `scil.enabled` — baseline traffic | 1 |
| `deterministic` | A configured template answered | 0 |
| `cache_hit` | Semantic cache answered | 0 |
| `llm` | Normal model call (validated first try or no validators) | 1 |
| `llm_retry` | Self-correction loop fired ≥ once (`retries` says how often) | 1 + retries |

---

## 4. Backend components

All SCIL business logic lives in `backend/app/scil/` (no FastAPI code —
same convention as `app/observability/`). The admin API lives in
`backend/app/scil_api/router.py`.

| Module | Responsibility |
|---|---|
| `normalizer.py` | Deterministic canonicalization + `input_hash`. `entities[]` stays an empty stub *here* — it would only ever widen cache-hit rates. The correctness-bearing half of entity canonicalization lives in `entities.py` instead (see below) |
| `cache.py` | Exact-hash and cosine-similarity lookup, TTL filtering, scope partitioning, idempotent upsert write. Contains the schema-qualified pgvector operators (`OPERATOR(public.<=>)` / `public.vector`) needed because the app's engine locks `search_path` to `agent_forge` while the extension lives in `public` |
| `validators.py` | Deterministic output validators, no LLM calls anywhere in this module (enforced by its own docstring): `sql` (sqlglot AST — reuses `data_query_tool.validate_single_select`'s guardrails; strips markdown code fences first), `json_schema` (validates against the agent's own declared `output_schema`), and `hallucination` (zero-tool-call check — an agent with tools attached that answers without calling any of them this turn is very likely inventing the answer; ported from the onboarding wizard's client-side smoke-test check so it now runs on every real turn, not just one canned question). First failure wins; unknown validator names are skipped, never fatal |
| `hallucination.py` | The LLM-judge *second* half of hallucination detection, sibling to `corrector.py` (not part of `validators.py`, which bans LLM calls). `check_groundedness()` sends the tool-call outputs + final answer to the same model as a strict fact-checker prompt, asking whether every claim traces back to real tool output; only runs when `"hallucination"` is in `validators` **and** `hallucination_groundedness_check: true` **and** at least one tool call happened this turn (a zero-tool-call turn is already caught for free by the deterministic check, so the judge call is skipped rather than restating the same finding). Fails open (`ok=True`) on any judge-call exception — a broken judge must never block a real answer |
| `corrector.py` | Builds the structured retry prompt (error signature + detail + failed output + known fix), looks up correction memory by `(agent, error class, input similarity ≥ 0.85)`, writes correction pairs on recovery |
| `entities.py` | Entity resolution — the failure class neither `validators.py` nor `hallucination.py` can see: syntactically valid SQL, a real `data_query_tool` call, zero rows because the searched-for literal was misspelled. `resolve_entity_mismatch()` blends sentence-transformer cosine similarity with lexical (`difflib`) similarity against `scil_entity_memory`; **measured live, pure cosine alone is a bad fit for single-token typos** — `cosine("Tesla Inc", "Tesslla") = 0.135`, actually *worse* than `cosine("Tesla Inc", "Microsoft Corp") = 0.42`, because MiniLM embeds meaning, not spelling, while it's exactly right for legitimate semantic/casing variants (`cosine("HDFC Bank Ltd", "HDFC") = 0.73`). Taking `max(cosine, lexical)` covers both. `remember_entities_fire_and_forget()` grows the memory from every successful (≥1 row) lookup — cold start (nothing remembered yet) intentionally passes a zero-row result through unflagged rather than force a retry on a guess, matching the same "never guess" fallback the calling agent's own instructions already rely on |
| `exemplars.py` | Pre-first-attempt few-shot injection: top-k corrections (cosine ≥ 0.85), compact block under an ~800-token budget, truncating lowest-similarity first. Only the outbound prompt changes — transcript, cache key, and embeddings keep the original message |
| `templates.py` | Per-agent regex/slot templates. `fullmatch` only (a template must never answer a longer, different question); named groups become `str.format` slots; invalid regexes and unresolvable slots skip cleanly |
| `runner.py` | Orchestration glue: config parsing (`ScilConfig`), template check, cache check, exemplar message building, fire-and-forget cache/metrics writes |
| `metrics.py` | The one metrics writer |
| `../embeddings.py` | The platform's single shared embedder (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim), extracted from `retrieval_tool.py` so RAG and SCIL share one provider |

**Session-handling design decision**: SCIL never borrows the request's
`Depends(get_db)` session. The cache lookup (which gates whether the LLM
runs at all) is awaited inline on its own short-lived session; cache
writes, correction writes, and metrics are fire-and-forget
`asyncio.create_task(...)` on their own sessions — the same pattern
`logging_hooks.log_invocation_fire_and_forget` already established,
necessary because `_stream_turn` is a `StreamingResponse` generator that
outlives its request's session.

### 4.1 Admin API (`/api/scil/...`, all `require_role("admin")`)

Gated tighter than the debug console (which viewers/developers can see)
because cached Q&A pairs contain other users' request/response content.

| Endpoint | Purpose |
|---|---|
| `GET /metrics/summary?agent_id=&from_date=&to_date=` | Route distribution, LLM calls avoided, cache-hit rate, retried turns, retry success rate, avg latency per route |
| `GET /metrics/timeseries?range_days=&agent_id=` | Per-day `(route, count, llm_calls)` buckets |
| `GET /cache/entries?agent_id=&limit=&offset=` | Paginated cache listing (workspace-scoped via `Agent` join) |
| `DELETE /cache/entries/{id}` | Remove one cached answer |
| `POST /cache/purge {agent_id}` | Drop an agent's entire cache |
| `GET /corrections?agent_id=&error_signature=` | Paginated correction-memory listing |
| `DELETE /corrections/{id}` | Curate out a bad correction |
| `GET /entities?agent_id=&limit=&offset=` | Paginated `scil_entity_memory` listing, sorted by `use_count` desc |
| `DELETE /entities/{id}` | Curate out a wrongly-remembered entity (e.g. a typo that itself got written once) before it corrupts a future match |

`retry_success_rate` needs no extra bookkeeping column: an `auto_retry`
correction row is written exactly once per *recovered* turn, so
`recovered / retried` over the same agent+time window is the rate.

---

## 5. The Dashboard (frontend)

**Files**: `frontend/src/pages/ScilDashboardPage.tsx` (the page),
`frontend/src/api/scil.ts` (react-query hooks + types),
nav entry in `components/Layout.tsx` (Observability section, admin-only),
route in `App.tsx` behind `<RequireRole roles={['admin']}>`.

Built entirely from the platform's existing UI system — `Card`,
`StatTile`, `Badge`, `Skeleton`, `LiveBadge`, recharts, and the shared
`chartPalette` dark-mode hook — so it reads as a native sibling of the
Usage/Monitoring/Audit dashboards. All queries poll every 30 s
(`refetchInterval`), so the page is live without manual refresh.

### 5.1 Element by element

1. **Range selector** (7d / 30d / 90d) — scopes the tiles, donut, and
   timeseries.
2. **Four stat tiles**:
   - *LLM calls avoided* — count of `cache_hit` turns (each one is a
     Gemini round-trip that didn't happen).
   - *Cache hit rate* — `cache_hit / total_requests`.
   - *Retried turns* — turns where the self-correction loop fired.
   - *Retry success rate* — fraction of retried turns that ended in a
     validated answer.
3. **Route distribution donut** — the shape of traffic at a glance.
   Colors are **semantic and fixed** (not positional): green =
   `cache_hit`, violet = `deterministic` (both "0 LLM calls"), blue =
   `llm`, amber = `llm_retry`, slate = `disabled`. A growing green+violet
   share is the visual definition of SCIL paying for itself.
4. **Requests over time, by route** — stacked bars per day, same colors.
   Shows whether savings are trending up as the cache warms.
5. **Semantic cache table** — agent, question text, hit count, last hit;
   per-row delete and per-agent **Purge** (with confirm). This is where an
   admin answers "what is SCIL actually serving?" and evicts anything
   stale or wrong.
6. **Correction memory table** — agent, input, error-signature badge
   (e.g. `SQL:Syntax`), source, reuse count; per-row delete. High
   `reuse_count` = a memory that keeps earning its keep; a wrong
   correction can be curated out before it misleads future prompts.

---

## 6. Configuration reference

Per-agent, under `model_config.scil` (validated by `ScilAgentConfig` in
`app/schemas/agents.py` so it round-trips through `POST/PATCH /api/agents`):

```jsonc
"scil": {
  "enabled": true,                    // master switch; absent/false = pre-SCIL behavior
  "cache_similarity_threshold": 0.80, // cosine floor for fuzzy cache hits
  "cache_ttl_hours": 24,              // null = never expires
  "cache_scope": "user",              // "global" (default) | "user" — RLS domains MUST use "user"
  "max_retries": 2,                   // self-correction loop budget
  "exemplar_top_k": 3,                // corrections injected into first attempts
  "validators": ["sql"],              // [] (default) = accept any successful turn
                                       // recognized: "sql" | "json_schema" | "hallucination" | "entity_resolution"
  "hallucination_groundedness_check": false, // only meaningful if "hallucination" is in validators;
                                       // opts into the extra LLM-judge pass on top of the always-free
                                       // zero-tool-call check (see §4, hallucination.py)
                                       // "entity_resolution" needs no extra flag — deterministic-cost
                                       // (one embedding lookup, no LLM call) once it's in the list
  "templates_enabled": true,
  "templates": [
    {"pattern": "^ping$", "response_text": "pong"},
    {"pattern": "convert (?P<amt>\\d+) (?P<src>[a-z]{3}) to (?P<dst>[a-z]{3})",
     "response_text": "Use /tools/fx?amount={amt}&from={src}&to={dst}"}
  ],
  "escalation_model": null            // reserved — escalation tier not built
}
```

**`validators` defaults to `[]` and no seed script sets it for most agents.**
`scripts/enable_scil.py`'s config dict for every agent it enables sets only
`enabled`/`cache_ttl_hours`/`cache_scope`, never `validators`. Since the
script does a full `jsonb_set` replace of the `scil` key (not a merge), any
validator that had been configured separately would be wiped out by the
next run of this script anyway. Practically: **out of the box, no shipped
agent has the self-correction loop wired up** — it has to be turned on
explicitly per agent, e.g.:

```sql
UPDATE agents
SET model_config = jsonb_set(model_config, '{scil,validators}', '["hallucination", "entity_resolution"]'::jsonb, true)
WHERE trim(name) = 'credit_facility_analyst' AND status != 'archived';
```

`credit_facility_analyst` now runs with exactly this config in this
deployment — turned on live to close a real gap: "give me credit facility
data for Tesslla" used to dead-end in "I couldn't find any companies
matching 'Tesslla'. Did you mean Tesla?" because the agent's own "never
guess a company_id" instruction (correct, RLS-driven) had nothing to
correct against. *Verified live* via `POST /api/chat/message`: first
attempt SQL `WHERE company_name LIKE '%Tesslla%'` → 0 rows →
`Entity:NoMatch` (matched `scil_entity_memory`'s "Tesla Inc" at high
similarity) → retry `WHERE company_name LIKE '%Tesla%'` → 4 rows, resolved
to Tesla Inc's real July 2026 facility data. `scil_metrics` shows
`route=llm_retry, retries=1`; `scil_correction_memory` has the
`Entity:NoMatch` row. See §4's `entities.py` entry for why this needed a
blended cosine+lexical score rather than sentence-transformer similarity
alone.

(`sql_insights_agent`'s entry in `ENABLE` explicitly sets `"validators": []`
— read this as "make sure it's off," not as evidence a validator was ever
on for it via this script.)

**Fleet enablement**: `python scripts/enable_scil.py [--disable]` sets
domain-appropriate configs on the real agents:

| Agents | TTL | Rationale |
|---|---|---|
| stock/crypto/forex/market-orchestrator, weather | 1 h | Market data staleness bound |
| funds, company research, sql insights, reporting | 24 h | Daily-ish data |
| translator, example | 168 h | Effectively deterministic |
| credit_facility_analyst | 24 h + `cache_scope:"user"` | RLS — see §7. Also carries `validators: ["hallucination", "entity_resolution"]`, added by hand (not by this script — see above) |
| StudyBuddy family | **not enabled** | Session-state-scoped retrieval; quiz output should vary |

`enable_scil.py` itself still sets no `validators` for any agent — every
row above except `credit_facility_analyst` runs with the correction loop
dormant (empty validator list) until someone adds one by hand, as shown
above.

---

## 7. Safety design

These are the load-bearing correctness rules, each one discovered or
verified against a real failure mode during implementation:

1. **Row-level security × caching**: a global cache key would serve one
   persona's `credit_facility_analyst` answer to another persona.
   `cache_scope: "user"` partitions the cache by the asking user's id
   (the same identity the policy engine resolves personas from).
   *Verified live*: the same Tesla question from a different `user_id` is
   a cache miss.
2. **Failed-tool-call gate**: a turn whose tool call errors (e.g. an RLS
   authorization refusal) still counts as ADK "success" because the model
   apologizes gracefully — and that apology must never become a cached
   answer. Both paths refuse to cache any turn with a failed tool call.
   (Found live when an unauthenticated test call cached "I encountered an
   error"; fixed same session.)
3. **Validated-only caching**: an answer that exhausts its retries still
   invalid is *returned* (the user gets the best available answer) but
   *never cached* — a mistake can't be replayed to future callers.
4. **Templates use `fullmatch`** — a pattern can never hijack a longer,
   more nuanced question that merely contains the template phrase.
5. **Correction retries never relax guardrails** — validators are pure
   functions over output text; the retry re-enters the exact same
   validated pipeline.
6. **Fail-open optimization posture**: every SCIL I/O failure (cache
   lookup, exemplar fetch, metrics write) logs and falls through to the
   normal LLM path. SCIL can only ever make a turn cheaper, never break it.
7. **Kill switch**: `scil.enabled=false` (or running
   `enable_scil.py --disable`) restores exact pre-SCIL behavior with no
   restart (config is read from the agents row per request, not from the
   cached ADK build).
8. **Streaming path never retries, by design, not by bug**: `_stream_turn`
   runs the validator chain only to decide whether to write a cache entry
   — a failing turn is still streamed to the user as-is, at route `llm`,
   with no correction attempt and no `scil_correction_memory` write. This
   means the browser `/chat` UI (which always calls the streaming
   endpoint) can never demonstrate the self-correction loop, only the
   cache. See §2's entry-point table and the worked example below for how
   to actually exercise it against a chat-facing agent.
9. **Deterministic hallucination check is shape-based, not
   content-based** — `Hallucination:NoToolCall` fires on *any* tool-less
   turn, including a *correct* refusal. Verified live: asking
   `credit_facility_analyst` "What is the capital of France?" via
   `POST /api/chat/message` (non-streaming) got a correct, honest refusal
   ("I cannot use any of my tools to provide this information") with zero
   tool calls — which still trips the validator and would enter the retry
   loop if this validator were enabled. This is expected behavior for a
   free, deterministic heuristic, not a defect — but it means enabling
   `hallucination` broadly on an agent that legitimately fields
   off-domain questions will generate retries/corrections on turns that
   were never actually wrong. Prefer scoping it to agents where "answered
   without querying" is *always* a red flag.
10. **Entity resolution never guesses on a cold start** — `resolve_entity_mismatch`
    only fails validation (and thus triggers a retry) when a genuine, scored
    candidate already exists in `scil_entity_memory` for that agent. The
    very first time an agent sees any zero-row result, there is nothing to
    correct against yet, so it passes through unflagged and the agent's own
    "ask the user to confirm" behavior is exactly what happens — matching
    pre-feature behavior byte-for-byte. Memory only grows from *successful*
    (≥1 row) lookups, never from a guess, so a wrong correction can't
    compound into a worse one; the admin API's `DELETE /entities/{id}`
    exists for the rare case a bad string gets remembered anyway (e.g. a
    typo that itself happened to return rows).

**Worked example — exercising the retry loop on a chat-facing RLS agent**:
the Playground can't impersonate an RLS persona, and the `/chat` UI only
hits the streaming endpoint, so the direct way to see `_run_turn`'s full
retry loop fire for e.g. `credit_facility_analyst` is to call the blocking
chat endpoint yourself with a persona's token:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"gcm1@creditfacility.demo","password":"Demo@12345"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s -X POST http://127.0.0.1:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"What is the capital of France?","agent_name":"credit_facility_analyst"}'
```

Then check `scil_metrics` (`route = 'llm_retry'`, `retries > 0`) and
`scil_correction_memory` (`error_signature = 'Hallucination:NoToolCall'`)
for that agent to confirm the loop actually ran. Demo login credentials
and all eight personas are listed in
`backend/app/domains/credit_facility/seed_data.py` (`DEMO_USERS`,
password `Demo@12345` for all).

---

## 8. Error-signature taxonomy

Stable strings — correction memory rows and the corrections API filter on
them, so they are contract, not free text:

| Signature | Emitted when |
|---|---|
| `SQL:Syntax` | Response didn't parse as SQL at all |
| `SQL:NotSingleSelect` | Parsed, but not exactly one read-only SELECT |
| `SQL:GuardrailViolation` | INSERT/UPDATE/DELETE/DDL anywhere in the AST |
| `JSON:ParseError` | Response isn't valid JSON |
| `JSON:SchemaMismatch` | Valid JSON, violates the agent's `output_schema` |
| `Hallucination:NoToolCall` | Deterministic, free (`validators.py`) — the agent has tools attached but answered without calling any of them this turn. Blunt by design: it flags the *shape* of the turn (no tool call), not the *content*. Verified live: an off-domain question ("What is the capital of France?") to `credit_facility_analyst` correctly gets refused by the model with zero tool calls — a *correct* answer — but still trips this signature, because the check has no way to distinguish "correctly declined" from "should have looked something up." Treat it as a signal to review, not proof of an actual hallucination |
| `Hallucination:Ungrounded` | LLM-judge, opt-in, costs one extra model call (`app/scil/hallucination.py`) — a second model reviews the tool outputs actually received this turn and the final answer, and flags any claim not traceable to that tool output. Only runs when `Hallucination:NoToolCall` did *not* already fire (i.e., at least one tool was called) **and** `hallucination_groundedness_check: true` is set. Fails open on judge error |
| `Entity:NoMatch` | Deterministic-cost, no LLM call (`app/scil/entities.py`) — a `data_query_tool` call ran clean SQL and returned zero rows, but a WHERE-clause literal it searched for scored ≥0.6 (blended cosine + lexical similarity) against a string already in `scil_entity_memory` for this agent. Only fires when a genuine candidate exists — a cold-start zero-row result with no memory yet never trips this signature. Fails open on any lookup error |

The spec's `citation` validator is intentionally unimplemented: chat
responses carry no structured citation ids to check against a retrieved
chunk set, so there is nothing deterministic to validate yet.

---

## 9. Measured benefits (all from live verification, this deployment)

| Scenario | Without SCIL | With SCIL |
|---|---|---|
| Repeat MSFT price question (differently phrased), `stock_market_analyst` via `/invoke` | 6,452 ms + 1 Gemini call + 1 Yahoo call | **77 ms, 0 LLM calls** (similarity hit) |
| Repeat capital-of-France question (playground, test agent) | 1,827 ms | **15 ms** |
| Repeat credit-facility question, same user, chat surface | ~7,000 ms | **0–15 ms** (user-scoped hit) |
| Template match | full LLM turn | **~1 ms, 0 LLM calls** |
| Known SQL mistake on a similar question | full failed turn + manual user retry | avoided up front via exemplar injection, or auto-recovered in 1 retry |
| "Tesslla" (misspelled "Tesla") vs `credit_facility_analyst`, chat surface | "I couldn't find any companies matching 'Tesslla'. Did you mean Tesla?" — dead end, user must retype | **1 auto-retry, real Tesla Inc data returned** — `route=llm_retry`, `error_signature=Entity:NoMatch` |

Structural benefits beyond latency/cost: repeated mistakes become
one-time costs (correction memory), quality regressions are visible the
day they start (retry success rate), and the platform finally has a
baseline (route=`disabled` rows) proving what un-enabled agents cost.

---

## 10. Testing

Five test files, 33 tests, all against the real dev Postgres (no mocked
DB, per repo convention):

- `tests/test_scil.py` — Phase-2 integration with **live Gemini**:
  disabled passthrough; miss→write; hit with zero additional LLM calls.
- `tests/test_scil_correction.py` — validator taxonomy (pure unit, 10
  cases) + the retry loop driven by **monkeypatched scripted outcomes**
  (deterministic validation failures, no LLM flakiness): fail→retry→
  recover writes the correction + caches; retry exhaustion returns but
  never caches.
- `tests/test_scil_p4.py` — template matching semantics; exemplar block
  budget; template hit **never invokes the model** (patched executor
  raises if called); a stored correction reaches the model's *first*
  prompt and bumps `reuse_count`.
- `tests/test_scil_hallucination.py` (9 tests) — the deterministic
  zero-tool-call check (flags when tools attached + no call; passes when a
  tool was called; never flags when the agent has no tools; dispatches
  correctly through `validate_output`); the retry loop end-to-end for a
  hallucination failure (self-corrects, and separately, logs a
  `hallucination_unresolved` event on retry exhaustion — mirrors the
  `all_events.append(...)` block in `_run_turn`, see §7); and the LLM-judge
  groundedness check in isolation (flags an ungrounded answer, accepts a
  grounded one, skips entirely when there were no tool calls to judge
  against — the deterministic check already covers that case for free).

- `tests/test_scil_entities.py` (12 tests) — pure-unit literal extraction
  (LIKE wildcards stripped, multiple literals, short literals filtered,
  invalid SQL never raises); `resolve_entity_mismatch` against real
  Postgres (finds a seeded "Tesla Inc" for a "Tesslla" query; cold-start
  with no memory passes through; ignores non-empty and error results);
  `remember_entities_fire_and_forget` (writes, then dedupes/bumps
  `use_count` on a repeat); and the retry loop end-to-end with
  monkeypatched scripted outcomes (self-corrects and writes both the
  correction and the cache entry; a cold-start zero-row result never
  forces a retry, `route` stays `llm` not `llm_retry`).

One genuine flake was found and fixed: whether the first turn's
fire-and-forget cache write landed before the second request depended on
embedder warmth (test order), silently flipping the second request from
the exemplar path to a cache hit — fixed by purging the cache between the
two phases of that test.

---

## 11. Known limitations / future work

- **Self-correction loop is unreachable from the primary chat UI**: the
  browser `/chat` surface only ever calls `POST /chat/message/stream`
  (`_stream_turn`), which — by design, see §7.8 — never retries, only
  gates caching. The retry/correction machinery is fully built and tested
  (§10) and reachable via the Playground, `/invoke`, and the *blocking*
  `/chat/message` endpoint, but there's currently no way for an end user
  chatting through the actual product UI to trigger or benefit from a
  self-correction. Options for closing this gap: port a retry loop into
  `_stream_turn` (harder — has to retry mid-stream without duplicating
  already-yielded tokens), or have the chat UI fall back to a blocking
  call for agents that have `validators` configured, at the cost of
  losing live "thinking steps" during retries.
- **Deterministic hallucination check has no way to distinguish a correct
  refusal from an actual invented answer** — see §7.9. Fine for agents
  that should always be grounding on a tool; will over-flag agents that
  legitimately answer some questions without tools.
- **`hallucination_groundedness_check` adds real LLM cost and latency**:
  it's an *extra* full model call per turn (on top of the turn's own call,
  and on top of any retries), only worth enabling where a wrong-but-
  plausible-sounding answer is costlier than an extra Gemini round trip.
- **Escalation tier & HITL** (`escalation_model` accepted but unused):
  retry exhaustion currently returns the best available answer; routing
  to a bigger model or a human queue needs model-variant agent builds and
  review infrastructure that don't exist yet.
- **Conversation context**: the cache key is the message text alone. A
  context-dependent follow-up ("what was that code I mentioned?") that
  happens to match a cached standalone question would be served the
  standalone answer. Session-aware keys are future work; per-user scoping
  bounds the blast radius today.
- **StudyBuddy family stays un-enabled** until the cache key can carry
  session state (grade/subject/book), not just user identity.
- **Entity canonicalization** for the *cache key* ("HDFC bank ltd" → "HDFC
  Bank" folding into one cache entry) is still stubbed — the normalizer's
  `entities[]` is always empty; that's still true and still low-priority
  (nice-to-have cache-hit-rate widening, not correctness). The
  correctness-bearing half — catching a misspelled entity that makes a
  *tool call* return zero rows — is no longer a gap; see §4/§10's
  `entities.py`.
- **Entity resolution only understands `data_query_tool` calls**: it
  structurally detects the `{row_count, columns, data, ...}` /
  `{"error": ...}` shape `DataQueryTool.run_async` returns. An agent whose
  "no match" tool is an `mcp_tool` or `http_tool` (different output shape)
  gets no benefit from this validator today — extending detection to other
  tool types would mean either standardizing their empty-result shape or
  adding a per-tool-type adapter.
- **The 0.6 match threshold and the `max(cosine, lexical)` blend are a
  heuristic, not a proof** — tuned against a handful of manually-checked
  pairs (§4's `entities.py` docstring), not a labeled dataset. A domain
  with many short, similarly-spelled entity names (e.g. ticker-like codes)
  could see more false-positive matches than the Tesla/HDFC/Apple examples
  suggest; worth revisiting per-domain if that happens.
- **No frontend surface yet for `scil_entity_memory`**: the admin API
  (`GET/DELETE /api/scil/entities`) exists, but `ScilDashboardPage.tsx`
  doesn't render an entity-memory table yet, unlike the cache/corrections
  tables it already has. A natural, small follow-up matching the existing
  dashboard's pattern.
- **Cache pruning job** (LRU beyond TTL) not yet implemented; tables are
  small and TTL + purge cover current volumes.

---

## 12. File inventory

```
backend/
  alembic/versions/e2f9a6c1b8d4_add_scil_tables.py        # 3 tables + pgvector ext
  alembic/versions/f4b8d2e9a713_add_scil_cache_scope_key.py
  alembic/versions/c9a4f1e08b3d_add_scil_entity_memory.py  # scil_entity_memory table
  app/embeddings.py                                        # shared 384-dim embedder
  app/models/scil.py                                       # SQLAlchemy models
  app/schemas/scil.py                                      # API response shapes
  app/schemas/agents.py                                    # ScilAgentConfig (config validation)
  app/scil/{normalizer,cache,validators,corrector,exemplars,templates,runner,metrics}.py
  app/scil/hallucination.py                                # LLM-judge groundedness check (opt-in)
  app/scil/entities.py                                     # entity resolution (opt-in, no LLM call)
  app/scil_api/router.py                                   # /api/scil/* (incl. /entities)
  app/playground_api/router.py                             # integration point — _run_turn has the
                                                             # full retry loop; _stream_turn does not
  app/chat_api/router.py                                   # /chat/message (_run_turn, retries) vs
                                                             # /chat/message/stream (_stream_turn, no retries)
  app/tool_registry/data_query_tool.py                     # the tool type entities.py detects (row_count shape)
  scripts/enable_scil.py                                   # fleet enablement (sets no validators by default)
  tests/{test_scil,test_scil_correction,test_scil_p4,test_scil_hallucination,test_scil_entities}.py
frontend/
  src/api/scil.ts                                          # react-query hooks
  src/pages/ScilDashboardPage.tsx                          # the dashboard
  src/components/Layout.tsx, src/App.tsx                   # nav + route
```
