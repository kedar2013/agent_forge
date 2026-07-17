import { useEffect, useState } from 'react'
import { CheckCircle2, Plus, Trash2, Wand2, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import {
  useConnections,
  useCreateDataEntity,
  useIntrospectSource,
  useListTables,
  useTestConnection,
  useUpdateDataEntity,
} from '../../api/dataEntities'
import type { DataConnection, DataEntity, DataField, PolicyBackendType, TableInfo } from '../../api/types'
import Button from '../ui/Button'
import { Ex, GuidedField } from '../ui/FieldGuide'
import Input from '../ui/Input'
import Select from '../ui/Select'

function emptyField(): DataField {
  return { name: '', label: '', type: 'string', searchable: false, filterable: false, visible: true, measure: false, format: 'text' }
}

const NUMERIC_TYPES = new Set(['int', 'bigint', 'smallint', 'tinyint', 'decimal', 'float', 'double', 'numeric'])
const DATE_TYPES = new Set(['date', 'datetime', 'timestamp', 'time', 'year'])
const TEXT_TYPES = new Set(['varchar', 'char', 'text', 'mediumtext', 'longtext'])
const CURRENCY_HINTS = /amount|price|revenue|cost|total|salary|value|balance|fee/i

const FORMAT_OPTIONS = [
  { label: 'text', value: 'text' },
  { label: 'currency', value: 'currency' },
  { label: 'percent', value: 'percent' },
  { label: 'date', value: 'date' },
  { label: 'integer', value: 'integer' },
]

function titleCase(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Smart auto-annotation: turns a raw introspected column into a sensibly
 * pre-tagged field, so the admin reviews checkboxes instead of setting
 * every one by hand. Heuristics, all overridable in the table below:
 *   numeric non-id  -> measure (currency format when the name smells like money)
 *   date-ish        -> date format + filterable
 *   *_id / id / enum-> filterable
 *   text            -> searchable
 */
function annotate(name: string, type: string): DataField {
  const isId = /(^|_)id$/i.test(name)
  const field: DataField = {
    name,
    label: titleCase(name),
    type,
    searchable: TEXT_TYPES.has(type),
    filterable: isId || type === 'enum' || DATE_TYPES.has(type),
    visible: true,
    measure: NUMERIC_TYPES.has(type) && !isId,
    format: DATE_TYPES.has(type)
      ? 'date'
      : NUMERIC_TYPES.has(type) && !isId
        ? CURRENCY_HINTS.test(name)
          ? 'currency'
          : 'integer'
        : 'text',
  }
  return field
}

export default function DataEntityForm({
  entity,
  onDone,
  onCreated,
}: {
  entity?: DataEntity
  onDone: () => void
  /** Fires in addition to onDone with the created/updated entity — lets a
   * caller (e.g. the domain-onboarding wizard) carry the new id forward. */
  onCreated?: (entity: DataEntity) => void
}) {
  const isEditing = !!entity
  const [name, setName] = useState(entity?.name ?? '')
  const [description, setDescription] = useState(entity?.description ?? '')
  const [backendType, setBackendType] = useState<PolicyBackendType>(entity?.connection.type ?? 'mysql')
  const [connectionEnvPrefix, setConnectionEnvPrefix] = useState(entity?.connection.connection_env_prefix ?? '')
  const [connectionEnv, setConnectionEnv] = useState(entity?.connection.connection_env ?? '')
  const [database, setDatabase] = useState(entity?.connection.database ?? '')
  const [table, setTable] = useState(entity?.source.table ?? entity?.source.collection ?? '')
  const [primaryKey, setPrimaryKey] = useState(entity?.source.primary_key ?? '')
  const [fields, setFields] = useState<DataField[]>(entity?.fields ?? [])
  const [sortField, setSortField] = useState(entity?.default_sort?.field ?? '')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(entity?.default_sort?.dir ?? 'asc')
  const [defaultLimit, setDefaultLimit] = useState(entity?.default_limit ?? 20)
  const [maxLimit, setMaxLimit] = useState(entity?.max_limit ?? 100)

  const createEntity = useCreateDataEntity()
  const updateEntity = useUpdateDataEntity()
  const introspect = useIntrospectSource()
  const { data: connections } = useConnections()
  const testConnection = useTestConnection()
  const listTables = useListTables()
  const [tables, setTables] = useState<TableInfo[]>([])
  const pending = createEntity.isPending || updateEntity.isPending

  // Table list refreshes whenever a (MySQL) connection prefix is chosen —
  // the admin picks from what actually exists instead of typing blind.
  useEffect(() => {
    setTables([])
    if (backendType !== 'mysql' || !connectionEnvPrefix) return
    listTables.mutate(connectionEnvPrefix, {
      onSuccess: (r) => setTables(r.tables),
      onError: () => setTables([]), // connection test button surfaces the real error
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionEnvPrefix, backendType])

  function updateField(index: number, patch: Partial<DataField>) {
    setFields((fs) => fs.map((f, i) => (i === index ? { ...f, ...patch } : f)))
  }

  function handleTestConnection() {
    if (!connectionEnvPrefix) {
      toast.error('Pick or type a connection prefix first')
      return
    }
    testConnection.mutate(connectionEnvPrefix, {
      onSuccess: (r) => toast.success(`Connected to "${r.database}" — ${r.table_count} tables visible`),
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function handleIntrospect(tableName?: string) {
    const target = tableName ?? table
    if (!target) {
      toast.error('Pick a table/collection first')
      return
    }
    const connection: DataConnection =
      backendType === 'mysql'
        ? { type: 'mysql', connection_env_prefix: connectionEnvPrefix }
        : { type: 'mongo', connection_env: connectionEnv, database }
    introspect.mutate(
      { connection, table: target },
      {
        onSuccess: (result) => {
          const existingNames = new Set(fields.map((f) => f.name))
          const newFields = result.fields.filter((f) => !existingNames.has(f.name)).map((f) => annotate(f.name, f.type))
          setFields((fs) => [...fs, ...newFields])
          if (result.primary_key && !primaryKey) setPrimaryKey(result.primary_key)
          if (!name) setName(target)
          toast.success(
            `Introspected ${result.fields.length} column(s) — labels, formats, and search/filter/measure tags were pre-filled; review and adjust below`,
          )
        },
        onError: (err) => toast.error((err as Error).message),
      },
    )
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const connection: DataConnection =
      backendType === 'mysql'
        ? { type: 'mysql', connection_env_prefix: connectionEnvPrefix }
        : { type: 'mongo', connection_env: connectionEnv, database }
    const source = backendType === 'mysql' ? { table, primary_key: primaryKey } : { collection: table, primary_key: primaryKey }
    const input = {
      name,
      description: description || undefined,
      connection,
      source,
      fields,
      default_sort: sortField ? { field: sortField, dir: sortDir } : undefined,
      default_limit: defaultLimit,
      max_limit: maxLimit,
    }
    const onSuccess = (saved: DataEntity) => {
      toast.success(isEditing ? `Data entity "${name}" updated` : `Data entity "${name}" created`)
      onCreated?.(saved)
      onDone()
    }
    const onError = (err: unknown) => toast.error((err as Error).message)
    if (isEditing) {
      updateEntity.mutate({ id: entity.id, ...input }, { onSuccess, onError })
    } else {
      createEntity.mutate(input, { onSuccess, onError })
    }
  }

  const knownPrefixes = connections ?? []

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <GuidedField
          label="Name"
          guide={{
            title: 'Entity name',
            what: 'A short identifier for this table\'s data dictionary.',
            why: 'It names the generated query tool (query_<name>) and is how the agent\'s instruction refers to this data.',
            example: (
              <>
                {table ? <Ex>{table}</Ex> : <Ex>orders</Ex>} — auto-filled from the table you pick if you leave it
                blank before introspecting.
              </>
            ),
          }}
        >
          <Input required label="Name" value={name} onChange={(e) => setName(e.target.value)} />
        </GuidedField>
        <GuidedField
          label="Description"
          guide={{
            title: 'Entity description',
            what: 'One line about what a row in this table represents.',
            why: 'Included in the tool description the LLM reads — a good description measurably improves which tool it picks and the SQL it writes.',
            example: <>e.g. <Ex>One row per customer order, including status and total amount</Ex></>,
          }}
        >
          <Input label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        </GuidedField>
      </div>

      <fieldset className="space-y-3 rounded-md border border-slate-200 p-3 dark:border-slate-700">
        <legend className="px-1 text-xs font-semibold uppercase text-slate-500">Source</legend>
        <GuidedField
          label="Backend"
          guide={{
            title: 'Backend type',
            what: 'The kind of database this table lives in.',
            why: 'Decides which query tool is generated: MySQL gets the SQL data_query_tool (LLM writes SELECTs), Mongo gets the document query tool.',
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
          <div className="space-y-2">
            <GuidedField
              label="Connection"
              guide={{
                title: 'Connection env prefix',
                what: 'Which already-configured database connection to use — each option is a {PREFIX}_HOST/_USER/_PASSWORD/_DATABASE group from the backend\'s .env.',
                why: 'The generated tool connects with these exact credentials at chat time. Nothing is stored in the browser or database — only the prefix string.',
                example:
                  knownPrefixes.length > 0 ? (
                    <>
                      Discovered from your .env:{' '}
                      {knownPrefixes.map((c) => (
                        <span key={c.prefix} className="mr-1">
                          <Ex>
                            {c.prefix} → {c.database}
                          </Ex>
                        </span>
                      ))}
                    </>
                  ) : (
                    <>e.g. <Ex>SALES_DB</Ex> for SALES_DB_HOST/_USER/_PASSWORD/_DATABASE</>
                  ),
                warn: 'A new database needs its env vars added to backend/.env (and a backend restart) before it appears here.',
              }}
            >
              <div className="flex gap-2">
                <div className="flex-1">
                  <Select
                    label="Connection"
                    value={knownPrefixes.some((c) => c.prefix === connectionEnvPrefix) ? connectionEnvPrefix : ''}
                    onChange={(e) => setConnectionEnvPrefix(e.target.value)}
                    placeholder="— pick a connection —"
                    options={knownPrefixes.map((c) => ({
                      label: `${c.prefix} (${c.database} @ ${c.host})`,
                      value: c.prefix,
                    }))}
                  />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  tone="neutral"
                  size="xs"
                  onClick={handleTestConnection}
                  disabled={!connectionEnvPrefix}
                  isPending={testConnection.isPending}
                  loadingLabel="Testing…"
                  leftIcon={
                    testConnection.isSuccess ? (
                      <CheckCircle2 size={13} className="text-emerald-500" />
                    ) : testConnection.isError ? (
                      <XCircle size={13} className="text-red-500" />
                    ) : undefined
                  }
                  className="shrink-0"
                >
                  {testConnection.isSuccess ? 'Connected' : testConnection.isError ? 'Retry test' : 'Test connection'}
                </Button>
              </div>
            </GuidedField>

            <GuidedField
              label="Table"
              guide={{
                title: 'Source table',
                what: 'The table this entity describes — picked from the live database, so typos are impossible.',
                why: 'Every SQL the LLM writes through this tool is locked to exactly this table by AST validation; it cannot join or reference others.',
                example:
                  tables.length > 0 ? (
                    <>
                      {tables.slice(0, 4).map((t) => (
                        <span key={t.name} className="mr-1">
                          <Ex>
                            {t.name} ({t.row_estimate.toLocaleString()} rows)
                          </Ex>
                        </span>
                      ))}
                    </>
                  ) : (
                    <>Pick a connection above to load its tables.</>
                  ),
              }}
            >
              <Select
                label="Table"
                value={tables.some((t) => t.name === table) ? table : ''}
                onChange={(e) => {
                  setTable(e.target.value)
                  if (e.target.value) handleIntrospect(e.target.value)
                }}
                placeholder={listTables.isPending ? 'Loading tables…' : '— pick a table (auto-introspects) —'}
                options={tables.map((t) => ({
                  label: `${t.name} — ${t.column_count} cols, ~${t.row_estimate.toLocaleString()} rows`,
                  value: t.name,
                }))}
              />
            </GuidedField>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <GuidedField
              label="Connection env var name"
              guide={{
                title: 'Mongo connection env var',
                what: 'The name of the env var in backend/.env holding the full MongoDB connection string.',
                why: 'The generated tool reads this env var at chat time to connect.',
                example: <Ex>MONGO_URL</Ex>,
              }}
            >
              <Input label="Connection env var name" value={connectionEnv} onChange={(e) => setConnectionEnv(e.target.value)} />
            </GuidedField>
            <GuidedField
              label="Database"
              guide={{
                title: 'Mongo database',
                what: 'The database inside that Mongo deployment.',
                why: 'Combined with the collection below to scope every query this tool runs.',
              }}
            >
              <Input label="Database" value={database} onChange={(e) => setDatabase(e.target.value)} />
            </GuidedField>
            <GuidedField
              label="Collection"
              guide={{
                title: 'Source collection',
                what: 'The collection this entity describes.',
                why: 'All generated queries are locked to it.',
              }}
            >
              <Input label="Collection" value={table} onChange={(e) => setTable(e.target.value)} />
            </GuidedField>
            <div className="flex items-end">
              <Button
                type="button"
                variant="outline"
                tone="brand"
                size="xs"
                onClick={() => handleIntrospect()}
                disabled={introspect.isPending}
                leftIcon={<Wand2 size={13} />}
              >
                {introspect.isPending ? 'Reading…' : 'Introspect'}
              </Button>
            </div>
          </div>
        )}

        <GuidedField
          label="Primary key"
          guide={{
            title: 'Primary key',
            what: 'The column that uniquely identifies a row — auto-detected from the table definition when you pick a table.',
            why: 'Used for stable ordering and by access policies that scope by id.',
            example: primaryKey ? <Ex>{primaryKey}</Ex> : <>auto-fills on table selection, e.g. <Ex>order_id</Ex></>,
          }}
        >
          <Input label="Primary key" value={primaryKey} onChange={(e) => setPrimaryKey(e.target.value)} />
        </GuidedField>
      </fieldset>

      <fieldset className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
        <legend className="px-1 text-xs font-semibold uppercase text-slate-500">Fields</legend>
        <p className="text-xs text-slate-400">
          Pre-annotated from column types — <strong>Search</strong> lets the LLM match free text against the column,{' '}
          <strong>Filter</strong> marks it for WHERE clauses, <strong>Measure</strong> marks it aggregatable
          (SUM/AVG), <strong>Label/Format</strong> control how results render in chat.
        </p>
        {fields.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-slate-400">
                <tr>
                  <th className="px-1 py-1 font-medium">Column</th>
                  <th className="px-1 py-1 font-medium">Label</th>
                  <th className="px-1 py-1 font-medium">Type</th>
                  <th className="px-1 py-1 font-medium">Format</th>
                  <th className="px-1 py-1 text-center font-medium">Search</th>
                  <th className="px-1 py-1 text-center font-medium">Filter</th>
                  <th className="px-1 py-1 text-center font-medium">Measure</th>
                  <th className="px-1 py-1 text-center font-medium">Visible</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {fields.map((field, i) => (
                  <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="px-1 py-1">
                      <Input
                        size="xs"
                        label="Column name"
                        value={field.name}
                        onChange={(e) => updateField(i, { name: e.target.value })}
                      />
                    </td>
                    <td className="px-1 py-1">
                      <Input
                        size="xs"
                        label="Column label"
                        value={field.label ?? ''}
                        onChange={(e) => updateField(i, { label: e.target.value })}
                      />
                    </td>
                    <td className="px-1 py-1">
                      <Input
                        size="xs"
                        label="Column type"
                        value={field.type}
                        onChange={(e) => updateField(i, { type: e.target.value })}
                      />
                    </td>
                    <td className="px-1 py-1">
                      <Select
                        size="xs"
                        label="Column format"
                        value={field.format ?? 'text'}
                        onChange={(e) => updateField(i, { format: e.target.value as DataField['format'] })}
                        options={FORMAT_OPTIONS}
                      />
                    </td>
                    <td className="px-1 py-1 text-center">
                      <input type="checkbox" checked={!!field.searchable} onChange={(e) => updateField(i, { searchable: e.target.checked })} />
                    </td>
                    <td className="px-1 py-1 text-center">
                      <input type="checkbox" checked={!!field.filterable} onChange={(e) => updateField(i, { filterable: e.target.checked })} />
                    </td>
                    <td className="px-1 py-1 text-center">
                      <input type="checkbox" checked={!!field.measure} onChange={(e) => updateField(i, { measure: e.target.checked })} />
                    </td>
                    <td className="px-1 py-1 text-center">
                      <input type="checkbox" checked={field.visible !== false} onChange={(e) => updateField(i, { visible: e.target.checked })} />
                    </td>
                    <td className="px-1 py-1">
                      <Button
                        type="button"
                        variant="ghost"
                        tone="danger"
                        size="icon"
                        onClick={() => setFields((fs) => fs.filter((_, idx) => idx !== i))}
                        aria-label="Remove field"
                      >
                        <Trash2 size={13} />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Button
          type="button"
          variant="ghost"
          tone="brand"
          size="xs"
          onClick={() => setFields((fs) => [...fs, emptyField()])}
          leftIcon={<Plus size={13} />}
        >
          Add field manually
        </Button>
      </fieldset>

      <fieldset className="grid grid-cols-1 gap-3 rounded-md border border-slate-200 p-3 sm:grid-cols-2 lg:grid-cols-4 dark:border-slate-700">
        <legend className="px-1 text-xs font-semibold uppercase text-slate-500">Defaults</legend>
        <GuidedField
          label="Sort field"
          guide={{
            title: 'Default sort',
            what: 'How results are ordered when the user\'s question doesn\'t imply an order.',
            why: 'Keeps answers stable between runs — without it, "show me orders" can return a different sample every time.',
          }}
        >
          <Select
            label="Sort field"
            value={sortField}
            onChange={(e) => setSortField(e.target.value)}
            placeholder="None"
            options={fields.map((f) => ({ label: f.name, value: f.name }))}
          />
        </GuidedField>
        <GuidedField
          label="Direction"
          guide={{
            title: 'Sort direction',
            what: 'Ascending or descending for the default sort.',
            why: 'desc + a date column = "most recent first", the right default for most operational data.',
          }}
        >
          <Select
            label="Direction"
            value={sortDir}
            onChange={(e) => setSortDir(e.target.value as 'asc' | 'desc')}
            options={[
              { label: 'asc', value: 'asc' },
              { label: 'desc', value: 'desc' },
            ]}
          />
        </GuidedField>
        <GuidedField
          label="Default limit"
          guide={{
            title: 'Default row limit',
            what: 'Rows returned when the question doesn\'t say how many.',
            why: 'Keeps chat answers readable and token costs bounded.',
          }}
        >
          <Input
            type="number"
            label="Default limit"
            value={defaultLimit}
            onChange={(e) => setDefaultLimit(Number(e.target.value) || 20)}
          />
        </GuidedField>
        <GuidedField
          label="Max limit"
          guide={{
            title: 'Hard row cap',
            what: 'The most rows any single query may return, even if the user asks for more.',
            why: 'Enforced by AST edit on every generated SQL — the LLM cannot exceed it.',
            warn: 'This is a safety bound, not a suggestion — set it to what the chat UI can sensibly render.',
          }}
        >
          <Input
            type="number"
            label="Max limit"
            value={maxLimit}
            onChange={(e) => setMaxLimit(Number(e.target.value) || 100)}
          />
        </GuidedField>
      </fieldset>

      <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
        <Button type="button" variant="outline" tone="neutral" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" isPending={pending} loadingLabel="Saving…">
          {isEditing ? 'Save changes' : 'Create data entity'}
        </Button>
      </div>
    </form>
  )
}
