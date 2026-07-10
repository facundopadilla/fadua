import { useQuery } from '@tanstack/react-query'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8010'

interface HealthResponse {
  status: string
}

async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/health`)
  if (!res.ok) throw new Error(`Health check failed with status ${res.status}`)
  return res.json() as Promise<HealthResponse>
}

/** Polls GET /health so the UI can show a subtle backend-connection indicator. */
export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
    retry: 1,
    staleTime: 15_000,
  })
}
