import { humanize } from '@/lib/format'
import type { Course, CoursePerson } from '@/lib/school-types'

/**
 * Contacts parsed from harvester data. `instructors` holds strings or objects; `people` maps a
 * role to a person, a list, names with a shared note, or a sentence.
 */

export interface PersonEntry {
  key: string
  name: string
  email: string | null
  role: string | null
  /** Office, hours, phone and any harvester note, already joined for one line. */
  detail: string | null
}

export interface CourseContacts {
  instructors: PersonEntry[]
  staff: PersonEntry[]
  /** A sentence the harvester attached to the group rather than to a person. */
  note: string | null
}

const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function joinDetail(parts: (string | null | undefined)[]): string | null {
  const kept = parts.map((part) => part?.trim()).filter((part): part is string => Boolean(part))
  return kept.length > 0 ? kept.join(' · ') : null
}

/** `"Ada Example <ada@cs.example.edu>"` splits; a bare name stays whole. */
function fromString(value: string, key: string, role: string | null): PersonEntry | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const match = EMAIL.exec(trimmed)
  const email = match ? match[0] : null
  const name = email ? trimmed.replace(email, '').replace(/[<>(),]/g, '').trim() : trimmed
  return { key, name: name || email || trimmed, email, role, detail: null }
}

function fromPerson(person: CoursePerson, key: string, fallbackRole: string | null): PersonEntry | null {
  const name = asText(person.name)
  if (!name) return null
  return {
    key,
    name,
    email: asText(person.email),
    role: asText(person.role) ?? fallbackRole,
    detail: joinDetail([person.office, person.office_hours, person.phone, person.note]),
  }
}

function readEntry(value: unknown, key: string): PersonEntry[] {
  const role = humanize(key)

  if (typeof value === 'string') {
    const entry = fromString(value, key, role)
    return entry ? [entry] : []
  }

  if (Array.isArray(value)) {
    return value.flatMap((item, index) => readEntry(item, `${key}-${String(index)}`))
  }

  const record = asRecord(value)
  if (!record) return []

  // `{ names: [...], note: "one is assigned per team" }`
  if (Array.isArray(record.names)) {
    const note = asText(record.note);
    return record.names
      .map(asText)
      .filter((name): name is string => name !== null)
      .map((name, index) => ({
        key: `${key}-${String(index)}`,
        name,
        email: null,
        role,
        detail: note,
      }))
  }

  // `{ tas: [...] }` and any other nested grouping.
  if (asText(record.name) === null) {
    return Object.entries(record).flatMap(([childKey, childValue]) =>
      childKey === 'note' ? [] : readEntry(childValue, childKey),
    )
  }

  const entry = fromPerson(record as unknown as CoursePerson, key, role)
  return entry ? [entry] : []
}

export function readCourseContacts(course: Pick<Course, 'instructors' | 'people'> | undefined): CourseContacts {
  if (!course) return { instructors: [], staff: [], note: null }

  const instructors = (course.instructors ?? []).flatMap((value, index) => {
    const key = `instructor-${String(index)}`
    if (typeof value === 'string') {
      const entry = fromString(value, key, null)
      return entry ? [entry] : []
    }
    const entry = fromPerson(value, key, null)
    return entry ? [entry] : []
  })

  const peopleRecord = asRecord(course.people)
  const staff = peopleRecord
    ? Object.entries(peopleRecord).flatMap(([key, value]) => (key === 'note' ? [] : readEntry(value, key)))
    : []

  return {
    instructors,
    staff,
    note: peopleRecord ? asText(peopleRecord.note) : null,
  }
}
