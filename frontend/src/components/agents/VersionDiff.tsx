import { diffWordsWithSpace } from 'diff'
import type { ModelConfig } from '../../api/types'

/** The shape both an AgentVersion.snapshot and the live Agent row can be
 * mapped to, so the same diff logic compares "any two points in time" for
 * an agent — a past version vs. the one before it, or the live draft vs.
 * its last published snapshot. */
export interface SnapshotLike {
  name: string
  description: string | null
  base_instruction: string
  model_config: ModelConfig
  output_schema?: Record<string, unknown> | null
  output_key?: string | null
  tools: { id: string; name: string }[]
  skills: { id: string; name: string }[]
  sub_agents: { id: string; name: string }[]
}

function normalize(value: string | null | undefined): string {
  return value ?? ''
}

function jsonOf(value: Record<string, unknown> | null | undefined): string {
  return value ? JSON.stringify(value, null, 2) : ''
}

function diffList<T extends { id: string; name: string }>(before: T[], after: T[]) {
  const beforeIds = new Set(before.map((x) => x.id))
  const afterIds = new Set(after.map((x) => x.id))
  return {
    added: after.filter((x) => !beforeIds.has(x.id)),
    removed: before.filter((x) => !afterIds.has(x.id)),
  }
}

function diffModelConfig(before: ModelConfig | undefined, after: ModelConfig | undefined) {
  const b = (before ?? {}) as Record<string, unknown>
  const a = (after ?? {}) as Record<string, unknown>
  const keys = new Set([...Object.keys(b), ...Object.keys(a)])
  const changes: { key: string; before: unknown; after: unknown }[] = []
  for (const key of keys) {
    if (JSON.stringify(b[key]) !== JSON.stringify(a[key])) {
      changes.push({ key, before: b[key], after: a[key] })
    }
  }
  return changes
}

/** Computed once so both VersionDiff and its callers (e.g. deciding whether
 * to even show a "draft has unpublished changes" banner) agree on what
 * counts as a real change. */
export function computeSnapshotDiff(before: SnapshotLike, after: SnapshotLike) {
  const tools = diffList(before.tools, after.tools)
  const skills = diffList(before.skills, after.skills)
  const subAgents = diffList(before.sub_agents, after.sub_agents)
  const modelChanges = diffModelConfig(before.model_config, after.model_config)

  return {
    nameChanged: before.name !== after.name,
    descriptionChanged: normalize(before.description) !== normalize(after.description),
    instructionChanged: before.base_instruction !== after.base_instruction,
    outputKeyChanged: normalize(before.output_key) !== normalize(after.output_key),
    schemaChanged: jsonOf(before.output_schema) !== jsonOf(after.output_schema),
    modelChanges,
    tools,
    skills,
    subAgents,
  }
}

export function hasSnapshotChanges(before: SnapshotLike, after: SnapshotLike): boolean {
  const d = computeSnapshotDiff(before, after)
  return (
    d.nameChanged ||
    d.descriptionChanged ||
    d.instructionChanged ||
    d.outputKeyChanged ||
    d.schemaChanged ||
    d.modelChanges.length > 0 ||
    d.tools.added.length > 0 ||
    d.tools.removed.length > 0 ||
    d.skills.added.length > 0 ||
    d.skills.removed.length > 0 ||
    d.subAgents.added.length > 0 ||
    d.subAgents.removed.length > 0
  )
}

function TextDiff({ before, after }: { before: string; after: string }) {
  const parts = diffWordsWithSpace(before, after)
  return (
    <>
      {parts.map((part, i) => (
        <span
          key={i}
          className={
            part.added
              ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300'
              : part.removed
                ? 'text-red-700 line-through decoration-red-400/70 dark:text-red-400'
                : ''
          }
        >
          {part.value}
        </span>
      ))}
    </>
  )
}

function DiffRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
        {label}
      </div>
      {children}
    </div>
  )
}

function ChangeBadgeList({
  added,
  removed,
}: {
  added: { id: string; name: string }[]
  removed: { id: string; name: string }[]
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {added.map((item) => (
        <span
          key={`+${item.id}`}
          className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
        >
          + {item.name}
        </span>
      ))}
      {removed.map((item) => (
        <span
          key={`-${item.id}`}
          className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-400"
        >
          − {item.name}
        </span>
      ))}
    </div>
  )
}

export default function VersionDiff({
  before,
  after,
}: {
  /** null means "nothing to compare against" — e.g. the very first published version. */
  before: SnapshotLike | null
  after: SnapshotLike
}) {
  if (!before) {
    return <p className="text-xs italic text-slate-500">Initial version — nothing to compare against.</p>
  }

  const d = computeSnapshotDiff(before, after)

  if (!hasSnapshotChanges(before, after)) {
    return (
      <p className="text-xs italic text-slate-500">
        No content changes — this was likely republished only to refresh cached tool/sub-agent references (e.g.
        after a shared tool or a sub-agent was updated elsewhere).
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {d.nameChanged && (
        <DiffRow label="Name">
          <div className="font-mono text-xs leading-relaxed">
            <TextDiff before={before.name} after={after.name} />
          </div>
        </DiffRow>
      )}

      {d.descriptionChanged && (
        <DiffRow label="Description">
          <div className="font-mono text-xs leading-relaxed whitespace-pre-wrap">
            <TextDiff before={normalize(before.description)} after={normalize(after.description)} />
          </div>
        </DiffRow>
      )}

      {d.instructionChanged && (
        <DiffRow label="Instruction">
          <div className="max-h-64 overflow-y-auto rounded-md border border-slate-200 p-2 font-mono text-xs leading-relaxed whitespace-pre-wrap dark:border-slate-800">
            <TextDiff before={before.base_instruction} after={after.base_instruction} />
          </div>
        </DiffRow>
      )}

      {d.modelChanges.length > 0 && (
        <DiffRow label="Model config">
          <ul className="space-y-0.5 font-mono text-xs">
            {d.modelChanges.map((c) => (
              <li key={c.key}>
                <span className="text-slate-500">{c.key}:</span>{' '}
                <span className="text-red-700 line-through dark:text-red-400">{JSON.stringify(c.before)}</span>
                {' → '}
                <span className="text-emerald-700 dark:text-emerald-400">{JSON.stringify(c.after)}</span>
              </li>
            ))}
          </ul>
        </DiffRow>
      )}

      {d.outputKeyChanged && (
        <DiffRow label="Output key">
          <div className="font-mono text-xs">
            <TextDiff before={before.output_key || '(none)'} after={after.output_key || '(none)'} />
          </div>
        </DiffRow>
      )}

      {d.schemaChanged && (
        <DiffRow label="Output schema">
          <div className="max-h-48 overflow-y-auto rounded-md border border-slate-200 p-2 font-mono text-xs leading-relaxed whitespace-pre-wrap dark:border-slate-800">
            <TextDiff before={jsonOf(before.output_schema)} after={jsonOf(after.output_schema)} />

          </div>
        </DiffRow>
      )}

      {(d.tools.added.length > 0 || d.tools.removed.length > 0) && (
        <DiffRow label="Tools">
          <ChangeBadgeList added={d.tools.added} removed={d.tools.removed} />
        </DiffRow>
      )}

      {(d.skills.added.length > 0 || d.skills.removed.length > 0) && (
        <DiffRow label="Skills">
          <ChangeBadgeList added={d.skills.added} removed={d.skills.removed} />
        </DiffRow>
      )}

      {(d.subAgents.added.length > 0 || d.subAgents.removed.length > 0) && (
        <DiffRow label="Sub-agents">
          <ChangeBadgeList added={d.subAgents.added} removed={d.subAgents.removed} />
        </DiffRow>
      )}
    </div>
  )
}
