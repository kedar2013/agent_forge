import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScilAgentConfig(BaseModel):
    """Per-agent SCIL (Self-Correcting Intelligence Layer) settings — see
    app/scil/runner.get_scil_config, which independently re-parses the raw
    dict defensively so a hand-edited/legacy model_config missing this
    structure never breaks agent invocation. This schema exists so the
    field actually round-trips through POST/PATCH /api/agents instead of
    being silently dropped by ModelConfig's default extra="ignore"
    behavior."""

    enabled: bool = False
    cache_similarity_threshold: float = 0.80
    cache_ttl_hours: int | None = None
    # "global" (default) or "user" — per-user cache partitioning, required
    # for RLS-scoped agents (see app/scil/runner.ScilConfig.scope_key).
    cache_scope: Literal["global", "user"] = "global"
    max_retries: int = 2
    exemplar_top_k: int = 3
    # Model cascading (see app/agent_runtime/cascade.py) — once a validator
    # flags a low-confidence first attempt, retries run on this model
    # instead of the agent's own, up to escalation_max_cost_usd if set.
    escalation_model: str | None = None
    escalation_max_cost_usd: float | None = None
    validators: list[str] = Field(default_factory=list)
    templates_enabled: bool = False
    # [{"pattern": "<regex with named groups>", "response_text": "...{slot}..."}]
    # — see app/scil/templates.py for matching semantics.
    templates: list[dict] = Field(default_factory=list)
    # Only meaningful when "hallucination" is in `validators`. The
    # zero-tool-call check is always-on and free; this adds a second,
    # LLM-judge groundedness pass (extra latency/cost) — see
    # app/scil/hallucination.check_groundedness.
    hallucination_groundedness_check: bool = False
    # "entity_resolution" in `validators` (a fourth recognized value,
    # alongside "sql"/"json_schema"/"hallucination") turns on
    # app/scil/entities.py: a data_query_tool call that runs cleanly but
    # returns zero rows because the searched-for literal was misspelled gets
    # matched against this agent's own scil_entity_memory (sentence-transformer
    # + lexical similarity) and retried with the likely-correct value if a
    # confident match exists. No config flag beyond the validators-list entry
    # — same pattern as "sql"/"json_schema", free/deterministic-cost, no LLM
    # call (only an embedding lookup).


class GuardrailsInputConfig(BaseModel):
    prompt_injection_check: bool = True
    jailbreak_check: bool = True
    # Free-text description of what this agent should answer — judged by an
    # LLM call, so topical_scope_check defaults off even when guardrails
    # overall are on; see app/guardrails/config.py.
    topical_scope: str | None = None
    topical_scope_check: bool = False


class GuardrailsOutputConfig(BaseModel):
    pii_check: bool = True
    mnpi_check: bool = True
    toxicity_check: bool = True
    # Merged with (not replacing) the platform-wide GUARDRAILS_MNPI_TERMS_RAW
    # list at check time — see app/guardrails/config.get_guardrails_config.
    mnpi_terms: list[str] = Field(default_factory=list)
    action: Literal["block", "redact"] = "block"


class GuardrailsAgentConfig(BaseModel):
    """Round-trips through POST/PATCH /api/agents the same way
    ScilAgentConfig does — this schema existing (not just the free-form
    dict `model_config_json` column) is what lets a `model_config.guardrails`
    value survive request validation instead of being silently stripped by
    ModelConfig's default extra="ignore" behavior. See
    app/guardrails/config.get_guardrails_config for how the platform default
    (Settings.guardrails_enabled/guardrails_judge_enabled) layers under
    whatever this agent explicitly sets."""

    enabled: bool = True
    input: GuardrailsInputConfig = Field(default_factory=GuardrailsInputConfig)
    output: GuardrailsOutputConfig = Field(default_factory=GuardrailsOutputConfig)
    block_message: str | None = None


class ModelConfig(BaseModel):
    model: str = "gemini-3.5-flash"
    temperature: float = 0.3
    scil: ScilAgentConfig | None = None
    guardrails: GuardrailsAgentConfig | None = None


class AgentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str | None = None
    base_instruction: str
    model_settings: ModelConfig = Field(default_factory=ModelConfig, alias="model_config")
    output_schema: dict | None = None
    output_key: str | None = None
    created_by: str | None = None
    workspace_id: uuid.UUID | None = None


class AgentUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    description: str | None = None
    base_instruction: str | None = None
    model_settings: ModelConfig | None = Field(default=None, alias="model_config")
    output_schema: dict | None = None
    output_key: str | None = None


class AttachToolRequest(BaseModel):
    tool_id: uuid.UUID


class AttachSkillRequest(BaseModel):
    skill_id: uuid.UUID
    attach_order: int = 0


class AttachSubagentRequest(BaseModel):
    child_agent_id: uuid.UUID


class AddCollaboratorRequest(BaseModel):
    user_email: str


class CollaboratorEntry(BaseModel):
    user_email: str
    added_by: str | None
    created_at: datetime


class PublishRequest(BaseModel):
    published_by: str | None = None


class AttachedToolRead(BaseModel):
    id: uuid.UUID
    name: str
    tool_type: str


class AttachedSkillRead(BaseModel):
    id: uuid.UUID
    name: str
    instruction_text: str
    attach_order: int


class AttachedSubagentRead(BaseModel):
    id: uuid.UUID
    name: str


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    workspace_id: uuid.UUID | None
    name: str
    description: str | None
    base_instruction: str
    model_settings: dict = Field(alias="model_config")
    output_schema: dict | None = None
    output_key: str | None = None
    status: Literal["draft", "published", "archived"]
    current_version: int
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    tools: list[AttachedToolRead] = []
    skills: list[AttachedSkillRead] = []
    sub_agents: list[AttachedSubagentRead] = []


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    version: int
    snapshot: dict
    published_by: str | None
    published_at: datetime


class PublishRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    status: Literal["pending", "approved", "rejected"]
    requested_by: str | None
    review_note: str | None
    decided_by: str | None
    decided_at: datetime | None
    published_version: int | None
    created_at: datetime


class PublishResult(BaseModel):
    """Response of POST /agents/{id}/publish. An admin's call publishes right
    away (`status="published"`, `version` populated). A developer's call only
    files a review request (`status="pending_approval"`, `publish_request`
    populated, `version` is None) — an admin has to separately approve it via
    /agents/publish-requests/{id}/approve before it actually goes live."""

    status: Literal["published", "pending_approval"]
    version: AgentVersionRead | None = None
    publish_request: PublishRequestRead | None = None


class ReviewPublishRequest(BaseModel):
    review_note: str | None = None
