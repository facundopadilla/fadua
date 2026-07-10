import { useEffect, useRef } from 'react'
import { ChatInput } from '@/components/ChatInput'
import { EmptyState } from '@/components/EmptyState'
import { MessageBubble } from '@/components/MessageBubble'
import type { ChatMessage } from '@/types/chat'

interface ChatPanelProps {
  messages: ChatMessage[]
  onSend: (message: string) => void
  isStreaming: boolean
  errorMessage: string | null
}

export function ChatPanel({ messages, onSend, isStreaming, errorMessage }: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages])

  return (
    <div className="flex h-full flex-1 flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <EmptyState onSelectPrompt={onSend} />
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-6">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} onSuggestionSelect={onSend} />
            ))}
          </div>
        )}
      </div>

      <div className="mx-auto w-full max-w-3xl px-6 pb-6">
        {errorMessage && (
          <p role="alert" className="mb-2 text-xs text-danger">
            {errorMessage}
          </p>
        )}
        <ChatInput onSend={onSend} disabled={isStreaming} />
      </div>
    </div>
  )
}
