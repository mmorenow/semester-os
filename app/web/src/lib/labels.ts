import type { ActionStatus, ActionType } from './types'

export const ACTION_TYPE_LABEL: Record<ActionType, string> = {
  school_note: 'Note',
  syllabus_import: 'Syllabus',
}

export const ACTION_STATUS_LABEL: Record<ActionStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  done: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

export function actionTypeLabel(type: ActionType | string): string {
  return (ACTION_TYPE_LABEL as Record<string, string>)[type] ?? type
}
