interface MetricsCardsProps {
  metrics: Record<string, number>
}

/** Renders ChatResponse.metrics as a row of compact KPI cards. */
export function MetricsCards({ metrics }: MetricsCardsProps) {
  const entries = Object.entries(metrics)
  if (entries.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2">
      {entries.map(([label, value]) => (
        <div
          key={label}
          className="min-w-[104px] rounded-md border border-border bg-surface px-3 py-2"
        >
          <p className="text-[11px] uppercase tracking-wide text-text-faint">
            {formatLabel(label)}
          </p>
          <p className="mt-0.5 font-mono text-base font-medium text-text">
            {formatValue(label, value)}
          </p>
        </div>
      ))}
    </div>
  )
}

const PERCENT_KEYS = ['ctr', 'roi', 'conversion_rate', 'conversion rate']
const CURRENCY_KEYS = ['cpc', 'cpl', 'cpa', 'roas', 'costo', 'ingreso', 'costo_total', 'ingresos_totales']

function formatLabel(label: string): string {
  return label.replaceAll('_', ' ')
}

function formatValue(label: string, value: number): string {
  const key = label.toLowerCase()

  if (PERCENT_KEYS.some((k) => key.includes(k))) {
    return `${(value * 100).toFixed(1)}%`
  }
  if (CURRENCY_KEYS.some((k) => key.includes(k))) {
    return `$${value.toLocaleString('es-AR', { maximumFractionDigits: 2 })}`
  }
  return value.toLocaleString('es-AR', { maximumFractionDigits: 2 })
}
