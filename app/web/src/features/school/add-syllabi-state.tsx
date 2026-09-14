import { Link } from 'react-router-dom'
import { Books } from '@phosphor-icons/react'
import { EmptyState } from '@/components/empty-state'
import { Button } from '@/components/ui/button'

/** Empty state for a fresh install: points to Set up. */
export function AddSyllabiState({ size = 'page' }: { size?: 'page' | 'inline' }) {
  return (
    <EmptyState
      size={size}
      icon={Books}
      title="Add your syllabi"
      description="Your semester is empty. Drop in each course's syllabus and Semester OS proposes the course, its weekly schedule, its deadlines and its grade weights for you to confirm."
      action={
        <Button size="sm" asChild>
          <Link to="/setup">Set up your semester</Link>
        </Button>
      }
    />
  )
}
