import type { JsonSchema } from '../../api/types'

interface Row {
  name: string
  type: string
  description: string
  required: boolean
}

function schemaToRows(schema: JsonSchema): Row[] {
  const required = new Set(schema.required ?? [])
  return Object.entries(schema.properties ?? {}).map(([name, prop]) => ({
    name,
    type: prop.type,
    description: prop.description ?? '',
    required: required.has(name),
  }))
}

function rowsToSchema(rows: Row[]): JsonSchema {
  const properties: JsonSchema['properties'] = {}
  const required: string[] = []
  for (const row of rows) {
    if (!row.name.trim()) continue
    properties[row.name] = { type: row.type, description: row.description || undefined }
    if (row.required) required.push(row.name)
  }
  return { type: 'object', properties, required: required.length ? required : undefined }
}

const TYPE_OPTIONS = ['string', 'number', 'boolean', 'object', 'array']

export default function ParamSchemaBuilder({
  value,
  onChange,
}: {
  value: JsonSchema
  onChange: (schema: JsonSchema) => void
}) {
  const rows = schemaToRows(value)

  function updateRows(next: Row[]) {
    onChange(rowsToSchema(next))
  }

  function updateRow(index: number, patch: Partial<Row>) {
    const next = rows.map((r, i) => (i === index ? { ...r, ...patch } : r))
    updateRows(next)
  }

  function addRow() {
    updateRows([...rows, { name: '', type: 'string', description: '', required: false }])
  }

  function removeRow(index: number) {
    updateRows(rows.filter((_, i) => i !== index))
  }

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium">Parameters</label>
      {rows.length === 0 && (
        <p className="text-sm text-slate-500">No parameters yet — add one below.</p>
      )}
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-2 rounded border border-slate-200 p-2 dark:border-slate-800">
          <input
            className="w-32 rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            placeholder="param_name"
            value={row.name}
            onChange={(e) => updateRow(i, { name: e.target.value })}
          />
          <select
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            value={row.type}
            onChange={(e) => updateRow(i, { type: e.target.value })}
          >
            {TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <input
            className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            placeholder="description"
            value={row.description}
            onChange={(e) => updateRow(i, { description: e.target.value })}
          />
          <label className="flex items-center gap-1 text-xs text-slate-600 dark:text-slate-400">
            <input
              type="checkbox"
              checked={row.required}
              onChange={(e) => updateRow(i, { required: e.target.checked })}
            />
            required
          </label>
          <button
            type="button"
            onClick={() => removeRow(i)}
            className="text-sm text-red-600 hover:underline"
          >
            remove
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={addRow}
        className="text-sm font-medium text-brand-600 hover:underline"
      >
        + add parameter
      </button>
    </div>
  )
}
