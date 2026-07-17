import type { ConversationSummary } from '../api/chat'

const DAY_MS = 24 * 60 * 60 * 1000

export interface ConversationGroup {
  label: string
  conversations: ConversationSummary[]
}

/** Buckets conversations into Claude/ChatGPT-style recency groups, newest first. */
export function groupConversationsByRecency(conversations: ConversationSummary[]): ConversationGroup[] {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()

  const buckets: Record<string, ConversationSummary[]> = {
    Today: [],
    Yesterday: [],
    'Previous 7 days': [],
    'Previous 30 days': [],
    Older: [],
  }

  for (const conv of conversations) {
    const at = new Date(conv.last_message_at).getTime()
    const daysAgo = Math.floor((startOfToday - at) / DAY_MS)
    if (at >= startOfToday) buckets.Today.push(conv)
    else if (daysAgo <= 1) buckets.Yesterday.push(conv)
    else if (daysAgo <= 7) buckets['Previous 7 days'].push(conv)
    else if (daysAgo <= 30) buckets['Previous 30 days'].push(conv)
    else buckets.Older.push(conv)
  }

  return Object.entries(buckets)
    .filter(([, list]) => list.length > 0)
    .map(([label, list]) => ({ label, conversations: list }))
}
