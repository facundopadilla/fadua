import { useCallback, useRef, useState } from 'react'
import type { ChatResponse } from '@/types/chat'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8010'

interface StreamCallbacks {
  onToken: (text: string) => void
  onDone: (response: ChatResponse) => void
  onError: (message: string) => void
}

/**
 * POST /chat and read the SSE-formatted stream by hand.
 *
 * EventSource can't be used here — it's GET-only and this endpoint is POST.
 * The backend sends `event: token` frames while generating, then exactly one
 * `event: done` frame carrying the full ChatResponse. Frames are separated by
 * a blank line (\n\n), matching the SSE spec.
 *
 * Only one stream runs at a time, but switching conversations must never
 * block on it. `streamingConversationId` tracks which conversation the
 * in-flight stream belongs to (null for a not-yet-created conversation, same
 * shape as App's conversationId), so callers can derive "is streaming" for
 * whichever conversation is currently active — a stream left running after
 * the user switches away no longer reads as "streaming" for the new tab.
 * `cancel()` aborts the underlying fetch outright, for the "delete the
 * conversation that's mid-stream" and "start a brand new conversation" cases
 * where there's no longer any conversation for a stray result to belong to.
 */
export function useChatStream() {
  const [streamingConversationId, setStreamingConversationId] = useState<string | null | undefined>(
    undefined,
  )
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(
    async (
      message: string,
      conversationId: string | null,
      model: string | null,
      callbacks: StreamCallbacks,
    ) => {
      const controller = new AbortController()
      abortRef.current = controller
      setStreamingConversationId(conversationId)

      try {
        const res = await fetch(`${API_URL}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, conversation_id: conversationId, model }),
          signal: controller.signal,
        })

        if (!res.ok || !res.body) {
          throw new Error(`Request failed with status ${res.status}`)
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          // SSE frames are separated by a blank line. Process every complete
          // frame in the buffer, keep the trailing partial frame for next read.
          const frames = buffer.split('\n\n')
          buffer = frames.pop() ?? ''

          for (const frame of frames) {
            const parsed = parseFrame(frame)
            if (!parsed) continue

            if (parsed.event === 'token') {
              const payload = JSON.parse(parsed.data) as { text: string }
              callbacks.onToken(payload.text)
            } else if (parsed.event === 'done') {
              const payload = JSON.parse(parsed.data) as ChatResponse
              callbacks.onDone(payload)
            }
          }
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        const message = err instanceof Error ? err.message : 'Unknown streaming error'
        callbacks.onError(message)
      } finally {
        setStreamingConversationId(undefined)
        abortRef.current = null
      }
    },
    [],
  )

  // Aborts the in-flight stream outright (its fetch/reader rejects and no
  // more callbacks fire). Use only when no conversation should receive the
  // result anymore (e.g. it was just deleted) or when starting fresh. For a
  // plain conversation switch, prefer just navigating away — the stream
  // finishes on its own and persists straight to its own conversation.
  const cancel = useCallback(() => {
    abortRef.current?.abort()
    setStreamingConversationId(undefined)
  }, [])

  return { send, cancel, streamingConversationId }
}

function parseFrame(frame: string): { event: string; data: string } | null {
  let event = ''
  const dataLines: string[] = []

  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trim())
    }
  }

  if (!event || dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}
