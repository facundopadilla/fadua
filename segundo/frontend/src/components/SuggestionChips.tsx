interface SuggestionChipsProps {
  suggestions: string[]
  onSelect: (suggestion: string) => void
  disabled?: boolean
}

/** Clickable follow-up suggestions from ChatResponse.suggestions. */
export function SuggestionChips({ suggestions, onSelect, disabled }: SuggestionChipsProps) {
  if (suggestions.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1.5">
      {suggestions.map((suggestion) => (
        <button
          key={suggestion}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(suggestion)}
          className="rounded-md border border-border bg-surface px-2.5 py-1 text-left text-xs text-text-muted transition-colors hover:border-border-strong hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
        >
          {suggestion}
        </button>
      ))}
    </div>
  )
}
