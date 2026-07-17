import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { useCreateAgent, usePublishAgent } from '../../api/agents'
import { api } from '../../api/client'
import { useRunPlayground } from '../../api/playground'
import { useCreateTool } from '../../api/tools'
import type { AccessPolicy, Agent, DataEntity, Tool } from '../../api/types'
import { fingerprint, hasPassedTest, markTestedIfPending, markTesting } from '../../lib/testGate'
import { slugify } from './slugify'

export const WIZARD_STEPS = ['Domain', 'Identity & access', 'Data entities', 'Tools', 'Agent', 'Test & publish'] as const

export interface WizardValidity {
  domain: boolean
  entities: boolean
  tools: boolean
  agent: boolean
  publish: boolean
}

function currentFingerprint(agent: Agent, attachedTools: Tool[]): string {
  return fingerprint({
    name: agent.name,
    description: agent.description ?? '',
    base_instruction: agent.base_instruction,
    model_config: agent.model_config,
    tools: attachedTools.map((t) => ({ id: t.id, name: t.name, tool_type: t.tool_type })),
    skills: [],
    sub_agents: [],
  })
}

/** All state, API orchestration, and step-gating for the domain onboarding
 * wizard. Keeps NewDomainWizard.tsx a thin renderer of whichever step is
 * current. */
export default function useNewDomainWizard() {
  const [step, setStep] = useState(0)

  const [domainName, setDomainName] = useState('')
  const [domainDescription, setDomainDescription] = useState('')

  const [policy, setPolicyState] = useState<AccessPolicy | null | undefined>(undefined) // undefined = not decided yet
  const [addingPolicy, setAddingPolicy] = useState(true)

  const [entities, setEntities] = useState<DataEntity[]>([])
  const [addingEntity, setAddingEntity] = useState(true)

  const [tools, setTools] = useState<Tool[]>([])
  const createTool = useCreateTool()

  const [agentName, setAgentName] = useState('')
  const [agentDescription, setAgentDescription] = useState('')
  const [agentInstruction, setAgentInstruction] = useState('')
  const [agent, setAgent] = useState<Agent | null>(null)
  const createAgent = useCreateAgent()
  const publishAgent = usePublishAgent(agent?.id ?? '')
  const [publishedVersion, setPublishedVersion] = useState<number | null>(null)

  const runPlayground = useRunPlayground()
  const [smokeResult, setSmokeResult] = useState<string | null>(null)

  function next() {
    setStep((s) => Math.min(s + 1, WIZARD_STEPS.length - 1))
  }

  function setPolicy(p: AccessPolicy) {
    setPolicyState(p)
  }

  function finishPolicyStep() {
    setAddingPolicy(false)
    next()
  }

  function changePolicy() {
    setAddingPolicy(true)
  }

  function skipPolicy() {
    setPolicyState(null)
    next()
  }

  function addEntity(entity: DataEntity) {
    setEntities((es) => [...es, entity])
  }

  function finishEntityForm() {
    setAddingEntity(false)
  }

  function addAnotherEntity() {
    setAddingEntity(true)
  }

  async function createAllTools() {
    const remaining = entities.filter((e) => !tools.some((t) => t.config.entity_id === e.id))
    let created = 0
    for (const entity of remaining) {
      try {
        const tool = await createTool.mutateAsync({
          name: `query_${entity.name}`,
          tool_type: 'data_query_tool',
          description: '', // auto-composed server-side from the entity's fields
          config: { entity_id: entity.id, policy_id: policy?.id },
          input_schema: { type: 'object', properties: {} }, // auto-derived server-side
        })
        setTools((ts) => [...ts, tool])
        created += 1
      } catch (err) {
        toast.error(`${entity.name}: ${(err as Error).message}`)
      }
    }
    if (created > 0) toast.success(`${created} query tool(s) created — no SQL written`)
  }

  function useSuggestedAgentName() {
    setAgentName(`${slugify(domainName)}_analyst`)
  }

  function defaultAgentInstruction(): string {
    return (
      `You are the ${domainName || 'this'} specialist. Available tools: ${tools.map((t) => t.name).join(', ')} — ` +
      "each one lets you write a SELECT statement yourself against the table/columns described in that tool. " +
      "Never reference a column that tool doesn't list. Data visibility is already scoped to the logged-in " +
      'user by the tools themselves — if a call comes back with an "error", explain that plainly rather than ' +
      "guessing or retrying with invented values. Present results as markdown tables using each column's label."
    )
  }

  async function createAgentAndAttachTools() {
    if (!agentName.trim()) {
      toast.error('Give the agent a name first')
      return
    }
    try {
      const created = await createAgent.mutateAsync({
        name: agentName,
        description: agentDescription || undefined,
        base_instruction: agentInstruction || defaultAgentInstruction(),
      })
      setAgent(created)
      // Attach with the FRESH id from the response, never from state — a
      // hook instantiated with the pre-creation agentId would close over a
      // stale value and every attach would silently post to /agents//tools.
      let attached = 0
      for (const tool of tools) {
        try {
          await api.post<void>(`/agents/${created.id}/tools`, { tool_id: tool.id })
          attached += 1
        } catch (err) {
          toast.error(`Attaching ${tool.name} failed: ${(err as Error).message}`)
        }
      }
      if (attached < tools.length) return // stay on this step so it's visibly broken, not silently
      toast.success(`Agent "${created.name}" created with ${attached} tool(s) attached`)
      next()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  function runSmokeTest() {
    if (!agent) return
    setSmokeResult(null)
    const firstEntity = entities[0]
    markTesting(agent.id, currentFingerprint(agent, tools))
    runPlayground.mutate(
      {
        agent_id: agent.id,
        message: `How many rows of ${firstEntity ? firstEntity.name : 'data'} are available? Answer briefly with the number.`,
      },
      {
        onSuccess: (r) => {
          // A text-to-SQL agent that answers without calling its query tool
          // is hallucinating, not working — the whole point of the smoke
          // test is to catch exactly that before publish.
          if (r.tool_calls.length === 0) {
            setSmokeResult(null)
            toast.error(
              'The agent answered WITHOUT querying the database (0 tool calls) — its answer was invented. Check that the tools show as attached on the agent page.',
            )
            return
          }
          markTestedIfPending(agent.id)
          setSmokeResult(r.response_text)
          toast.success(`Smoke test passed — ${r.tool_calls.length} real query tool call(s)`)
        },
        onError: (err) => {
          setSmokeResult(null)
          toast.error((err as Error).message)
        },
      },
    )
  }

  function publish() {
    if (!agent) return
    publishAgent.mutate(undefined, {
      onSuccess: (result) => {
        if (result.status === 'published' && result.version) {
          setPublishedVersion(result.version.version)
          toast.success('Published — ready to use in chat')
        } else {
          toast.success('Submitted for admin approval')
        }
      },
      onError: (err) => toast.error((err as Error).message),
    })
  }

  const validity: WizardValidity = useMemo(
    () => ({
      domain: domainName.trim().length > 0,
      entities: entities.length > 0,
      tools: tools.length > 0,
      agent: agentName.trim().length > 0,
      publish: agent != null && hasPassedTest(agent.id, currentFingerprint(agent, tools)),
    }),
    // smokeResult isn't read directly, but re-render after a passing smoke
    // test (which writes to sessionStorage via markTestedIfPending) is what
    // makes `publish` re-evaluate to true.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [domainName, entities, tools, agentName, agent, smokeResult],
  )

  return {
    step,
    domainName,
    domainDescription,
    setDomainName,
    setDomainDescription,

    policy,
    addingPolicy,
    setPolicy,
    finishPolicyStep,
    changePolicy,
    skipPolicy,

    entities,
    addingEntity,
    addEntity,
    finishEntityForm,
    addAnotherEntity,

    tools,
    isCreatingTools: createTool.isPending,
    createAllTools,

    agentName,
    agentDescription,
    agentInstruction,
    agent,
    setAgentName,
    setAgentDescription,
    setAgentInstruction,
    useSuggestedAgentName,
    isCreatingAgent: createAgent.isPending,
    createAgentAndAttachTools,

    smokeResult,
    isRunningSmokeTest: runPlayground.isPending,
    runSmokeTest,

    isPublishing: publishAgent.isPending,
    publishError: publishAgent.isError,
    publishedVersion,
    publish,

    validity,
    next,
  }
}

export type UseNewDomainWizardResult = ReturnType<typeof useNewDomainWizard>
