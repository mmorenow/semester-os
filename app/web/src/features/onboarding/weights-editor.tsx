import { useState } from 'react'
import { Plus, Trash, WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { Proposal } from './onboarding-types'
import {
  clearUncertainty,
  parseNumber,
  uncertaintyFor,
  weightRows,
  weightsFromRows,
  weightsTotal,
  type WeightRow,
} from './proposal-model'
import { FLAG_BORDER, FlagNote, ReviewSection } from './review-parts'

/** Same tolerance the server flags at: a syllabus writing 33.3 three times adds up. */
const SUM_TOLERANCE = 0.5

/**
 * Grade weights as name/percent rows. An off-100 total warns but never blocks.
 * Rows are local state so a half-typed name survives; unfinished rows aren't saved.
 */
export function WeightsEditor({
  draft,
  manual = false,
  onChange,
}: {
  draft: Proposal
  manual?: boolean
  onChange: (next: Proposal) => void
}) {
  const [rows, setRows] = useState<WeightRow[]>(() => weightRows(draft))
  const total = weightsTotal(rows)
  const off = rows.length > 0 && Math.abs(total - 100) > SUM_TOLERANCE
  const reason = uncertaintyFor(draft, 'grading_weights_pct')

  function commit(next: WeightRow[]) {
    setRows(next)
    onChange(clearUncertainty({ ...draft, grading_weights_pct: weightsFromRows(next) }, 'grading_weights_pct'))
  }

  return (
    <ReviewSection
      id="review-weights"
      title="Grade weights"
      meta={rows.length === 0 ? 'None stated' : `${String(rows.length)} ${rows.length === 1 ? 'category' : 'categories'}`}
      action={
        <Button type="button" size="sm" variant="ghost" onClick={() => setRows([...rows, { name: '', pct: null }])}>
          <Plus data-icon="inline-start" />
          Add category
        </Button>
      }
    >
      {reason ? (
        <FlagNote reason={reason} onDismiss={() => onChange(clearUncertainty(draft, 'grading_weights_pct'))} />
      ) : null}
      {rows.length > 0 ? (
        <div className="flex flex-col">
          <ul className="flex flex-col gap-1.5">
            {rows.map((row, index) => (
              <li key={index} className="grid grid-cols-[minmax(0,1fr)_5.5rem_1.75rem] items-center gap-2">
                <Input
                  value={row.name}
                  onChange={(event) =>
                    commit(rows.map((entry, position) => (position === index ? { ...entry, name: event.target.value } : entry)))
                  }
                  placeholder="Category"
                  aria-label={`Category ${String(index + 1)} name`}
                  className={cn('h-7', reason && FLAG_BORDER)}
                  maxLength={120}
                  autoComplete="off"
                />
                <div className="relative">
                  <Input
                    type="number"
                    inputMode="decimal"
                    min={0}
                    max={100}
                    value={row.pct ?? ''}
                    onChange={(event) =>
                      commit(
                        rows.map((entry, position) =>
                          position === index ? { ...entry, pct: parseNumber(event.target.value) } : entry,
                        ),
                      )
                    }
                    aria-label={`${row.name || `Category ${String(index + 1)}`} percent of the grade`}
                    className="num h-7 pr-6 text-right"
                  />
                  <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[13px] text-muted-foreground" aria-hidden>
                    %
                  </span>
                </div>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => commit(rows.filter((_, position) => position !== index))}
                  aria-label={`Remove ${row.name || `category ${String(index + 1)}`}`}
                >
                  <Trash />
                </Button>
              </li>
            ))}
          </ul>
          <div
            className="mt-2 grid grid-cols-[minmax(0,1fr)_5.5rem_1.75rem] items-center gap-2 border-t border-border pt-2"
            role="status"
          >
            <span className={cn('flex items-center gap-1.5 text-[13px]', off ? 'text-signal-amber' : 'text-muted-foreground')}>
              {off ? <WarningCircle size={14} aria-hidden /> : null}
              {off ? `Adds up to ${total.toFixed(total % 1 === 0 ? 0 : 1)}%, not 100%` : 'Total'}
            </span>
            <span className={cn('num pr-6 text-right text-sm', off ? 'text-signal-amber' : 'text-foreground')}>
              {total.toFixed(total % 1 === 0 ? 0 : 1)}%
            </span>
            <span />
          </div>
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground">
          {manual
            ? 'Add each grading category and its percentage, if you know them.'
            : 'The syllabus states no weights. Add the categories and their percentages if you know them.'}
        </p>
      )}
    </ReviewSection>
  )
}
