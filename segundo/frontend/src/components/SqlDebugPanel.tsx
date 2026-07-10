import { ChevronRight, Code2 } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

interface SqlDebugPanelProps {
  sql: string
}

/** Collapsible monospace panel showing the SQL the backend executed. */
export function SqlDebugPanel({ sql }: SqlDebugPanelProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-md border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-xs text-text-muted transition-colors hover:text-text"
      >
        <ChevronRight
          size={13}
          className={cn('transition-transform duration-150', open && 'rotate-90')}
        />
        <Code2 size={13} />
        <span>Mostrar SQL</span>
      </button>
      {open && (
        <pre className="overflow-x-auto border-t border-border px-3 py-2 font-mono text-[12px] leading-relaxed text-text-muted">
          {sql}
        </pre>
      )}
    </div>
  )
}
