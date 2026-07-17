import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { useCreateAccessPolicy, useUpdateAccessPolicy } from '../../api/accessPolicies'
import type { AccessPolicy, PolicyBackendType, PolicyResolverConfig, PolicyRuleMode } from '../../api/types'
import Button from '../ui/Button'
import { Ex, GuidedField } from '../ui/FieldGuide'
import Input from '../ui/Input'
import Select from '../ui/Select'

type ScopeLookupRow = { name: string; source: string; match_field: string; project: string }
type RuleRow = {
  persona: string
  mode: PolicyRuleMode
  values: string // attribute_scoped: comma-separated
  scopeName: string // id_scoped: which scope lookup to use
  argName: string // require_exact_arg
  reason: string // deny
}

function emptyRule(): RuleRow {
  return { persona: '', mode: 'global', values: '', scopeName: '', argName: '', reason: '' }
}

function emptyScopeLookup(): ScopeLookupRow {
  return { name: '', source: '', match_field: '', project: '' }
}

/** Reconstructs a RuleRow from stored rule JSON — recognizes this form's own
 * convention (`_policy_mode`/`_attr_values`/`_id_values`/`_exact_value`).
 * A rule authored some other way (e.g. credit facility's own
 * `_allowed_levels`/`_allowed_company_ids`/`_exact_gfcid` keys, written by
 * hand before this editor existed) falls back to "global" rather than
 * misrepresenting it — editing it here re-normalizes it into this
 * convention, which is a real change worth being deliberate about, not a
 * silent one. */
function parseRule(persona: string, raw: Record<string, unknown>): RuleRow {
  const row = emptyRule()
  row.persona = persona
  if (raw.__deny) {
    row.mode = 'deny'
    row.reason = String(raw.reason ?? '')
    return row
  }
  if (raw.__require_arg) {
    row.mode = 'require_exact_arg'
    row.argName = String(raw.__require_arg)
    return row
  }
  if (raw._policy_mode === 'ATTRIBUTE_SCOPED') {
    row.mode = 'attribute_scoped'
    row.values = Array.isArray(raw._attr_values) ? raw._attr_values.join(', ') : ''
  } else if (raw._policy_mode === 'ID_SCOPED') {
    row.mode = 'id_scoped'
    const ref = raw._id_values
    row.scopeName = typeof ref === 'string' && ref.startsWith('$') ? ref.slice(1) : ''
  } else {
    row.mode = 'global'
  }
  return row
}

function buildRuleJson(row: RuleRow): Record<string, unknown> {
  switch (row.mode) {
    case 'attribute_scoped':
      return {
        _policy_mode: 'ATTRIBUTE_SCOPED',
        _attr_values: row.values
          .split(',')
          .map((v) => v.trim())
          .filter(Boolean),
      }
    case 'id_scoped':
      return { _policy_mode: 'ID_SCOPED', _id_values: `$${row.scopeName}` }
    case 'require_exact_arg':
      return { __require_arg: row.argName, filter: { _policy_mode: 'EXACT', _exact_value: `{{${row.argName}}}` } }
    case 'deny':
      return { __deny: true, reason: row.reason || 'Not permitted at this access level.' }
    case 'global':
    default:
      return { _policy_mode: 'GLOBAL' }
  }
}

const RULE_MODE_OPTIONS = [
  { label: 'Global — sees everything', value: 'global' },
  { label: 'Attribute-scoped — limited to specific values', value: 'attribute_scoped' },
  { label: 'Id-scoped — limited to a coverage lookup', value: 'id_scoped' },
  { label: 'Require exact reference — no browsing', value: 'require_exact_arg' },
  { label: 'Deny — no access at all', value: 'deny' },
]

export default function AccessPolicyForm({
  policy,
  onDone,
  onCreated,
}: {
  policy?: AccessPolicy
  onDone: () => void
  /** Fires in addition to onDone with the created/updated policy — lets a
   * caller (e.g. the domain-onboarding wizard) carry the new id forward
   * without re-fetching. */
  onCreated?: (policy: AccessPolicy) => void
}) {
  const isEditing = !!policy
  const [name, setName] = useState(policy?.name ?? '')
  const [description, setDescription] = useState(policy?.description ?? '')
  const [backendType, setBackendType] = useState<PolicyBackendType>(policy?.resolver_config.type ?? 'mysql')
  const [connectionEnvPrefix, setConnectionEnvPrefix] = useState(policy?.resolver_config.connection_env_prefix ?? '')
  const [connectionEnv, setConnectionEnv] = useState(policy?.resolver_config.connection_env ?? '')
  const [database, setDatabase] = useState(policy?.resolver_config.database ?? '')
  const [identityStateKey, setIdentityStateKey] = useState(
    policy?.resolver_config.identity_state_key ?? '_principal_user_id',
  )
  const [personaSource, setPersonaSource] = useState(policy?.resolver_config.persona_lookup.source ?? '')
  const [personaMatch, setPersonaMatch] = useState(policy?.resolver_config.persona_lookup.match_field ?? 'user_id')
  const [personaProject, setPersonaProject] = useState(policy?.resolver_config.persona_lookup.project ?? 'persona')
  const [scopeLookups, setScopeLookups] = useState<ScopeLookupRow[]>(
    policy
      ? Object.entries(policy.resolver_config.scope_lookups ?? {}).map(([n, cfg]) => ({ name: n, ...cfg }))
      : [],
  )
  const [attrField, setAttrField] = useState(policy?.resolver_config.field_names?.attribute ?? '')
  const [idField, setIdField] = useState(policy?.resolver_config.field_names?.id ?? '')
  const [exactField, setExactField] = useState(policy?.resolver_config.field_names?.exact ?? '')
  const [rules, setRules] = useState<RuleRow[]>(
    policy && Object.keys(policy.rules).length > 0
      ? Object.entries(policy.rules).map(([persona, raw]) => parseRule(persona, raw))
      : [emptyRule()],
  )

  const createPolicy = useCreateAccessPolicy()
  const updatePolicy = useUpdateAccessPolicy()
  const pending = createPolicy.isPending || updatePolicy.isPending

  const usesAttrMode = rules.some((r) => r.mode === 'attribute_scoped')
  const usesIdMode = rules.some((r) => r.mode === 'id_scoped')
  const usesExactMode = rules.some((r) => r.mode === 'require_exact_arg')

  function updateRule(index: number, patch: Partial<RuleRow>) {
    setRules((rs) => rs.map((r, i) => (i === index ? { ...r, ...patch } : r)))
  }

  function updateScopeLookup(index: number, patch: Partial<ScopeLookupRow>) {
    setScopeLookups((ls) => ls.map((l, i) => (i === index ? { ...l, ...patch } : l)))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const resolver_config: PolicyResolverConfig = {
      type: backendType,
      ...(backendType === 'mysql'
        ? { connection_env_prefix: connectionEnvPrefix }
        : { connection_env: connectionEnv, database }),
      ...(identityStateKey && identityStateKey !== '_principal_user_id' ? { identity_state_key: identityStateKey } : {}),
      persona_lookup: { source: personaSource, match_field: personaMatch, project: personaProject },
      ...(attrField || idField || exactField
        ? { field_names: { attribute: attrField || undefined, id: idField || undefined, exact: exactField || undefined } }
        : {}),
      ...(scopeLookups.filter((s) => s.name).length > 0
        ? {
            scope_lookups: Object.fromEntries(
              scopeLookups
                .filter((s) => s.name)
                .map((s) => [s.name, { source: s.source, match_field: s.match_field, project: s.project }]),
            ),
          }
        : {}),
    }
    const rulesJson = Object.fromEntries(rules.filter((r) => r.persona).map((r) => [r.persona, buildRuleJson(r)]))
    const input = { name, description: description || undefined, resolver_config, rules: rulesJson }
    const onSuccess = (saved: AccessPolicy) => {
      toast.success(isEditing ? `Access policy "${name}" updated` : `Access policy "${name}" created`)
      onCreated?.(saved)
      onDone()
    }
    const onError = (err: unknown) => toast.error((err as Error).message)
    if (isEditing) {
      updatePolicy.mutate({ id: policy.id, ...input }, { onSuccess, onError })
    } else {
      createPolicy.mutate(input, { onSuccess, onError })
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <GuidedField
          label="Name"
          guide={{
            title: 'Policy name',
            what: 'An identifier for this row-level security policy.',
            why: 'Query tools reference the policy by it — one policy can gate many tools across the domain.',
            example: <Ex>sales_region_access</Ex>,
          }}
        >
          <Input required label="Name" value={name} onChange={(e) => setName(e.target.value)} />
        </GuidedField>
        <GuidedField
          label="Description"
          guide={{
            title: 'Policy description',
            what: 'One line on who sees what.',
            why: 'Your future self auditing access six months from now will thank you.',
            example: <Ex>Reps see own region; managers see all</Ex>,
          }}
        >
          <Input label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        </GuidedField>
      </div>

      <fieldset className="space-y-3 rounded-md border border-slate-200 p-3 dark:border-slate-700">
        <legend className="px-1 text-xs font-semibold uppercase text-slate-500">Data connection</legend>
        <GuidedField
          label="Backend"
          guide={{
            title: 'Policy backend',
            what: 'Where the persona/coverage lookup tables live.',
            why: 'Usually the same database as the domain data — the policy engine queries it to resolve each user\'s persona at chat time.',
          }}
        >
          <Select
            label="Backend"
            value={backendType}
            onChange={(e) => setBackendType(e.target.value as PolicyBackendType)}
            options={[
              { label: 'MySQL', value: 'mysql' },
              { label: 'MongoDB', value: 'mongo' },
            ]}
          />
        </GuidedField>
        {backendType === 'mysql' ? (
          <GuidedField
            label="Connection env var prefix"
            guide={{
              title: 'Connection env prefix',
              what: 'The {PREFIX} of the _HOST/_USER/_PASSWORD/_DATABASE group in the backend\'s .env to connect with.',
              why: 'Resolved server-side at chat time — credentials never live in this form or the database.',
              example: <Ex>CREDIT_FACILITY_MYSQL</Ex>,
              warn: 'Must already exist in backend/.env — this form can\'t create it.',
            }}
          >
            <Input
              label="Connection env var prefix"
              value={connectionEnvPrefix}
              onChange={(e) => setConnectionEnvPrefix(e.target.value)}
              placeholder="MY_DOMAIN_MYSQL"
            />
          </GuidedField>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Connection env var name"
              hideLabel={false}
              value={connectionEnv}
              onChange={(e) => setConnectionEnv(e.target.value)}
              placeholder="MY_DOMAIN_MONGO_URI"
            />
            <Input label="Database name" hideLabel={false} value={database} onChange={(e) => setDatabase(e.target.value)} />
          </div>
        )}
        <GuidedField
          label="Identity to match on"
          guide={{
            title: 'Identity key',
            what: 'Which trusted identity from the chat session is matched against the persona table.',
            why: 'The server injects it on every turn — a user cannot spoof it. Pick SOEID when the persona table is keyed by corporate ids assigned on the Users page.',
            warn: 'If persona lookups come back empty, the usual cause is this key not matching what the persona table stores.',
          }}
        >
          <Select
            label="Identity to match on"
            value={identityStateKey}
            onChange={(e) => setIdentityStateKey(e.target.value)}
            options={[
              { label: 'Agent Forge account id (default)', value: '_principal_user_id' },
              { label: 'SOEID (corporate id)', value: '_principal_soeid' },
            ]}
          />
        </GuidedField>
      </fieldset>

      <fieldset className="space-y-3 rounded-md border border-slate-200 p-3 dark:border-slate-700">
        <legend className="px-1 text-xs font-semibold uppercase text-slate-500">Persona lookup</legend>
        <p className="text-xs text-slate-400">
          How to find each user's persona — a table/collection with one row per identity.
        </p>
        <div className="grid grid-cols-3 gap-3">
          <Input label="Table / collection" hideLabel={false} value={personaSource} onChange={(e) => setPersonaSource(e.target.value)} />
          <Input label="Match column" hideLabel={false} value={personaMatch} onChange={(e) => setPersonaMatch(e.target.value)} />
          <Input label="Persona column" hideLabel={false} value={personaProject} onChange={(e) => setPersonaProject(e.target.value)} />
        </div>
      </fieldset>

      <fieldset className="space-y-3 rounded-md border border-slate-200 p-3 dark:border-slate-700">
        <legend className="px-1 text-xs font-semibold uppercase text-slate-500">
          Coverage lookups (optional, for "id-scoped" rules)
        </legend>
        {scopeLookups.map((lookup, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_1fr_1fr_auto] items-end gap-2">
            <Input
              label="Name"
              hideLabel={false}
              value={lookup.name}
              onChange={(e) => updateScopeLookup(i, { name: e.target.value })}
              placeholder="coverage"
            />
            <Input
              label="Table / collection"
              hideLabel={false}
              value={lookup.source}
              onChange={(e) => updateScopeLookup(i, { source: e.target.value })}
            />
            <Input
              label="Match column"
              hideLabel={false}
              value={lookup.match_field}
              onChange={(e) => updateScopeLookup(i, { match_field: e.target.value })}
            />
            <Input
              label="Project column"
              hideLabel={false}
              value={lookup.project}
              onChange={(e) => updateScopeLookup(i, { project: e.target.value })}
            />
            <Button
              type="button"
              variant="ghost"
              tone="danger"
              size="icon"
              onClick={() => setScopeLookups((ls) => ls.filter((_, idx) => idx !== i))}
              aria-label="Remove coverage lookup"
              className="mb-1.5"
            >
              <Trash2 size={15} />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="ghost"
          tone="brand"
          size="xs"
          onClick={() => setScopeLookups((ls) => [...ls, emptyScopeLookup()])}
          leftIcon={<Plus size={13} />}
        >
          Add coverage lookup
        </Button>
      </fieldset>

      {(usesAttrMode || usesIdMode || usesExactMode) && (
        <fieldset className="space-y-3 rounded-md border border-slate-200 p-3 dark:border-slate-700">
          <legend className="px-1 text-xs font-semibold uppercase text-slate-500">
            Column names the rules below enforce against
          </legend>
          {usesAttrMode && (
            <Input
              label="Attribute-scoped column"
              hideLabel={false}
              value={attrField}
              onChange={(e) => setAttrField(e.target.value)}
              placeholder="e.g. company_level"
            />
          )}
          {usesIdMode && (
            <Input
              label="Id-scoped column"
              hideLabel={false}
              value={idField}
              onChange={(e) => setIdField(e.target.value)}
              placeholder="e.g. company_id"
            />
          )}
          {usesExactMode && (
            <Input
              label="Exact-match column"
              hideLabel={false}
              value={exactField}
              onChange={(e) => setExactField(e.target.value)}
              placeholder="e.g. gfcid"
            />
          )}
          <p className="text-xs text-slate-400">
            A tool wired to this policy auto-scaffolds a WHERE clause using these column names — see the Access
            Policy picker in the Tool Builder.
          </p>
        </fieldset>
      )}

      <fieldset className="space-y-3 rounded-md border border-slate-200 p-3 dark:border-slate-700">
        <legend className="px-1 text-xs font-semibold uppercase text-slate-500">Rules — one per persona value</legend>
        {rules.map((rule, i) => (
          <div key={i} className="space-y-2 rounded border border-slate-100 p-2 dark:border-slate-800">
            <div className="flex items-center gap-2">
              <div className="flex-1">
                <Input
                  label="Persona value"
                  value={rule.persona}
                  onChange={(e) => updateRule(i, { persona: e.target.value })}
                  placeholder="Persona value, e.g. GCM"
                />
              </div>
              <div className="flex-1">
                <Select
                  label="Rule mode"
                  value={rule.mode}
                  onChange={(e) => updateRule(i, { mode: e.target.value as PolicyRuleMode })}
                  options={RULE_MODE_OPTIONS}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                tone="danger"
                size="icon"
                onClick={() => setRules((rs) => rs.filter((_, idx) => idx !== i))}
                aria-label="Remove rule"
              >
                <Trash2 size={15} />
              </Button>
            </div>
            {rule.mode === 'attribute_scoped' && (
              <Input
                label="Allowed values"
                value={rule.values}
                onChange={(e) => updateRule(i, { values: e.target.value })}
                placeholder="Allowed values, comma-separated (e.g. L3, L4)"
              />
            )}
            {rule.mode === 'id_scoped' && (
              <Select
                label="Coverage lookup"
                value={rule.scopeName}
                onChange={(e) => updateRule(i, { scopeName: e.target.value })}
                placeholder="Pick a coverage lookup…"
                options={scopeLookups.filter((s) => s.name).map((s) => ({ label: s.name, value: s.name }))}
              />
            )}
            {rule.mode === 'require_exact_arg' && (
              <Input
                label="Tool arg name"
                value={rule.argName}
                onChange={(e) => updateRule(i, { argName: e.target.value })}
                placeholder="Tool arg name the caller must supply, e.g. gfcid"
              />
            )}
            {rule.mode === 'deny' && (
              <Input
                label="Deny reason"
                value={rule.reason}
                onChange={(e) => updateRule(i, { reason: e.target.value })}
                placeholder="Reason shown to the user"
              />
            )}
          </div>
        ))}
        <Button
          type="button"
          variant="ghost"
          tone="brand"
          size="xs"
          onClick={() => setRules((rs) => [...rs, emptyRule()])}
          leftIcon={<Plus size={13} />}
        >
          Add persona rule
        </Button>
      </fieldset>

      <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
        <Button type="button" variant="outline" tone="neutral" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" isPending={pending} loadingLabel="Saving…">
          {isEditing ? 'Save changes' : 'Create access policy'}
        </Button>
      </div>
    </form>
  )
}

export type { RuleRow, ScopeLookupRow }
export { buildRuleJson, parseRule }
