import type { AttachedSkill, AttachedSubagent, AttachedTool, ModelConfig } from '../api/types'

export interface DraftFingerprintInput {
  name: string
  description: string
  base_instruction: string
  model_config: ModelConfig
  tools: AttachedTool[]
  skills: AttachedSkill[]
  sub_agents: AttachedSubagent[]
}

/**
 * A fingerprint of everything that affects what the agent actually does.
 * Used to gate "Publish" on "a playground test succeeded against this exact
 * composition" — if anything here changes after a successful test, the
 * fingerprint changes and Publish is disabled again until re-tested.
 */
export function fingerprint(input: DraftFingerprintInput): string {
  return JSON.stringify({
    name: input.name,
    description: input.description,
    base_instruction: input.base_instruction,
    model_config: input.model_config,
    tool_ids: [...input.tools.map((t) => t.id)].sort(),
    skills: input.skills
      .slice()
      .sort((a, b) => a.attach_order - b.attach_order)
      .map((s) => ({ id: s.id, order: s.attach_order })),
    sub_agent_ids: [...input.sub_agents.map((a) => a.id)].sort(),
  })
}

const testingKey = (agentId: string) => `af:testing:${agentId}`
const testedKey = (agentId: string) => `af:tested:${agentId}`

export function markTesting(agentId: string, fp: string) {
  sessionStorage.setItem(testingKey(agentId), fp)
}

export function markTestedIfPending(agentId: string) {
  const pending = sessionStorage.getItem(testingKey(agentId))
  if (pending) sessionStorage.setItem(testedKey(agentId), pending)
}

export function hasPassedTest(agentId: string, currentFp: string): boolean {
  return sessionStorage.getItem(testedKey(agentId)) === currentFp
}
