import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChartRenderer } from '@/components/ChartRenderer'
import { MetricsCards } from '@/components/MetricsCards'
import { SqlDebugPanel } from '@/components/SqlDebugPanel'
import { SuggestionChips } from '@/components/SuggestionChips'
import { cn } from '@/lib/utils'
import type { ChatMessage } from '@/types/chat'

interface MessageBubbleProps {
  message: ChatMessage
  onSuggestionSelect: (text: string) => void
}

export function MessageBubble({ message, onSuggestionSelect }: MessageBubbleProps) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-lg bg-user-bubble px-4 py-2.5 text-user-bubble-text">
          <p className="whitespace-pre-wrap text-[14px] leading-relaxed">{message.content}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="max-w-[85%] text-[14px] leading-relaxed text-text">
        {message.content ? (
          <div className="prose-chat">
            <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
            {message.streaming && <span className="typing-caret" aria-hidden="true" />}
          </div>
        ) : (
          <ThinkingIndicator />
        )}
      </div>

      {message.response && (
        <div className="flex max-w-[85%] flex-col gap-3">
          {message.response.chart && <ChartRenderer chart={message.response.chart} />}

          {Object.keys(message.response.metrics).length > 0 && (
            <MetricsCards metrics={message.response.metrics} />
          )}

          {message.response.sql && <SqlDebugPanel sql={message.response.sql} />}

          {message.response.suggestions.length > 0 && (
            <SuggestionChips
              suggestions={message.response.suggestions}
              onSelect={onSuggestionSelect}
            />
          )}

          <MessageFooter
            executionTime={message.response.execution_time}
            answer={message.response.answer}
          />
        </div>
      )}
    </div>
  )
}

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1 py-1 text-text-faint" role="status" aria-label="Pensando">
      <span className="thinking-dot h-1.5 w-1.5 rounded-full bg-current [animation-delay:0ms]" />
      <span className="thinking-dot h-1.5 w-1.5 rounded-full bg-current [animation-delay:150ms]" />
      <span className="thinking-dot h-1.5 w-1.5 rounded-full bg-current [animation-delay:300ms]" />
    </div>
  )
}

function MessageFooter({ executionTime, answer }: { executionTime: number; answer: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(answer)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="flex items-center gap-3 text-xs text-text-faint">
      <button
        type="button"
        onClick={handleCopy}
        className="flex items-center gap-1 transition-colors hover:text-text-muted"
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
        <span>{copied ? 'Copiado' : 'Copiar respuesta'}</span>
      </button>
      <span className={cn('font-mono')}>{executionTime.toFixed(2)}s</span>
    </div>
  )
}
