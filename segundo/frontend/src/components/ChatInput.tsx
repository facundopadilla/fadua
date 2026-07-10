import { ArrowUp } from 'lucide-react'
import { type KeyboardEvent, useRef, useState } from 'react'

interface ChatInputProps {
  onSend: (message: string) => void
  disabled?: boolean
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSubmit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleInput = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }

  return (
    <div className="flex items-end gap-2 rounded-lg border border-border bg-surface p-2 focus-within:border-border-strong">
      <label htmlFor="chat-message" className="sr-only">
        Mensaje
      </label>
      <textarea
        id="chat-message"
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={1}
        placeholder="Preguntame sobre ventas, campañas o proyecciones…"
        className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-[14px] leading-relaxed text-text placeholder:text-text-faint focus:outline-none disabled:opacity-50"
      />
      <button
        type="button"
        onClick={handleSubmit}
        disabled={disabled || value.trim().length === 0}
        aria-label="Enviar"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent text-accent-text transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
      >
        <ArrowUp size={16} strokeWidth={2.5} />
      </button>
    </div>
  )
}
