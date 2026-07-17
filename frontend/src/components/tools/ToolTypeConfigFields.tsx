import { useAccessPolicies } from '../../api/accessPolicies'
import { useDataEntities } from '../../api/dataEntities'
import type { AccessPolicy, ToolType } from '../../api/types'

type Config = Record<string, any>

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      <input
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function TextArea({
  label,
  value,
  onChange,
  placeholder,
  rows = 4,
  mono = true,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  rows?: number
  mono?: boolean
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      <textarea
        className={`w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 ${mono ? 'font-mono' : ''}`}
        style={{ height: `${rows * 1.5}rem` }}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function csvToList(v: string): string[] {
  return v
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

/** The same 4-branch OR-chain `_POLICY_WHERE_FRAGMENT` pattern
 * backend/app/domains/credit_facility/seed_agent.py hand-writes, generated
 * from a policy's own `field_names` (see AccessPolicyForm.tsx) — turns
 * "remember the reserved-key contract" into "pick a policy from a dropdown". */
function buildPolicyWhereFragment(policy: AccessPolicy): string {
  const fields = policy.resolver_config.field_names ?? {}
  const branches = ["%(_policy_mode)s = 'GLOBAL'"]
  if (fields.attribute) branches.push(`(%(_policy_mode)s = 'ATTRIBUTE_SCOPED' AND ${fields.attribute} IN %(_attr_values)s)`)
  if (fields.id) branches.push(`(%(_policy_mode)s = 'ID_SCOPED' AND ${fields.id} IN %(_id_values)s)`)
  if (fields.exact) branches.push(`(%(_policy_mode)s = 'EXACT' AND ${fields.exact} = %(_exact_value)s)`)
  return `(\n    ${branches.join('\n    OR ')}\n  )`
}

function PolicyPicker({
  policyId,
  onChange,
  onPickedPolicy,
}: {
  policyId: string
  onChange: (id: string) => void
  onPickedPolicy?: (policy: AccessPolicy | undefined) => void
}) {
  const { data: policies } = useAccessPolicies()
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">Access policy (optional — row-level security)</span>
      <select
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        value={policyId}
        onChange={(e) => {
          onChange(e.target.value)
          onPickedPolicy?.(policies?.find((p) => p.id === e.target.value))
        }}
      >
        <option value="">None — no access restriction</option>
        {policies?.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  )
}

function EntityPicker({ entityId, onChange }: { entityId: string; onChange: (id: string) => void }) {
  const { data: entities } = useDataEntities()
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">Data entity</span>
      <select
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        value={entityId}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Select a data entity…</option>
        {entities?.map((entity) => (
          <option key={entity.id} value={entity.id}>
            {entity.name} ({entity.source.table || entity.source.collection})
          </option>
        ))}
      </select>
      {!entities?.length && (
        <span className="mt-1 block text-xs text-amber-600 dark:text-amber-400">
          No data entities yet — create one on the Data Entities page first.
        </span>
      )}
    </label>
  )
}

export default function ToolTypeConfigFields({
  toolType,
  config,
  onChange,
}: {
  toolType: ToolType
  config: Config
  onChange: (config: Config) => void
}) {
  const set = (patch: Config) => onChange({ ...config, ...patch })

  if (toolType === 'http_tool') {
    const auth = config.auth ?? { type: 'none' }
    return (
      <div className="space-y-3">
        <Field
          label="Base URL"
          value={config.base_url ?? ''}
          onChange={(v) => set({ base_url: v })}
          placeholder="https://api.example.com"
        />
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Method</span>
          <select
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            value={config.method ?? 'GET'}
            onChange={(e) => set({ method: e.target.value })}
          >
            {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <Field
          label="Path template"
          value={config.path_template ?? ''}
          onChange={(v) => set({ path_template: v })}
          placeholder="/weather/{city}"
        />
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Auth type</span>
          <select
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            value={auth.type}
            onChange={(e) => set({ auth: { ...auth, type: e.target.value } })}
          >
            <option value="none">none</option>
            <option value="api_key">api_key</option>
            <option value="bearer">bearer</option>
          </select>
        </label>
        {auth.type === 'api_key' && (
          <Field
            label="Header name"
            value={auth.header_name ?? ''}
            onChange={(v) => set({ auth: { ...auth, header_name: v } })}
            placeholder="X-API-Key"
          />
        )}
        {auth.type !== 'none' && (
          <Field
            label="Secret env var name"
            value={auth.secret_env ?? ''}
            onChange={(v) => set({ auth: { ...auth, secret_env: v } })}
            placeholder="WEATHER_API_KEY"
          />
        )}
        <Field
          label="Timeout (seconds)"
          value={String(config.timeout_seconds ?? 10)}
          onChange={(v) => set({ timeout_seconds: Number(v) || 10 })}
        />
      </div>
    )
  }

  if (toolType === 'data_query_tool') {
    return (
      <div className="space-y-3">
        <EntityPicker entityId={config.entity_id ?? ''} onChange={(id) => set({ entity_id: id || undefined })} />
        <PolicyPicker policyId={config.policy_id ?? ''} onChange={(id) => set({ policy_id: id || undefined })} />
        <p className="text-xs text-slate-400">
          The LLM writes the SQL itself, guided by the entity's own field list — description and input schema are
          composed automatically when you save, nothing else to configure here.
        </p>
      </div>
    )
  }

  if (toolType === 'sql_tool') {
    return (
      <div className="space-y-3">
        <Field
          label="Connection env var name"
          value={config.connection_env ?? ''}
          onChange={(v) => set({ connection_env: v })}
          placeholder="AGENT_FORGE_READONLY_DB_URL"
        />
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Query template (locked, params via :name)</span>
          <textarea
            className="h-24 w-full rounded border border-slate-300 px-2 py-1 font-mono text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            value={config.query_template ?? ''}
            onChange={(e) => set({ query_template: e.target.value })}
            placeholder="SELECT * FROM company WHERE industry = :industry LIMIT :limit"
          />
        </label>
      </div>
    )
  }

  if (toolType === 'mysql_query_tool') {
    return (
      <div className="space-y-3">
        <Field
          label="Connection env var prefix"
          value={config.connection_env_prefix ?? ''}
          onChange={(v) => set({ connection_env_prefix: v })}
          placeholder="CREDIT_FACILITY_MYSQL"
        />
        <TextArea
          label="Query (params via %(name)s — structure fixed, LLM only binds values)"
          rows={8}
          value={config.query ?? ''}
          onChange={(v) => set({ query: v })}
          placeholder="SELECT * FROM my_table WHERE (%(id)s IS NULL OR id = %(id)s) AND ..."
        />
        <Field
          label="Optional scalar args (comma-separated)"
          value={(config.optional_scalar_args ?? []).join(', ')}
          onChange={(v) => set({ optional_scalar_args: csvToList(v) })}
          placeholder="company_id, gfcid"
        />
        <Field
          label="Optional list args (comma-separated)"
          value={(config.optional_list_args ?? []).join(', ')}
          onChange={(v) => set({ optional_list_args: csvToList(v) })}
          placeholder="load_ids"
        />
        <Field
          label="Name-search args to LIKE-wrap (comma-separated)"
          value={(config.like_wrap_args ?? []).join(', ')}
          onChange={(v) => set({ like_wrap_args: csvToList(v) })}
          placeholder="name_query"
        />
        <Field
          label="Max rows"
          value={String(config.max_rows ?? 50)}
          onChange={(v) => set({ max_rows: Number(v) || 50 })}
        />
        <PolicyPicker
          policyId={config.policy_id ?? ''}
          onChange={(id) => set({ policy_id: id || undefined })}
          onPickedPolicy={(policy) => {
            if (!policy || (config.query ?? '').includes('_policy_mode')) return
            const fragment = buildPolicyWhereFragment(policy)
            const base = (config.query ?? '').trim()
            const joined = base ? `${base}\n  AND ${fragment}` : `WHERE ${fragment}`
            set({ query: joined })
          }}
        />
      </div>
    )
  }

  if (toolType === 'mongo_query_tool') {
    return (
      <div className="space-y-3">
        <Field
          label="Connection env var name"
          value={config.connection_env ?? ''}
          onChange={(v) => set({ connection_env: v })}
          placeholder="MY_DOMAIN_MONGO_URI"
        />
        <Field
          label="Database"
          value={config.database ?? ''}
          onChange={(v) => set({ database: v })}
        />
        <Field
          label="Collection"
          value={config.collection ?? ''}
          onChange={(v) => set({ collection: v })}
        />
        <TextArea
          label="Filter template (JSON — {{arg}} leaves bind LLM values, structure stays fixed)"
          rows={5}
          value={JSON.stringify(config.filter_template ?? {}, null, 2)}
          onChange={(v) => {
            try {
              set({ filter_template: JSON.parse(v) })
            } catch {
              /* keep typing until it's valid JSON again */
            }
          }}
        />
        <Field
          label="Max rows"
          value={String(config.max_limit ?? 50)}
          onChange={(v) => set({ max_limit: Number(v) || 50, limit: Number(v) || 50 })}
        />
        <PolicyPicker policyId={config.policy_id ?? ''} onChange={(id) => set({ policy_id: id || undefined })} />
        <p className="text-xs text-slate-400">
          Row-level security for Mongo is enforced via a reserved <code>_enforced_filter</code> key the policy's
          rules should produce — see <code>mongo_tool.py</code>'s docstring.
        </p>
      </div>
    )
  }

  if (toolType === 'mcp_tool') {
    return (
      <div className="space-y-3">
        <Field
          label="MCP server URL"
          value={config.server_url ?? ''}
          onChange={(v) => set({ server_url: v })}
          placeholder="https://mcp.example.com/mcp"
        />
        <Field
          label="Tool name (on that server)"
          value={config.tool_name ?? ''}
          onChange={(v) => set({ tool_name: v })}
          placeholder="get_weather"
        />
        <Field
          label="Auth header env var (optional)"
          value={config.auth_header_env ?? ''}
          onChange={(v) => set({ auth_header_env: v })}
          placeholder="MCP_AUTH_TOKEN"
        />
      </div>
    )
  }

  // retrieval_tool
  return (
    <div className="space-y-3">
      <Field
        label="Connection env var name"
        value={config.connection_env ?? ''}
        onChange={(v) => set({ connection_env: v })}
        placeholder="DATABASE_URL"
      />
      <Field
        label="Table (schema-qualified)"
        value={config.table ?? ''}
        onChange={(v) => set({ table: v })}
        placeholder="public.document_chunks"
      />
      <Field
        label="Embedding column"
        value={config.embedding_column ?? 'embedding'}
        onChange={(v) => set({ embedding_column: v })}
      />
      <Field
        label="Text column"
        value={config.text_column ?? 'content'}
        onChange={(v) => set({ text_column: v })}
      />
      <Field
        label="Top K"
        value={String(config.top_k ?? 5)}
        onChange={(v) => set({ top_k: Number(v) || 5 })}
      />
    </div>
  )
}
