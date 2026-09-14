import { humanize } from '@/lib/format'

/**
 * Syllabus facts from `grading_scheme`, read defensively: an object with `policies`, a bare string
 * for hand-typed courses, or null. A course with no scheme yields an empty result.
 */

export interface PolicyFact {
  key: string
  label: string
  text: string
}

export interface GradingScheme {
  policies: PolicyFact[]
  /** The letter scale as the syllabus states it, verbatim. */
  scale: string | null
  /** The extractor's own reading of where the grade actually lives. */
  insights: string[]
  sourceFile: string | null
  extractedAt: string | null
  /** A scheme that is a bare string carries no structure; show it as prose. */
  prose: string | null
}

const LABELS: Record<string, string> = {
  late: 'Late work',
  drops: 'Dropped scores',
  ai: 'AI policy',
  attendance: 'Attendance',
  exams: 'Exams',
  regrade: 'Regrades',
  peer_evaluation: 'Peer evaluation',
  grading: 'Grading',
  collaboration: 'Collaboration',
  extensions: 'Extensions',
}

/** The order students ask these in, not JSON order. */
const ORDER = ['late', 'drops', 'ai', 'attendance', 'exams', 'regrade', 'peer_evaluation', 'collaboration', 'extensions', 'grading']

const EMPTY: GradingScheme = {
  policies: [],
  scale: null,
  insights: [],
  sourceFile: null,
  extractedAt: null,
  prose: null,
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function asTextList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map(asText).filter((entry): entry is string => entry !== null)
}

export function readGradingScheme(
  raw: string | Record<string, unknown> | null | undefined,
): GradingScheme {
  if (raw === null || raw === undefined) return EMPTY

  let value: unknown = raw
  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (!trimmed) return EMPTY
    try {
      value = JSON.parse(trimmed)
    } catch {
      // A hand-typed scheme like "standard curve" is a fact, not a failure.
      return { ...EMPTY, prose: trimmed }
    }
  }

  const record = asRecord(value)
  if (!record) return { ...EMPTY, prose: asText(value) }

  const policyRecord = asRecord(record.policies) ?? {}
  const policies: PolicyFact[] = Object.entries(policyRecord)
    .map(([key, entry]) => {
      const text = asText(entry)
      return text ? { key, label: LABELS[key] ?? humanize(key), text } : null
    })
    .filter((fact): fact is PolicyFact => fact !== null)
    .sort((a, b) => {
      const rankA = ORDER.indexOf(a.key)
      const rankB = ORDER.indexOf(b.key)
      return (rankA === -1 ? ORDER.length : rankA) - (rankB === -1 ? ORDER.length : rankB)
    })

  const source = asRecord(record.source_note)

  return {
    policies,
    scale: asText(record.scale) ?? asText(record.grading_scale),
    insights: asTextList(record.insights),
    sourceFile: source ? asText(source.file) : null,
    extractedAt: source ? asText(source.extracted_at) : null,
    prose: null,
  }
}

export function isEmptyScheme(scheme: GradingScheme): boolean {
  return (
    scheme.policies.length === 0 &&
    scheme.scale === null &&
    scheme.insights.length === 0 &&
    scheme.prose === null
  )
}
