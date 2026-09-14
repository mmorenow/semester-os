import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from '@/lib/api'
import { activityMeta } from '@/lib/activity'

/**
 * GET /api/calendar-feed. The links carry the feed secret: they live only in the query cache,
 * never in the URL, storage or logs.
 */
export interface CalendarFeedReader {
  client: 'google' | 'apple' | 'outlook' | 'browser' | 'other'
  label: string
  via: 'local' | 'public' | null
  last_fetch_at: string | null
}

export interface CalendarFeed {
  path: string
  local_url: string
  local_webcal_url: string
  public_url: string | null
  public_webcal_url: string | null
  public_base_url: string | null
  created_at: string | null
  rotated_at: string | null
  timezone: string
  window: { start: string; end: string }
  counts: { classes: number; deadlines: number; exams: number; events: number }
  event_count: number
  readers: CalendarFeedReader[]
}

export const connectKeys = {
  feed: ['calendar-feed'] as const,
}

export function useCalendarFeed() {
  return useQuery({
    queryKey: connectKeys.feed,
    queryFn: () => apiRequest<CalendarFeed>('/api/calendar-feed'),
    // No poll: readers arrive on calendar apps' schedules, so refetching on focus is enough.
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    retry: false,
  })
}

/** Every mutation answers with the whole feed, so the cache is replaced, not refetched. */
function useFeedMutation<TVariables>(
  label: string,
  request: (variables: TVariables) => Promise<CalendarFeed>,
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: request,
    meta: activityMeta(label, 'write'),
    onSuccess: (feed) => {
      client.setQueryData(connectKeys.feed, feed)
    },
  })
}

export function useRotateFeed() {
  return useFeedMutation('Rotating the calendar link', () =>
    apiRequest<CalendarFeed>('/api/calendar-feed/rotate', { method: 'POST' }),
  )
}

export function useSetPublicAddress() {
  return useFeedMutation('Saving the public address', (publicBaseUrl: string | null) =>
    apiRequest<CalendarFeed>('/api/calendar-feed/public-url', {
      method: 'PUT',
      body: { public_base_url: publicBaseUrl },
    }),
  )
}
