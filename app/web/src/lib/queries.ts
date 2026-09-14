import { useQuery } from '@tanstack/react-query'
import { apiRequest, buildQuery } from './api'
import type { ActionsResponse, AgentAction, AppConfig, HealthResponse } from './types'

export const queryKeys = {
  health: ['health'] as const,
  config: ['config'] as const,
  actions: (params: { status?: string; limit?: number }) => ['actions', params] as const,
  action: (id: number) => ['action', id] as const,
}

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => apiRequest<HealthResponse>('/api/health', { skipToken: true }),
    refetchInterval: (query) => (query.state.error ? 3000 : 15000),
    refetchIntervalInBackground: false,
    retry: false,
    staleTime: 5000,
  })
}

/** config.yaml as the server reads it. Changes only when the file does. */
export function useAppConfig() {
  return useQuery({
    queryKey: queryKeys.config,
    queryFn: () => apiRequest<AppConfig>('/api/config'),
    staleTime: 60_000,
  })
}

const LIVE_STATUSES = new Set(['pending', 'running'])

export function isLive(action: Pick<AgentAction, 'status'>): boolean {
  return LIVE_STATUSES.has(action.status)
}

export function useActions(params: { status?: string; limit?: number } = {}) {
  return useQuery({
    queryKey: queryKeys.actions(params),
    queryFn: async () => {
      const response = await apiRequest<ActionsResponse>(`/api/actions${buildQuery({ ...params })}`)
      return Array.isArray(response) ? response : response.items
    },
    // Auto refresh only while something is actually in flight.
    refetchInterval: (query) => {
      const data = query.state.data
      return data && data.some(isLive) ? 3000 : false
    },
  })
}
