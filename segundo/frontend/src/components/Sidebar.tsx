import { MessageSquare, Moon, PlusCircle, Sun, Trash2 } from 'lucide-react'
import { ModelSelector } from '@/components/ModelSelector'
import { cn } from '@/lib/utils'
import type { ConversationSummary } from '@/types/chat'

interface SidebarProps {
  conversations: ConversationSummary[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  theme: 'light' | 'dark'
  onToggleTheme: () => void
  isHealthy: boolean | undefined
  models: string[]
  selectedModel: string
  onSelectModel: (model: string) => void
}

export function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  theme,
  onToggleTheme,
  isHealthy,
  models,
  selectedModel,
  onSelectModel,
}: SidebarProps) {
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center justify-between px-4 py-4">
        <span className="text-sm font-semibold text-text">Fadua Analytics</span>
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            isHealthy === undefined && 'bg-text-faint',
            isHealthy === true && 'bg-accent',
            isHealthy === false && 'bg-danger',
          )}
          title={
            isHealthy === undefined
              ? 'Verificando conexión…'
              : isHealthy
                ? 'Backend conectado'
                : 'Backend no disponible'
          }
        />
      </div>

      <div className="px-3">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-text transition-colors hover:border-border-strong hover:bg-surface-raised"
        >
          <PlusCircle size={15} />
          Nueva conversación
        </button>
      </div>

      <nav className="mt-4 flex-1 overflow-y-auto px-3" aria-label="Historial de conversaciones">
        {conversations.length === 0 ? (
          <p className="px-1 py-2 text-xs text-text-faint">Sin conversaciones todavía.</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {conversations.map((conv) => (
              <li key={conv.id} className="group relative">
                <button
                  type="button"
                  onClick={() => onSelect(conv.id)}
                  aria-current={conv.id === activeId ? 'true' : undefined}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-md py-2 pl-2.5 pr-8 text-left text-[13px] transition-colors',
                    conv.id === activeId
                      ? 'bg-accent-soft text-text'
                      : 'text-text-muted hover:bg-surface-raised hover:text-text',
                  )}
                >
                  <MessageSquare size={13} className="shrink-0 opacity-60" />
                  <span className="truncate">{conv.firstMessage}</span>
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete(conv.id)
                  }}
                  aria-label="Eliminar conversación"
                  title="Eliminar"
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-text-faint opacity-0 transition-colors hover:bg-surface-raised hover:text-danger group-hover:opacity-100 focus-visible:opacity-100"
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </nav>

      <div className="border-t border-border px-3 py-3">
        <ModelSelector models={models} value={selectedModel} onChange={onSelectModel} />
      </div>

      <div className="border-t border-border px-3 py-3">
        <button
          type="button"
          onClick={onToggleTheme}
          className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-[13px] text-text-muted transition-colors hover:bg-surface-raised hover:text-text"
        >
          {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          {theme === 'dark' ? 'Modo claro' : 'Modo oscuro'}
        </button>
      </div>
    </aside>
  )
}
