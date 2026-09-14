import { useState } from 'react'
import { EnvelopeSimple, Scales, UsersThree } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/empty-state'
import { formatDate } from '@/lib/format'
import type { Course } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { readCourseContacts, type PersonEntry } from './course-people'
import { isEmptyScheme, readGradingScheme } from './grading-scheme'
import { Panel, PanelHeader } from './school-parts'

/** Late work, AI use, attendance and grade scale as a definition list, each clamped to three lines. */
export function PolicyFacts({ course }: { course: Course | undefined }) {
  const [expanded, setExpanded] = useState(false)
  const scheme = readGradingScheme(course?.grading_scheme)
  const empty = isEmptyScheme(scheme)

  const stamped = scheme.extractedAt ? formatDate(scheme.extractedAt) : null

  return (
    <Panel>
      <PanelHeader
        title="Policies"
        icon={Scales}
        action={
          !empty && (scheme.policies.length > 0 || scheme.scale) ? (
            <button
              type="button"
              onClick={() => { setExpanded((value) => !value) }}
              className="rounded-sm text-xs text-muted-foreground transition-colors hover:text-foreground focus-ring active:scale-[0.98]"
            >
              {expanded ? 'Show less' : 'Show all'}
            </button>
          ) : null
        }
      />

      {empty ? (
        <EmptyState
          size="inline"
          icon={Scales}
          title="No syllabus on file"
          description="Late, AI and attendance rules appear here once this course's syllabus has been read."
        />
      ) : (
        <>
          <dl className="flex flex-col divide-y divide-border">
            {scheme.prose ? (
              <div className="px-3 py-2.5">
                <dd className="text-[13px] leading-relaxed text-foreground/90">{scheme.prose}</dd>
              </div>
            ) : null}

            {scheme.policies.map((fact) => (
              <div key={fact.key} className="flex flex-col gap-1 px-3 py-2.5">
                <dt className="text-xs font-medium text-muted-foreground">{fact.label}</dt>
                <dd
                  className={cn(
                    'text-[13px] leading-relaxed text-foreground/90',
                    !expanded && 'line-clamp-3',
                  )}
                >
                  {fact.text}
                </dd>
              </div>
            ))}

            {scheme.scale ? (
              <div className="flex flex-col gap-1 px-3 py-2.5">
                <dt className="text-xs font-medium text-muted-foreground">Letter scale</dt>
                <dd className={cn('num text-[13px] leading-relaxed text-foreground/90', !expanded && 'line-clamp-3')}>
                  {scheme.scale}
                </dd>
              </div>
            ) : null}
          </dl>

          {scheme.sourceFile ? (
            <p className="border-t border-border px-3 py-2.5 text-xs text-muted-foreground">
              Read from <span className="num">{scheme.sourceFile}</span>
              {stamped ? (
                <>
                  {' on '}
                  <span className="num">{stamped}</span>
                </>
              ) : null}
              . Anything the syllabus did not state is absent here rather than guessed.
            </p>
          ) : null}
        </>
      )}
    </Panel>
  )
}

function PersonRow({ person }: { person: PersonEntry }) {
  return (
    <li className="flex flex-col gap-1 border-b border-border px-3 py-2.5 last:border-b-0">
      <div className="flex items-baseline gap-2">
        <span className="truncate text-sm text-foreground">{person.name}</span>
        {person.role ? (
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">{person.role}</span>
        ) : null}
      </div>
      {person.email ? (
        <a
          href={`mailto:${person.email}`}
          className="num flex w-fit max-w-full items-center gap-1 truncate text-[13px] text-primary underline underline-offset-2 hover:no-underline"
        >
          <EnvelopeSimple size={14} className="shrink-0" />
          {person.email}
        </a>
      ) : null}
      {person.detail ? <p className="text-xs leading-relaxed text-muted-foreground">{person.detail}</p> : null}
    </li>
  )
}

/** Who to write to, with mailto links. */
export function CourseContacts({ course }: { course: Course | undefined }) {
  const [expanded, setExpanded] = useState(false)
  const contacts = readCourseContacts(course)
  const people = [...contacts.instructors, ...contacts.staff]
  const visible = expanded ? people : people.slice(0, 4)

  if (people.length === 0) {
    return (
      <Panel>
        <PanelHeader title="Contacts" icon={UsersThree} />
        <EmptyState
          size="inline"
          icon={UsersThree}
          title="Nobody recorded"
          description="Instructors and TAs appear here once this course's syllabus or roster has been read."
        />
      </Panel>
    )
  }

  return (
    <Panel>
      <PanelHeader
        title="Contacts"
        icon={UsersThree}
        meta={
          <>
            <span className="num">{String(people.length)}</span>{' '}
            {people.length === 1 ? 'person' : 'people'}
          </>
        }
      />
      <ul>
        {visible.map((person) => (
          <PersonRow key={person.key} person={person} />
        ))}
      </ul>
      {contacts.note ? (
        <p className="border-t border-border px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
          {contacts.note}
        </p>
      ) : null}
      {people.length > visible.length || expanded ? (
        <div className="border-t border-border p-2">
          <Button
            variant="ghost"
            size="xs"
            className="text-muted-foreground"
            onClick={() => { setExpanded((value) => !value) }}
          >
            {expanded ? 'Show fewer' : `Show all ${String(people.length)}`}
          </Button>
        </div>
      ) : null}
    </Panel>
  )
}
