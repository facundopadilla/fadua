const PROMPTS = [
  '¿Cuántas ventas hubo este año?',
  '¿Cuál fue el ROAS de Google Ads vs Meta Ads?',
  '¿Cuántas ventas habrá el próximo mes?',
  'Mostrame la evolución de ingresos',
]

interface EmptyStateProps {
  onSelectPrompt: (prompt: string) => void
}

export function EmptyState({ onSelectPrompt }: EmptyStateProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <p className="max-w-sm text-[15px] text-text-muted">
        Preguntame sobre ventas, campañas o proyecciones…
      </p>
      <div className="mt-6 grid w-full max-w-md grid-cols-1 gap-2 sm:grid-cols-2">
        {PROMPTS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => onSelectPrompt(prompt)}
            className="rounded-md border border-border bg-surface px-3 py-2.5 text-left text-[13px] text-text-muted transition-colors hover:border-border-strong hover:text-text"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  )
}
