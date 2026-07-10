/** Mirrors backend/app/schemas/chat.py — keep in sync with the FastAPI contract. */

export type ChartType = 'line' | 'bar' | 'pie' | 'area'

export interface ChartConfig {
  type: ChartType
  title: string | null
  data: Record<string, unknown>[]
  x_key: string | null
  y_keys: string[]
}

export interface ChatRequest {
  message: string
  conversation_id: string | null
  model: string | null
}

export interface ChatResponse {
  conversation_id: string
  answer: string
  sql: string | null
  chart: ChartConfig | null
  metrics: Record<string, number>
  suggestions: string[]
  execution_time: number
  confidence: number
}

/** Local chat message — assistant messages carry the full ChatResponse once streaming completes. */
export type ChatMessage =
  | { id: string; role: 'user'; content: string }
  | {
      id: string
      role: 'assistant'
      content: string
      streaming: boolean
      response: ChatResponse | null
    }

/** One entry in the sidebar history — persisted to localStorage. */
export interface ConversationSummary {
  id: string
  firstMessage: string
  updatedAt: number
}

/** GET /models response. */
export interface ModelsResponse {
  models: string[]
}
