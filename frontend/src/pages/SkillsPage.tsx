import { ListChecks, Plus, Sparkles, Tags } from 'lucide-react'
import { useState } from 'react'
import { useSkills } from '../api/skills'
import SkillCard from '../components/skills/SkillCard'
import SkillForm from '../components/skills/SkillForm'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Modal from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import { CardGridSkeleton } from '../components/ui/Skeleton'
import StatTile from '../components/ui/StatTile'
import ViewModeToggle from '../components/ui/ViewModeToggle'
import { useViewMode } from '../lib/viewMode'

export default function SkillsPage() {
  const { data: skills, isLoading, error } = useSkills()
  const [showForm, setShowForm] = useState(false)
  const [viewMode, setViewMode] = useViewMode('skills')

  const withExamples = skills?.filter((s) => (s.few_shot_examples?.length ?? 0) > 0).length ?? 0
  const uniqueTags = new Set(skills?.flatMap((s) => s.tags ?? [])).size

  return (
    <div className="space-y-6">
      <PageHeader
        title="Skills"
        description="Reusable prompt fragments you can stack onto any agent's instruction."
        actions={
          <>
            <ViewModeToggle mode={viewMode} onChange={setViewMode} />
            <Button onClick={() => setShowForm(true)} leftIcon={<Plus size={16} />}>
              New Skill
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile icon={Sparkles} label="Total skills" value={skills?.length ?? 0} tone="brand" />
        <StatTile icon={ListChecks} label="With few-shot examples" value={withExamples} tone="success" />
        <StatTile icon={Tags} label="Unique tags" value={uniqueTags} tone="warning" />
      </div>

      {isLoading && <CardGridSkeleton />}
      {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
      {!isLoading && !skills?.length && (
        <EmptyState
          icon={Sparkles}
          title="No skills yet"
          message="Skills are composable instruction fragments — like 'grade-level simplification' or 'citation formatting' — that stack into an agent's effective prompt."
          action={
            <Button onClick={() => setShowForm(true)}>
              + New Skill
            </Button>
          }
        />
      )}
      {!isLoading && !!skills?.length && (
        <div className={viewMode === 'grid' ? 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3' : 'flex flex-col gap-2'}>
          {skills.map((skill) => (
            <SkillCard key={skill.id} skill={skill} compact={viewMode === 'list'} />
          ))}
        </div>
      )}

      <Modal open={showForm} onClose={() => setShowForm(false)} title="New Skill" maxWidth="max-w-xl">
        <SkillForm onDone={() => setShowForm(false)} />
      </Modal>
    </div>
  )
}
