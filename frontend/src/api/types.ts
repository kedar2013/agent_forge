export type ToolType =
  | 'http_tool'
  | 'sql_tool'
  | 'mcp_tool'
  | 'retrieval_tool'
  | 'image_gen_tool'
  | 'db_schema_tool'
  | 'nl2sql_query_tool'
  | 'mongo_query_tool'
  | 'mysql_query_tool'
  | 'data_query_tool'
export type AgentStatus = 'draft' | 'published' | 'archived'

export interface JsonSchemaProperty {
  type: string
  description?: string
}

export interface JsonSchema {
  type: 'object'
  properties: Record<string, JsonSchemaProperty>
  required?: string[]
}

export interface Tool {
  id: string
  workspace_id: string | null
  name: string
  tool_type: ToolType
  config: Record<string, unknown>
  input_schema: JsonSchema
  description: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface ToolCreateInput {
  name: string
  tool_type: ToolType
  config: Record<string, unknown>
  input_schema: JsonSchema
  description?: string
}

// --- Access policies (row-level security for mysql_query_tool/mongo_query_tool) ---

export type PolicyBackendType = 'mysql' | 'mongo'

export type PolicyRuleMode = 'global' | 'attribute_scoped' | 'id_scoped' | 'require_exact_arg' | 'deny'

export interface PolicyScopeLookup {
  source: string
  match_field: string
  project: string
}

export interface PolicyResolverConfig {
  type: PolicyBackendType
  connection_env?: string // mongo
  database?: string // mongo
  connection_env_prefix?: string // mysql
  identity_state_key?: string // defaults to "_principal_user_id"; set to "_principal_soeid" to key by SOEID
  persona_lookup: PolicyScopeLookup
  scope_lookups?: Record<string, PolicyScopeLookup>
  // Column names the generated rules' _attr_values/_id_values/_exact_value
  // enforce against — read by the Tool Builder's Access Policy picker to
  // auto-scaffold a matching WHERE clause for a mysql_query_tool. Only
  // meaningful alongside this form's own rule convention (see
  // AccessPolicyForm.tsx) — not used by policy_engine.py itself.
  field_names?: { attribute?: string; id?: string; exact?: string }
}

// One rule per persona/discriminator value — raw JSON as ultimately stored
// (see backend/app/tool_registry/policy_engine.py), plus the UI-only `mode`
// tag so the structured editor can round-trip a rule it generated. A rule
// loaded from outside the editor (hand-authored) may have no recognizable
// mode; the editor falls back to a raw-JSON view for those.
export interface PolicyRule {
  mode: PolicyRuleMode
  // attribute_scoped
  field?: string
  values?: string[]
  // id_scoped
  scope_name?: string
  id_field?: string
  // require_exact_arg
  arg_name?: string
  filter?: Record<string, unknown>
  // deny
  reason?: string
  raw?: Record<string, unknown> // escape hatch: unrecognized shape, edited as JSON
}

export interface AccessPolicy {
  id: string
  workspace_id: string | null
  name: string
  description: string | null
  resolver_config: PolicyResolverConfig
  rules: Record<string, Record<string, unknown>>
  created_at: string
  updated_at: string
}

export interface AccessPolicyCreateInput {
  name: string
  description?: string
  resolver_config: PolicyResolverConfig
  rules: Record<string, Record<string, unknown>>
}

export interface AccessPolicyUpdateInput {
  name?: string
  description?: string
  resolver_config?: PolicyResolverConfig
  rules?: Record<string, Record<string, unknown>>
}

// --- Data entities (the data dictionary a data_query_tool points at) ---

export interface DataField {
  name: string
  label?: string
  type: string
  searchable?: boolean
  filterable?: boolean
  visible?: boolean
  measure?: boolean
  format?: 'text' | 'currency' | 'percent' | 'date' | 'integer'
  enum?: string[]
}

export interface DataConnection {
  type: PolicyBackendType
  connection_env_prefix?: string // mysql
  connection_env?: string // mongo
  database?: string // mongo
}

export interface DataSource {
  table?: string // mysql
  collection?: string // mongo
  primary_key?: string
}

export interface DataEntity {
  id: string
  workspace_id: string | null
  name: string
  description: string | null
  connection: DataConnection
  source: DataSource
  fields: DataField[]
  default_sort: { field: string; dir: 'asc' | 'desc' } | null
  default_limit: number
  max_limit: number
  created_at: string
  updated_at: string
}

export interface DataEntityCreateInput {
  name: string
  description?: string
  connection: DataConnection
  source: DataSource
  fields: DataField[]
  default_sort?: { field: string; dir: 'asc' | 'desc' }
  default_limit?: number
  max_limit?: number
}

export interface DataEntityUpdateInput {
  name?: string
  description?: string
  connection?: DataConnection
  source?: DataSource
  fields?: DataField[]
  default_sort?: { field: string; dir: 'asc' | 'desc' }
  default_limit?: number
  max_limit?: number
}

export interface IntrospectedField {
  name: string
  type: string
}

export interface ConnectionInfo {
  prefix: string
  database: string
  host: string
  port: number
}

export interface TableInfo {
  name: string
  column_count: number
  row_estimate: number
}

export interface TestConnectionResult {
  ok: boolean
  database: string
  table_count: number
}

export interface FewShotExample {
  input: string
  output: string
}

export interface Skill {
  id: string
  workspace_id: string | null
  name: string
  instruction_text: string
  few_shot_examples: FewShotExample[] | null
  tags: string[] | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface SkillCreateInput {
  name: string
  instruction_text: string
  few_shot_examples?: FewShotExample[]
  tags?: string[]
}

export interface AttachedTool {
  id: string
  name: string
  tool_type: ToolType
}

export interface AttachedSkill {
  id: string
  name: string
  instruction_text: string
  attach_order: number
}

export interface AttachedSubagent {
  id: string
  name: string
}

export interface ScilConfig {
  enabled: boolean
  cache_similarity_threshold: number
  cache_ttl_hours: number | null
  cache_scope: 'global' | 'user'
  max_retries: number
  exemplar_top_k: number
  escalation_model: string | null
  validators: string[]
  templates_enabled: boolean
  templates: Record<string, unknown>[]
  /** Only meaningful when 'hallucination' is in validators. Enables an extra
   * LLM-judge groundedness check (extra cost/latency) on top of the
   * always-cheap zero-tool-call check. */
  hallucination_groundedness_check: boolean
}

export interface ModelConfig {
  model: string
  temperature: number
  scil?: ScilConfig
}

export interface Agent {
  id: string
  workspace_id: string | null
  name: string
  description: string | null
  base_instruction: string
  model_config: ModelConfig
  output_schema: Record<string, unknown> | null
  output_key: string | null
  status: AgentStatus
  current_version: number
  created_by: string | null
  created_at: string
  updated_at: string
  tools: AttachedTool[]
  skills: AttachedSkill[]
  sub_agents: AttachedSubagent[]
}

export interface AgentCreateInput {
  name: string
  description?: string
  base_instruction: string
  model_config?: ModelConfig
  output_schema?: Record<string, unknown> | null
  output_key?: string | null
}

export interface AgentUpdateInput {
  name?: string
  description?: string
  base_instruction?: string
  model_config?: ModelConfig
  output_schema?: Record<string, unknown> | null
  output_key?: string | null
}

export interface AgentVersion {
  id: string
  agent_id: string
  version: number
  snapshot: {
    name: string
    description: string | null
    base_instruction: string
    model_config: ModelConfig
    output_schema?: Record<string, unknown> | null
    output_key?: string | null
    tools: { id: string; name: string }[]
    skills: { id: string; name: string; attach_order: number }[]
    sub_agents: { id: string; name: string }[]
  }
  published_by: string | null
  published_at: string
}

export type PublishRequestStatus = 'pending' | 'approved' | 'rejected'

export interface PublishRequest {
  id: string
  agent_id: string
  status: PublishRequestStatus
  requested_by: string | null
  review_note: string | null
  decided_by: string | null
  decided_at: string | null
  published_version: number | null
  created_at: string
}

// Response of POST /agents/{id}/publish — an admin publishes immediately
// (`version` set), a developer only files a review request (`publish_request`
// set, `version` is null) that an admin later approves/rejects.
export interface PublishResult {
  status: 'published' | 'pending_approval'
  version: AgentVersion | null
  publish_request: PublishRequest | null
}

export interface ToolCallTrace {
  name: string
  input: Record<string, unknown>
  output: unknown
}

export interface PlaygroundRunRequest {
  agent_id: string
  message: string
  user_id?: string
  session_id?: string
  state_delta?: Record<string, unknown>
}

export interface PlaygroundRunResponse {
  response_text: string
  tool_calls: ToolCallTrace[]
  latency_ms: number
  session_id: string
}

export interface MonitoringSummary {
  total_invocations: number
  error_rate: number
  p50_latency_ms: number | null
  p95_latency_ms: number | null
  p99_latency_ms: number | null
  active_agents_count: number
}

export interface AgentHealthRow {
  agent_id: string
  name: string
  status: AgentStatus
  invocation_count: number
  error_rate: number
  p95_latency_ms: number | null
  last_invocation_at: string | null
}

export interface ToolHealthRow {
  tool_id: string | null
  name: string
  tool_type: ToolType
  call_count: number
  error_rate: number
  avg_latency_ms: number | null
}

export interface UsageSummary {
  total_invocations: number
  total_cost_usd: number
  total_tokens: number
  unique_agents: number
}

export interface UsageTimeseriesPoint {
  date: string
  agent_id: string
  agent_name: string
  invocations: number
  cost_usd: number
}

export interface AgentUsageRow {
  agent_id: string
  name: string
  invocation_count: number
  total_tokens: number
  total_cost_usd: number
  avg_cost_per_invocation: number
}

export interface ToolUsageRow {
  tool_id: string | null
  name: string
  call_count: number
  agent_names: string[]
}

export interface UserUsageRow {
  user_key: string
  email: string | null
  role: 'admin' | 'viewer' | 'chat_user' | null
  invocation_count: number
  total_tokens: number
  total_cost_usd: number
  error_count: number
  last_active: string | null
}

export interface InvocationAuditRow {
  id: string
  agent_id: string | null
  agent_name: string | null
  agent_version: number
  status: string
  latency_ms: number
  input_tokens: number | null
  output_tokens: number | null
  estimated_cost_usd: number | null
  invoked_by: string | null
  trace_id: string | null
  created_at: string
}

export interface InvocationDetail extends InvocationAuditRow {
  transcript: { message?: string; response_text?: string } | null
  error_message: string | null
}

export interface ConfigAuditRow {
  id: string
  entity_type: string
  entity_id: string
  action: string
  actor: string | null
  diff: Record<string, unknown> | null
  created_at: string
}

export interface InvocationListResponse {
  items: InvocationAuditRow[]
  total: number
  limit: number
  offset: number
}

export interface ConfigChangeListResponse {
  items: ConfigAuditRow[]
  total: number
  limit: number
  offset: number
}
