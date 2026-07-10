import { useCallback, useEffect, useState } from 'react'
import type { ChatMessage, ConversationSummary } from '@/types/chat'

const INDEX_KEY = 'fadua.conversations'
const ACTIVE_KEY = 'fadua.conversations.active'
const MESSAGES_KEY_PREFIX = 'fadua.conversation.messages.'

function messagesKey(id: string) {
  return `${MESSAGES_KEY_PREFIX}${id}`
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // localStorage unavailable (private mode, quota) — history just won't persist.
  }
}

function readIndex(): ConversationSummary[] {
  const parsed = readJson<ConversationSummary[]>(INDEX_KEY, [])
  return Array.isArray(parsed) ? parsed : []
}

function readActiveId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY)
  } catch {
    return null
  }
}

function writeActiveId(id: string | null) {
  try {
    if (id === null) {
      localStorage.removeItem(ACTIVE_KEY)
    } else {
      localStorage.setItem(ACTIVE_KEY, id)
    }
  } catch {
    // localStorage unavailable — active conversation just won't survive a reload.
  }
}

/** Reads a conversation's full persisted message list. Safe to call for an unknown id (returns []). */
export function readConversationMessages(id: string): ChatMessage[] {
  const parsed = readJson<ChatMessage[]>(messagesKey(id), [])
  return Array.isArray(parsed) ? parsed : []
}

/** Persists a conversation's full message list, keyed by its id. */
export function writeConversationMessages(id: string, messages: ChatMessage[]) {
  writeJson(messagesKey(id), messages)
}

function removeConversationMessages(id: string) {
  try {
    localStorage.removeItem(messagesKey(id))
  } catch {
    // ignore
  }
}

/**
 * Client-side conversation history. There is no history endpoint — each
 * conversation is identified by the conversation_id the backend returns.
 *
 * The backend's Redis memory only stores {role, content} text for the LLM —
 * it does not store charts/metrics/sql/suggestions — so this hook is the
 * source of truth for everything the UI needs to re-render a past turn. Both
 * the conversation index (id + first message, for the sidebar) and the full
 * per-conversation message list are persisted to localStorage, independently
 * per conversation id, so switching conversations never touches another
 * conversation's stored messages.
 */
export function useConversations() {
  const [conversations, setConversations] = useState<ConversationSummary[]>(() => readIndex())
  const [activeId, setActiveIdState] = useState<string | null>(() => readActiveId())

  useEffect(() => {
    writeJson(INDEX_KEY, conversations)
  }, [conversations])

  const setActiveId = useCallback((id: string | null) => {
    setActiveIdState(id)
    writeActiveId(id)
  }, [])

  const recordConversation = useCallback((id: string, firstMessage: string) => {
    setConversations((prev) => {
      if (prev.some((c) => c.id === id)) {
        return prev.map((c) => (c.id === id ? { ...c, updatedAt: Date.now() } : c))
      }
      const next: ConversationSummary = { id, firstMessage, updatedAt: Date.now() }
      return [next, ...prev]
    })
  }, [])

  const touchConversation = useCallback((id: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, updatedAt: Date.now() } : c)),
    )
  }, [])

  const deleteConversation = useCallback(
    (id: string) => {
      setConversations((prev) => prev.filter((c) => c.id !== id))
      removeConversationMessages(id)
      if (activeId === id) {
        setActiveId(null)
      }
    },
    [activeId, setActiveId],
  )

  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt)

  return {
    conversations: sorted,
    activeId,
    setActiveId,
    recordConversation,
    touchConversation,
    deleteConversation,
  }
}
