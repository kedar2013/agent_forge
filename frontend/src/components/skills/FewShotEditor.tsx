import type { FewShotExample } from '../../api/types'

export default function FewShotEditor({
  value,
  onChange,
}: {
  value: FewShotExample[]
  onChange: (examples: FewShotExample[]) => void
}) {
  function update(i: number, patch: Partial<FewShotExample>) {
    onChange(value.map((ex, idx) => (idx === i ? { ...ex, ...patch } : ex)))
  }

  function add() {
    onChange([...value, { input: '', output: '' }])
  }

  function remove(i: number) {
    onChange(value.filter((_, idx) => idx !== i))
  }

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium">Few-shot examples</label>
      {value.map((ex, i) => (
        <div key={i} className="space-y-1 rounded border border-slate-200 p-2 dark:border-slate-800">
          <textarea
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            placeholder="example input"
            value={ex.input}
            onChange={(e) => update(i, { input: e.target.value })}
          />
          <textarea
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            placeholder="expected output"
            value={ex.output}
            onChange={(e) => update(i, { output: e.target.value })}
          />
          <button type="button" onClick={() => remove(i)} className="text-sm text-red-600 hover:underline">
            remove
          </button>
        </div>
      ))}
      <button type="button" onClick={add} className="text-sm font-medium text-brand-600 hover:underline">
        + add example
      </button>
    </div>
  )
}
