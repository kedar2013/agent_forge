import type { BadgeTone } from '../components/ui/Badge'
import type { AgentStatus, ToolType } from '../api/types'

export const TOOL_TYPE_TONE: Record<ToolType, BadgeTone> = {
  http_tool: 'info',
  sql_tool: 'violet',
  mcp_tool: 'teal',
  retrieval_tool: 'amber',
  image_gen_tool: 'success',
  db_schema_tool: 'neutral',
  nl2sql_query_tool: 'violet',
  mongo_query_tool: 'success',
  mysql_query_tool: 'info',
  data_query_tool: 'brand',
}

export const AGENT_STATUS_TONE: Record<AgentStatus, BadgeTone> = {
  draft: 'neutral',
  published: 'success',
  archived: 'warning',
}
