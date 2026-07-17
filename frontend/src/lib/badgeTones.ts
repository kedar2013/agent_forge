import {
  ClipboardList,
  Database,
  DatabaseZap,
  Globe,
  Image,
  Layers,
  type LucideIcon,
  Plug,
  Search,
  Table2,
  Terminal,
  Wand2,
} from 'lucide-react'
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
  self_healing_sql_tool: 'violet',
  read_scratchpad_tool: 'neutral',
}

/** Per-type glyph for the tool's EntityAvatar — paired with TOOL_TYPE_TONE
 * above so each tool_type reads as a distinct color+icon combo at a glance. */
export const TOOL_TYPE_ICON: Record<ToolType, LucideIcon> = {
  http_tool: Globe,
  sql_tool: Database,
  mcp_tool: Plug,
  retrieval_tool: Search,
  image_gen_tool: Image,
  db_schema_tool: Table2,
  nl2sql_query_tool: Terminal,
  mongo_query_tool: DatabaseZap,
  mysql_query_tool: Database,
  data_query_tool: Layers,
  self_healing_sql_tool: Wand2,
  read_scratchpad_tool: ClipboardList,
}

export const AGENT_STATUS_TONE: Record<AgentStatus, BadgeTone> = {
  draft: 'neutral',
  published: 'success',
  archived: 'warning',
}
