import { useState } from 'react'
import { toast } from 'sonner'
import { useCreateTool, useUpdateTool } from '../../api/tools'
import type { JsonSchema, Tool, ToolType } from '../../api/types'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Select from '../ui/Select'
import ParamSchemaBuilder from './ParamSchemaBuilder'
import ToolTypeConfigFields from './ToolTypeConfigFields'

const EMPTY_SCHEMA: JsonSchema = { type: 'object', properties: {} }

type ToolTemplate = {
  name?: string
  tool_type?: ToolType
  description?: string
  config?: Record<string, any>
  input_schema?: JsonSchema
}

export default function ToolForm({
  tool,
  initialValues,
  onDone,
  onCreated,
}: {
  tool?: Tool
  /** Prefills a create-mode form (e.g. the domain-onboarding wizard
   * scaffolding a search/list/get tool) — ignored once `tool` (edit mode)
   * is set. */
  initialValues?: ToolTemplate
  onDone: () => void
  /** Fires in addition to onDone with the created/updated tool. */
  onCreated?: (tool: Tool) => void
}) {
  const seed = tool ?? initialValues
  const [name, setName] = useState(seed?.name ?? '')
  const [toolType, setToolType] = useState<ToolType>(seed?.tool_type ?? 'http_tool')
  const [description, setDescription] = useState(seed?.description ?? '')
  const [config, setConfig] = useState<Record<string, any>>(seed?.config ?? {})
  const [inputSchema, setInputSchema] = useState<JsonSchema>(seed?.input_schema ?? EMPTY_SCHEMA)
  const createTool = useCreateTool()
  const updateTool = useUpdateTool()
  const isEditing = !!tool
  const pending = createTool.isPending || updateTool.isPending

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const input = { name, tool_type: toolType, description, config, input_schema: inputSchema }
    const onSuccess = (saved: Tool) => {
      toast.success(isEditing ? `Tool "${name}" updated` : `Tool "${name}" created`)
      onCreated?.(saved)
      onDone()
    }
    const onError = (err: unknown) => toast.error((err as Error).message)

    if (isEditing) {
      updateTool.mutate({ id: tool.id, ...input }, { onSuccess, onError })
    } else {
      createTool.mutate(input, { onSuccess, onError })
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Input
        label="Name"
        hideLabel={false}
        required
        value={name}
        onChange={(e) => setName(e.target.value)}
      />

      <Input
        label="Description"
        hideLabel={false}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />

      <Select
        label="Tool type"
        hideLabel={false}
        value={toolType}
        onChange={(e) => {
          setToolType(e.target.value as ToolType)
          setConfig({})
        }}
        options={[
          { label: 'data_query_tool (recommended — LLM writes SQL, no query authoring)', value: 'data_query_tool' },
          { label: 'http_tool', value: 'http_tool' },
          { label: 'sql_tool', value: 'sql_tool' },
          { label: 'mysql_query_tool (fixed query)', value: 'mysql_query_tool' },
          { label: 'mongo_query_tool (fixed filter)', value: 'mongo_query_tool' },
          { label: 'mcp_tool', value: 'mcp_tool' },
          { label: 'retrieval_tool', value: 'retrieval_tool' },
        ]}
      />

      <ToolTypeConfigFields toolType={toolType} config={config} onChange={setConfig} />

      {toolType === 'data_query_tool' && (
        <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:bg-slate-800/50 dark:text-slate-400">
          The input schema for this tool type is derived automatically from the chosen data entity — nothing to
          define below.
        </p>
      )}

      {toolType !== 'data_query_tool' && <ParamSchemaBuilder value={inputSchema} onChange={setInputSchema} />}

      <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
        <Button variant="outline" tone="neutral" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" isPending={pending} loadingLabel="Saving…">
          {isEditing ? 'Save changes' : 'Create tool'}
        </Button>
      </div>
    </form>
  )
}
