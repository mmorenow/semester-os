import { useState } from 'react'
import { ListChecks, Plus, WarningCircle } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/empty-state'
import { useCreateTodo, useTodos, useUpdateTodo } from '@/lib/school-queries'
import { isDone, type Todo } from '@/lib/school-types'
import { DUE_TONE_TEXT, dueLabel } from '@/lib/school-time'
import { cn } from '@/lib/utils'
import { Panel, PanelHeader } from './school-parts'

/** Open items first, each block in due order, undated last. */
function sortTodos(todos: Todo[]): Todo[] {
  return [...todos].sort((a, b) => {
    const doneA = isDone(a)
    const doneB = isDone(b)
    if (doneA !== doneB) return doneA ? 1 : -1
    const dueA = a.due_at ? new Date(a.due_at).getTime() : Number.POSITIVE_INFINITY
    const dueB = b.due_at ? new Date(b.due_at).getTime() : Number.POSITIVE_INFINITY
    if (dueA !== dueB) return dueA - dueB
    return a.id - b.id
  })
}

function TodoRow({ todo, now }: { todo: Todo; now: Date }) {
  const updateTodo = useUpdateTodo()
  const done = isDone(todo)
  const due = dueLabel(todo.due_at, now)
  const inputId = `todo-${String(todo.id)}`

  function toggle(next: boolean) {
    updateTodo.mutate(
      { id: todo.id, patch: { done: next ? 1 : 0 } },
      {
        onError: (error: unknown) => {
          toast.error('Could not update the to-do', {
            description: error instanceof Error ? error.message : 'The server rejected the request.',
          })
        },
      },
    )
  }

  return (
    <li className="flex items-center gap-2 border-b border-border px-2 py-2 last:border-b-0">
      <Checkbox
        id={inputId}
        checked={done}
        onCheckedChange={(checked) => { toggle(checked === true) }}
      />
      <label
        htmlFor={inputId}
        className={cn(
          'min-w-0 flex-1 cursor-pointer truncate text-sm transition-colors duration-150',
          done ? 'text-muted-foreground line-through' : 'text-foreground',
        )}
      >
        {todo.title}
      </label>
      {todo.course_code ? (
        <span className="num shrink-0 text-xs text-muted-foreground">{todo.course_code}</span>
      ) : null}
      {due ? (
        <span className={cn('num shrink-0 text-xs', done ? 'text-muted-foreground' : DUE_TONE_TEXT[due.tone])}>
          {due.label}
        </span>
      ) : null}
    </li>
  )
}

function TodosSkeleton() {
  return (
    <ul>
      {Array.from({ length: 3 }, (_, index) => (
        <li key={index} className="flex items-center gap-2 border-b border-border px-2 py-2.5 last:border-b-0">
          <Skeleton className="size-4 shrink-0 rounded-[4px]" />
          <Skeleton className="h-3.5 flex-1" />
        </li>
      ))}
    </ul>
  )
}

/** Todos: the one thing on Today the user writes. */
export function TodosWidget({ now }: { now: Date }) {
  const todos = useTodos()
  const createTodo = useCreateTodo()
  const [title, setTitle] = useState('')

  const rows = sortTodos(todos.data ?? [])
  const openCount = rows.filter((todo) => !isDone(todo)).length

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = title.trim()
    if (!trimmed || createTodo.isPending) return
    createTodo.mutate(
      { title: trimmed },
      {
        // The input clears when the server has it, not when the key was pressed.
        onSuccess: () => { setTitle('') },
        onError: (error: unknown) => {
          toast.error('Could not add the to-do', {
            description: error instanceof Error ? error.message : 'The server rejected the request.',
          })
        },
      },
    )
  }

  return (
    <Panel>
      <PanelHeader
        title="To-dos"
        meta={
          openCount > 0 ? (
            <>
              <span className="num">{String(openCount)}</span> open
            </>
          ) : undefined
        }
      />

      {todos.isPending ? (
        <TodosSkeleton />
      ) : todos.isError ? (
        <EmptyState
          size="inline"
          icon={WarningCircle}
          title="Could not load to-dos"
          description="The to-do endpoint did not respond. Check that the Semester OS server is still running."
          action={
            <Button size="sm" variant="outline" onClick={() => void todos.refetch()}>
              Try again
            </Button>
          }
        />
      ) : rows.length === 0 ? (
        <EmptyState
          size="inline"
          icon={ListChecks}
          title="No to-dos"
          description="Add anything the schedule does not already carry. Agents file theirs here too."
        />
      ) : (
        <ul className="max-h-[240px] overflow-y-auto">
          {rows.map((todo) => (
            <TodoRow key={todo.id} todo={todo} now={now} />
          ))}
        </ul>
      )}

      <form onSubmit={handleSubmit} className="flex items-center gap-2 border-t border-border p-2">
        <label htmlFor="new-todo" className="sr-only">
          New to-do
        </label>
        <Input
          id="new-todo"
          value={title}
          onChange={(event) => { setTitle(event.target.value) }}
          placeholder="Add a to-do"
          autoComplete="off"
          disabled={todos.isError}
        />
        <Button
          type="submit"
          size="icon"
          aria-label="Add to-do"
          disabled={title.trim() === '' || createTodo.isPending}
        >
          <Plus />
        </Button>
      </form>
    </Panel>
  )
}
