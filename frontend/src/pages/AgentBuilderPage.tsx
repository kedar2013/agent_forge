import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { FlaskConical, Rocket } from 'lucide-react'
import { toast } from 'sonner'
import {
  useAgent,
  useAttachSkill,
  useAttachSubagent,
  useAttachTool,
  useCreateAgent,
  useDetachSkill,
  useDetachSubagent,
  useDetachTool,
  usePublishAgent,
  useUpdateAgent,
} from '../api/agents'
import type { ModelConfig } from '../api/types'
import EffectivePromptPreview from '../components/agents/EffectivePromptPreview'
import SkillAttachList from '../components/agents/SkillAttachList'
import SkillPicker from '../components/agents/SkillPicker'
import SubAgentAttachPanel from '../components/agents/SubAgentAttachPanel'
import ToolAttachPanel from '../components/agents/ToolAttachPanel'
import { AGENT_STATUS_TONE } from '../lib/badgeTones'
import { fingerprint, hasPassedTest, markTesting } from '../lib/testGate'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Select from '../components/ui/Select'
import Textarea from '../components/ui/Textarea'
import Toggle from '../components/ui/Toggle'

const SCIL_VALIDATOR_OPTIONS: { value: string; label: string; emphasize?: boolean }[] = [
  { value: 'sql', label: 'SQL guardrails' },
  { value: 'json_schema', label: 'JSON schema' },
  { value: 'hallucination', label: 'Hallucination detection', emphasize: true },
]

// Stored value is what agent_runtime/builder.py._resolve_model reads:
// Claude entries use the "anthropic/<model-id>" litellm routing convention
// (wrapped in ADK's LiteLlm adapter); Gemini entries are ADK's native bare
// model string. Keep in sync with backend/app/observability/pricing.py.
const MODEL_OPTIONS = [
  { group: 'Claude (Anthropic)', value: 'anthropic/claude-opus-4-8', label: 'Claude Opus 4.8' },
  { group: 'Claude (Anthropic)', value: 'anthropic/claude-sonnet-5', label: 'Claude Sonnet 5' },
  { group: 'Claude (Anthropic)', value: 'anthropic/claude-haiku-4-5', label: 'Claude Haiku 4.5' },
  { group: 'Claude (Anthropic)', value: 'anthropic/claude-opus-4-7', label: 'Claude Opus 4.7' },
  { group: 'Claude (Anthropic)', value: 'anthropic/claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { group: 'Gemini (Google)', value: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
  { group: 'Gemini (Google)', value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { group: 'Gemini (Google)', value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { group: 'Gemini (Google)', value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
]

interface Draft {
  name: string
  description: string
  base_instruction: string
  model: string
  temperature: number
  output_key: string
  output_schema_text: string
}

const EMPTY_DRAFT: Draft = {
  name: '',
  description: '',
  base_instruction: '',
  model: 'gemini-3.5-flash',
  temperature: 0.3,
  output_key: '',
  output_schema_text: '',
}

export default function AgentBuilderPage() {
  const { id } = useParams<{ id: string }>()
  const isNew = id === undefined
  const navigate = useNavigate()

  const { data: agent } = useAgent(id)
  const createAgent = useCreateAgent()
  const updateAgent = useUpdateAgent(id ?? '')
  const publishAgent = usePublishAgent(id ?? '')
  const attachTool = useAttachTool(id ?? '')
  const detachTool = useDetachTool(id ?? '')
  const attachSkill = useAttachSkill(id ?? '')
  const detachSkill = useDetachSkill(id ?? '')
  const attachSubagent = useAttachSubagent(id ?? '')
  const detachSubagent = useDetachSubagent(id ?? '')

  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [seededFor, setSeededFor] = useState<string | null>(null)
  const [schemaError, setSchemaError] = useState<string | null>(null)

  // SCIL config local state — mirrors the model/temperature pattern above:
  // seeded from agent.model_config.scil on load, folded back into
  // buildModelConfig()'s output on save.
  const [scilEnabled, setScilEnabled] = useState(false)
  const [scilValidators, setScilValidators] = useState<string[]>([])
  const [scilHallucinationGroundedness, setScilHallucinationGroundedness] = useState(false)
  const [scilCacheTtlHours, setScilCacheTtlHours] = useState<string>('')
  const [scilMaxRetries, setScilMaxRetries] = useState<string>('2')

  useEffect(() => {
    if (agent && seededFor !== agent.id) {
      setDraft({
        name: agent.name,
        description: agent.description ?? '',
        base_instruction: agent.base_instruction,
        model: agent.model_config.model,
        temperature: agent.model_config.temperature,
        output_key: agent.output_key ?? '',
        output_schema_text: agent.output_schema ? JSON.stringify(agent.output_schema, null, 2) : '',
      })
      const scil = agent.model_config.scil
      setScilEnabled(scil?.enabled ?? false)
      setScilValidators(scil?.validators ?? [])
      setScilHallucinationGroundedness(scil?.hallucination_groundedness_check ?? false)
      setScilCacheTtlHours(scil?.cache_ttl_hours != null ? String(scil.cache_ttl_hours) : '')
      setScilMaxRetries(scil?.max_retries != null ? String(scil.max_retries) : '2')
      setSeededFor(agent.id)
    }
  }, [agent, seededFor])

  function toggleScilValidator(value: string, on: boolean) {
    setScilValidators((prev) => (on ? [...prev, value] : prev.filter((v) => v !== value)))
  }

  function buildModelConfig(): ModelConfig {
    const base: ModelConfig = { model: draft.model, temperature: draft.temperature }
    if (isNew) return base
    return {
      ...base,
      scil: {
        ...agent?.model_config.scil,
        enabled: scilEnabled,
        validators: scilValidators,
        cache_ttl_hours: scilCacheTtlHours.trim() === '' ? null : Number(scilCacheTtlHours),
        max_retries: scilMaxRetries.trim() === '' ? 2 : Number(scilMaxRetries),
        hallucination_groundedness_check: scilHallucinationGroundedness,
        // Fields not exposed by this UI — preserved from the existing config,
        // with contract defaults as a fallback for brand-new SCIL configs.
        cache_similarity_threshold: agent?.model_config.scil?.cache_similarity_threshold ?? 0.80,
        cache_scope: agent?.model_config.scil?.cache_scope ?? 'global',
        exemplar_top_k: agent?.model_config.scil?.exemplar_top_k ?? 3,
        escalation_model: agent?.model_config.scil?.escalation_model ?? null,
        templates_enabled: agent?.model_config.scil?.templates_enabled ?? false,
        templates: agent?.model_config.scil?.templates ?? [],
      },
    }
  }

  function parseOutputSchema(): { ok: true; value: Record<string, unknown> | null } | { ok: false } {
    if (!draft.output_schema_text.trim()) return { ok: true, value: null }
    try {
      return { ok: true, value: JSON.parse(draft.output_schema_text) }
    } catch {
      return { ok: false }
    }
  }

  const isDirty =
    !!agent &&
    (draft.name !== agent.name ||
      draft.description !== (agent.description ?? '') ||
      draft.base_instruction !== agent.base_instruction ||
      draft.model !== agent.model_config.model ||
      draft.temperature !== agent.model_config.temperature ||
      draft.output_key !== (agent.output_key ?? '') ||
      draft.output_schema_text !== (agent.output_schema ? JSON.stringify(agent.output_schema, null, 2) : ''))

  async function handleSave() {
    const parsed = parseOutputSchema()
    if (!parsed.ok) {
      setSchemaError('Output schema must be valid JSON (or left empty).')
      return
    }
    setSchemaError(null)
    try {
      await updateAgent.mutateAsync({
        name: draft.name,
        description: draft.description,
        base_instruction: draft.base_instruction,
        model_config: buildModelConfig(),
        output_key: draft.output_key || null,
        output_schema: parsed.value,
      })
      toast.success('Changes saved')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    try {
      const created = await createAgent.mutateAsync({
        name: draft.name,
        description: draft.description,
        base_instruction: draft.base_instruction,
        model_config: buildModelConfig(),
      })
      toast.success(`Agent "${created.name}" created`)
      navigate(`/agents/${created.id}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function handleTestInPlayground() {
    if (!id || !agent) return
    if (isDirty) await handleSave()
    const fp = fingerprint({
      name: draft.name,
      description: draft.description,
      base_instruction: draft.base_instruction,
      model_config: buildModelConfig(),
      tools: agent.tools,
      skills: agent.skills,
      sub_agents: agent.sub_agents,
    })
    markTesting(id, fp)
    navigate(`/agents/${id}/playground`)
  }

  async function handlePublish() {
    try {
      const result = await publishAgent.mutateAsync(undefined)
      if (result.status === 'pending_approval') {
        toast.success('Publish request submitted — an admin needs to approve it before this goes live.')
      } else if (result.version) {
        toast.success(`Published version ${result.version.version}`)
      }
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  function handleReorderSkills(newOrderIds: string[]) {
    newOrderIds.forEach((skillId, index) => {
      attachSkill.mutate({ skill_id: skillId, attach_order: index })
    })
  }

  if (isNew) {
    return (
      <div className="max-w-xl">
        <h1 className="mb-4 text-xl font-semibold">New Agent</h1>
        <Card>
          <form onSubmit={handleCreate} className="space-y-3">
            <Input
              label="Name"
              hideLabel={false}
              required
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
            <Input
              label="Description"
              hideLabel={false}
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
            <Textarea
              label="Base instruction"
              hideLabel={false}
              required
              className="h-40"
              value={draft.base_instruction}
              onChange={(e) => setDraft({ ...draft, base_instruction: e.target.value })}
            />
            <div className="flex gap-3">
              <div className="flex-1">
                <Select
                  label="Model"
                  hideLabel={false}
                  value={draft.model}
                  onChange={(e) => setDraft({ ...draft, model: e.target.value })}
                  options={MODEL_OPTIONS}
                />
              </div>
              <div className="w-32">
                <Input
                  label="Temperature"
                  hideLabel={false}
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={draft.temperature}
                  onChange={(e) => setDraft({ ...draft, temperature: Number(e.target.value) })}
                />
              </div>
            </div>
            <Button type="submit" isPending={createAgent.isPending} loadingLabel="Creating…">
              Create agent
            </Button>
          </form>
        </Card>
      </div>
    )
  }

  if (!agent) return <p className="text-sm text-slate-500">Loading agent…</p>

  const currentFp = fingerprint({
    name: draft.name,
    description: draft.description,
    base_instruction: draft.base_instruction,
    model_config: buildModelConfig(),
    tools: agent.tools,
    skills: agent.skills,
    sub_agents: agent.sub_agents,
  })
  const canPublish = !isDirty && hasPassedTest(agent.id, currentFp)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{agent.name}</h1>
        <Badge tone={AGENT_STATUS_TONE[agent.status]}>
          {agent.status} · v{agent.current_version}
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left: composer */}
        <Card className="space-y-4">
          <Input
            label="Name"
            hideLabel={false}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <Input
            label="Description"
            hideLabel={false}
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          />
          <div className="flex gap-3">
            <div className="flex-1">
              <Select
                label="Model"
                hideLabel={false}
                value={draft.model}
                onChange={(e) => setDraft({ ...draft, model: e.target.value })}
                options={MODEL_OPTIONS}
              />
            </div>
            <div className="w-28">
              <Input
                label="Temperature"
                hideLabel={false}
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={draft.temperature}
                onChange={(e) => setDraft({ ...draft, temperature: Number(e.target.value) })}
              />
            </div>
          </div>
          <Textarea
            label="Base instruction"
            hideLabel={false}
            className="h-40"
            value={draft.base_instruction}
            onChange={(e) => setDraft({ ...draft, base_instruction: e.target.value })}
          />

          <details className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
            <summary className="cursor-pointer text-sm font-medium text-slate-600 dark:text-slate-300">
              Advanced: structured output
            </summary>
            <div className="mt-3 space-y-3">
              <div>
                <Input
                  label="Output key"
                  hideLabel={false}
                  placeholder="e.g. last_quiz"
                  value={draft.output_key}
                  onChange={(e) => setDraft({ ...draft, output_key: e.target.value })}
                />
                <span className="mt-1 block text-xs text-slate-500">
                  Session-state key ADK writes this agent's final reply into (enables
                  <code> {'{'}key?{'}'} </code>
                  placeholders in other agents' instructions).
                </span>
              </div>
              <div>
                <Textarea
                  label="Output schema (JSON)"
                  hideLabel={false}
                  className="h-32 font-mono text-xs"
                  placeholder='{"type": "object", "properties": {...}}'
                  value={draft.output_schema_text}
                  onChange={(e) => {
                    setDraft({ ...draft, output_schema_text: e.target.value })
                    setSchemaError(null)
                  }}
                />
                <span className="mt-1 block text-xs text-slate-500">
                  Optional. When set, this agent's reply is forced into this JSON shape
                  instead of free text.
                </span>
                {schemaError && <span className="mt-1 block text-xs text-red-600">{schemaError}</span>}
              </div>
            </div>
          </details>

          <details className="rounded-md border border-slate-200 p-3 dark:border-slate-800" open={scilEnabled}>
            <summary className="cursor-pointer text-sm font-medium text-slate-600 dark:text-slate-300">
              Self-correction &amp; hallucination detection (SCIL)
            </summary>
            <div className="mt-3 space-y-4">
              <Toggle
                label="Enable SCIL"
                description="Semantic caching, deterministic validators, and self-correcting retries for this agent."
                checked={scilEnabled}
                onChange={setScilEnabled}
              />

              {scilEnabled && (
                <>
                  <div>
                    <span className="mb-1.5 block text-sm font-medium">Validators</span>
                    <div className="space-y-1.5">
                      {SCIL_VALIDATOR_OPTIONS.map((opt) => (
                        <label key={opt.value} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={scilValidators.includes(opt.value)}
                            onChange={(e) => toggleScilValidator(opt.value, e.target.checked)}
                            className="rounded border-slate-300 text-brand-600 focus:ring-brand-500 dark:border-slate-700"
                          />
                          <span className={opt.emphasize ? 'font-semibold' : undefined}>{opt.label}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  {scilValidators.includes('hallucination') && (
                    <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-900">
                      <Toggle
                        label="Also check answer groundedness with an LLM judge"
                        description="Extra latency/cost per turn — verifies every claim in the answer traces back to the tool output data it actually received, catching invented details even when a tool was called."
                        checked={scilHallucinationGroundedness}
                        onChange={setScilHallucinationGroundedness}
                      />
                    </div>
                  )}

                  <div className="flex gap-3">
                    <div className="flex-1">
                      <Input
                        label="Cache TTL (hours)"
                        hideLabel={false}
                        type="number"
                        min="0"
                        placeholder="no expiry"
                        value={scilCacheTtlHours}
                        onChange={(e) => setScilCacheTtlHours(e.target.value)}
                      />
                    </div>
                    <div className="flex-1">
                      <Input
                        label="Max retries"
                        hideLabel={false}
                        type="number"
                        min="0"
                        value={scilMaxRetries}
                        onChange={(e) => setScilMaxRetries(e.target.value)}
                      />
                    </div>
                  </div>
                </>
              )}
            </div>
          </details>

          <Button
            variant="primary"
            tone="neutral"
            onClick={handleSave}
            disabled={!isDirty}
            isPending={updateAgent.isPending}
            loadingLabel="Saving…"
          >
            {isDirty ? 'Save changes' : 'Saved'}
          </Button>

          <hr className="border-slate-200 dark:border-slate-800" />

          <div>
            <span className="mb-1 block text-sm font-medium">Attached skills (order matters)</span>
            <SkillAttachList
              skills={agent.skills}
              onReorder={handleReorderSkills}
              onRemove={(skillId) => detachSkill.mutate(skillId)}
            />
            <div className="mt-2">
              <SkillPicker
                attachedIds={agent.skills.map((s) => s.id)}
                onAttach={(skillId) =>
                  attachSkill.mutate({ skill_id: skillId, attach_order: agent.skills.length })
                }
              />
            </div>
          </div>

          <ToolAttachPanel
            attached={agent.tools}
            onAttach={(toolId) => attachTool.mutate(toolId)}
            onDetach={(toolId) => detachTool.mutate(toolId)}
          />

          <SubAgentAttachPanel
            currentAgentId={agent.id}
            attached={agent.sub_agents}
            onAttach={(childId) => attachSubagent.mutate(childId)}
            onDetach={(childId) => detachSubagent.mutate(childId)}
          />
        </Card>

        {/* Right: live preview + actions */}
        <div className="space-y-3">
          <EffectivePromptPreview baseInstruction={draft.base_instruction} skills={agent.skills} />

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              tone="brand"
              onClick={handleTestInPlayground}
              leftIcon={<FlaskConical size={15} />}
            >
              Test in playground
            </Button>
            <Button
              onClick={handlePublish}
              disabled={!canPublish}
              isPending={publishAgent.isPending}
              loadingLabel="Publishing…"
              title={canPublish ? undefined : 'Run a successful playground test against this exact config first'}
              leftIcon={<Rocket size={15} />}
            >
              Publish
            </Button>
          </div>
          {!canPublish && (
            <p className="text-xs text-slate-500">
              Publish is disabled until a playground test succeeds against this exact configuration.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
