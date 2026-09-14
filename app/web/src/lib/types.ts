/** App-wide API shapes: health, config and agent runs. Semester data lives in `school-types.ts`. */

/** A value the server may send as JSON TEXT or as a parsed structure. */
export type JsonMaybe<T> = T | string | null

/** Agent run types: a typed note or a syllabus import. */
export type ActionType = 'school_note' | 'syllabus_import'
export type ActionStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'

export interface AgentAction {
  id: number
  type: ActionType | string
  payload?: JsonMaybe<Record<string, unknown>>
  status: ActionStatus
  result_md?: string | null
  error?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}

/** The runs list arrives inside an items envelope. A bare array is tolerated. */
export type ActionsResponse = AgentAction[] | { items: AgentAction[]; total?: number }

export interface HealthResponse {
  ok: boolean
  app?: string
  /** False when the Claude Code CLI is not installed. Notes need it; nothing else does. */
  claude_cli: boolean
}

/** GET /api/config: config.yaml as the interface may see it. Feed URLs never leave the server. */
export interface AppConfig {
  timezone: string
  term: string | null
  school_name: string | null
  port: number
  calendar_feeds: Record<string, boolean>
  config_file: boolean
}
