import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ChartConfig } from '@/types/chat'

const SERIES_COLORS = [
  'var(--color-chart-1)',
  'var(--color-chart-2)',
  'var(--color-chart-3)',
  'var(--color-chart-4)',
  'var(--color-chart-5)',
]

const tooltipStyle = {
  background: 'var(--color-surface-raised)',
  border: '1px solid var(--color-border)',
  borderRadius: 6,
  fontSize: 12,
  fontFamily: 'var(--font-sans)',
  color: 'var(--color-text)',
}

const axisTick = { fill: 'var(--color-text-muted)', fontSize: 11 }

interface ChartRendererProps {
  chart: ChartConfig
}

/** Renders the backend-provided ChartConfig with the matching Recharts chart type. */
export function ChartRenderer({ chart }: ChartRendererProps) {
  const yKeys = chart.y_keys.length > 0 ? chart.y_keys : inferYKeys(chart)

  return (
    <div className="w-full rounded-md border border-border bg-surface p-4">
      {chart.title && <p className="mb-3 text-sm font-medium text-text">{chart.title}</p>}
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {renderChart(chart, yKeys)}
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function renderChart(chart: ChartConfig, yKeys: string[]) {
  switch (chart.type) {
    case 'line':
      return (
        <LineChart data={chart.data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey={chart.x_key ?? undefined} tick={axisTick} />
          <YAxis tick={axisTick} />
          <Tooltip contentStyle={tooltipStyle} />
          {yKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {yKeys.map((key, i) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          ))}
        </LineChart>
      )

    case 'area':
      return (
        <AreaChart data={chart.data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey={chart.x_key ?? undefined} tick={axisTick} />
          <YAxis tick={axisTick} />
          <Tooltip contentStyle={tooltipStyle} />
          {yKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {yKeys.map((key, i) => (
            <Area
              key={key}
              type="monotone"
              dataKey={key}
              stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
              fill={SERIES_COLORS[i % SERIES_COLORS.length]}
              fillOpacity={0.15}
              strokeWidth={2}
            />
          ))}
        </AreaChart>
      )

    case 'bar':
      return (
        <BarChart data={chart.data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey={chart.x_key ?? undefined} tick={axisTick} />
          <YAxis tick={axisTick} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'var(--color-accent-soft)' }} />
          {yKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {yKeys.map((key, i) => (
            <Bar
              key={key}
              dataKey={key}
              fill={SERIES_COLORS[i % SERIES_COLORS.length]}
              radius={[3, 3, 0, 0]}
            />
          ))}
        </BarChart>
      )

    case 'pie': {
      const valueKey = yKeys[0] ?? 'value'
      const nameKey = chart.x_key ?? 'name'
      return (
        <PieChart margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Pie
            data={chart.data}
            dataKey={valueKey}
            nameKey={nameKey}
            innerRadius="45%"
            outerRadius="75%"
            paddingAngle={2}
          >
            {chart.data.map((_, i) => (
              <Cell key={i} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
            ))}
          </Pie>
        </PieChart>
      )
    }

    default:
      return <div />
  }
}

/** Fallback when the backend omits y_keys: use every numeric field besides x_key. */
function inferYKeys(chart: ChartConfig): string[] {
  const first = chart.data[0]
  if (!first) return []
  return Object.keys(first).filter(
    (key) => key !== chart.x_key && typeof first[key] === 'number',
  )
}
