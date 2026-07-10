import { ChevronDown } from 'lucide-react'
import { useId } from 'react'

interface ModelSelectorProps {
  models: string[]
  value: string
  onChange: (model: string) => void
  disabled?: boolean
}

/**
 * Formats a model id into a nicer label, e.g. "kimi-k2.7-code" -> "Kimi K2.7 Code".
 * Falls back gracefully for ids that don't follow the dash-separated convention.
 */
function formatModelLabel(id: string): string {
  return id
    .split('-')
    .map((part) => (part.length === 0 ? part : part[0].toUpperCase() + part.slice(1)))
    .join(' ')
}

/** Compact model picker — sends the selected LLM model with each query. */
export function ModelSelector({ models, value, onChange, disabled }: ModelSelectorProps) {
  const selectId = useId()

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={selectId} className="px-0.5 text-[11px] text-text-faint">
        Modelo
      </label>
      <div className="relative">
        <select
          id={selectId}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="w-full appearance-none rounded-md border border-border bg-surface py-1.5 pl-2.5 pr-7 text-[13px] text-text transition-colors hover:border-border-strong focus:border-border-strong focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
        >
          {models.map((model) => (
            <option key={model} value={model}>
              {formatModelLabel(model)}
            </option>
          ))}
        </select>
        <ChevronDown
          size={13}
          className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-faint"
        />
      </div>
    </div>
  )
}
