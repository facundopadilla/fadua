import { useQuery } from '@tanstack/react-query'
import type { ModelsResponse } from '@/types/chat'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8010'

/**
 * Fallback list used when GET /models fails or hasn't shipped yet on the
 * backend. Keeps the selector usable during rollout instead of collapsing to
 * a single option.
 */
const FALLBACK_MODELS = [
  'minimax-m3',
  'minimax-m2.7',
  'minimax-m2.5',
  'kimi-k2.7-code',
  'kimi-k2.6',
  'kimi-k2.5',
  'glm-5.2',
  'glm-5.1',
  'glm-5',
  'deepseek-v4-pro',
  'deepseek-v4-flash',
  'qwen3.7-max',
  'qwen3.7-plus',
  'qwen3.6-plus',
  'qwen3.5-plus',
  'mimo-v2-pro',
  'mimo-v2-omni',
  'mimo-v2.5-pro',
  'mimo-v2.5',
  'hy3-preview',
] as const

async function fetchModels(): Promise<string[]> {
  const res = await fetch(`${API_URL}/models`)
  if (!res.ok) throw new Error(`Models request failed with status ${res.status}`)
  const data = (await res.json()) as ModelsResponse
  if (!Array.isArray(data.models) || data.models.length === 0) {
    throw new Error('Models response was empty')
  }
  return data.models
}

/** Fetches the available LLM model ids. Falls back to a hardcoded list if the backend isn't ready. */
export function useModels() {
  const query = useQuery({
    queryKey: ['models'],
    queryFn: fetchModels,
    staleTime: 5 * 60_000,
    retry: 1,
  })

  return {
    ...query,
    models: query.data ?? [...FALLBACK_MODELS],
    isFallback: !query.data && query.isFetched,
  }
}
