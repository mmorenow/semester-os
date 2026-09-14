import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { activityMeta } from '@/lib/activity'
import { apiRequest } from '@/lib/api'
import type { Proposal, SourcesResponse, SyllabusSource } from './onboarding-types'
import { isReading } from './onboarding-types'

export const onboardingKeys = {
  sources: ['onboarding', 'sources'] as const,
}

/** Poll while an agent is reading; same cadence as Notes. */
const READING_POLL_MS = 3000

/** Sources plus unreadable files. The GET rescans `syllabi/`, so files added in Finder show up on the next read. */
export function useSyllabusSources() {
  return useQuery({
    queryKey: onboardingKeys.sources,
    queryFn: () => apiRequest<SourcesResponse>('/api/onboarding/sources'),
    retry: false,
    refetchInterval: (query) => (query.state.data?.sources.some(isReading) ? READING_POLL_MS : false),
    refetchIntervalInBackground: false,
    staleTime: 0,
  })
}

/** Put one returned row into the cached list, replacing the one with its id. */
function useSeedSource() {
  const client = useQueryClient()
  return (source: SyllabusSource) => {
    client.setQueryData<SourcesResponse>(onboardingKeys.sources, (old) => {
      if (!old) return old
      const exists = old.sources.some((row) => row.id === source.id)
      return {
        ...old,
        sources: exists
          ? old.sources.map((row) => (row.id === source.id ? source : row))
          : [source, ...old.sources],
      }
    })
  }
}

function useSettle() {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: onboardingKeys.sources })
    void client.invalidateQueries({ queryKey: ['actions'] })
  }
}

/** One dropped file, as raw bytes. The server names, checks and caps it. */
export function useUploadSyllabus() {
  const seed = useSeedSource()
  const settle = useSettle()
  return useMutation({
    mutationFn: (file: File) =>
      apiRequest<SyllabusSource>(`/api/onboarding/uploads?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST',
        body: file,
      }),
    meta: activityMeta('Saving syllabus', 'write'),
    onSuccess: seed,
    onSettled: settle,
  })
}

export function useAddCourseLink() {
  const seed = useSeedSource()
  const settle = useSettle()
  return useMutation({
    mutationFn: (url: string) =>
      apiRequest<SyllabusSource>('/api/onboarding/links', { method: 'POST', body: { url } }),
    meta: activityMeta('Adding link', 'write'),
    onSuccess: seed,
    onSettled: settle,
  })
}

/** Start the course-importer on one source. Tagged as a run. */
export function useReadSource() {
  const seed = useSeedSource()
  const settle = useSettle()
  return useMutation({
    mutationFn: (id: number) =>
      apiRequest<SyllabusSource>(`/api/onboarding/sources/${String(id)}/read`, { method: 'POST' }),
    meta: activityMeta('Syllabus agent', 'run'),
    onSuccess: seed,
    onSettled: settle,
  })
}

export function useReadAllSources() {
  const settle = useSettle()
  return useMutation({
    mutationFn: () =>
      apiRequest<{ sources: SyllabusSource[] }>('/api/onboarding/read-all', { method: 'POST' }),
    meta: activityMeta('Syllabus agents', 'run'),
    onSettled: settle,
  })
}

/** Review editor autosave. Untagged: a debounced save isn't work to watch. */
export function useSaveProposal() {
  const seed = useSeedSource()
  return useMutation({
    mutationFn: ({ id, proposal }: { id: number; proposal: Proposal }) =>
      apiRequest<SyllabusSource>(`/api/onboarding/sources/${String(id)}/proposal`, {
        method: 'PATCH',
        body: { proposal },
      }),
    onSuccess: seed,
  })
}

/** Confirm the course. Sends the edited proposal so what's written is what was on screen. */
export function useApplySource() {
  const client = useQueryClient()
  const seed = useSeedSource()
  return useMutation({
    mutationFn: ({ id, proposal }: { id: number; proposal: Proposal | null }) =>
      apiRequest<SyllabusSource>(`/api/onboarding/sources/${String(id)}/apply`, {
        method: 'POST',
        body: proposal ? { proposal } : {},
      }),
    meta: activityMeta('Adding course', 'write'),
    onSuccess: seed,
    onSettled: () => {
      void client.invalidateQueries({ queryKey: onboardingKeys.sources })
      void client.invalidateQueries({ queryKey: ['school'] })
    },
  })
}

export function useDiscardSource() {
  const seed = useSeedSource()
  const settle = useSettle()
  return useMutation({
    mutationFn: (id: number) =>
      apiRequest<SyllabusSource>(`/api/onboarding/sources/${String(id)}/discard`, { method: 'POST' }),
    onSuccess: seed,
    onSettled: settle,
  })
}

export function useCreateManualCourse() {
  const seed = useSeedSource()
  const settle = useSettle()
  return useMutation({
    mutationFn: (body: { course_code: string; course_title: string | null }) =>
      apiRequest<SyllabusSource>('/api/onboarding/manual', { method: 'POST', body }),
    onSuccess: seed,
    onSettled: settle,
  })
}

/** Stop a read that is taking too long. The source fails with the reason. */
export function useCancelRead() {
  const settle = useSettle()
  return useMutation({
    mutationFn: (actionId: number) =>
      apiRequest<unknown>(`/api/actions/${String(actionId)}/cancel`, { method: 'POST' }),
    onSettled: settle,
  })
}
