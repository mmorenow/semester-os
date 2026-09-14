import { apiRequest } from './api'
import type { GcalConnectResponse } from './school-types'

/**
 * Google OAuth consent round trip, without React. The callback lands on `/?gcal=connected|denied|error`.
 * The popup posts to `window.opener`, but Google's COOP can sever it, so the result also goes over a
 * BroadcastChannel the starting tab acknowledges. Unacknowledged returns are handled where they landed.
 */

export type GcalReturnResult = 'connected' | 'denied' | 'error'

const POPUP_NAME = 'gcal-connect'
const POPUP_FEATURES = 'width=520,height=680'
export const GCAL_MESSAGE_TYPE = 'semester-os:gcal-connect'
const CHANNEL_NAME = 'semester-os-gcal-connect'
/** How long a landed return waits for the starting tab before handling itself. */
const ACK_TIMEOUT_MS = 400

export interface GcalReturnMessage {
  type: typeof GCAL_MESSAGE_TYPE
  kind: 'return' | 'ack'
  id: string
  result: GcalReturnResult
}

function isResult(value: unknown): value is GcalReturnResult {
  return value === 'connected' || value === 'denied' || value === 'error'
}

export function isGcalMessage(value: unknown): value is GcalReturnMessage {
  if (typeof value !== 'object' || value === null) return false
  const data = value as Partial<GcalReturnMessage>
  return data.type === GCAL_MESSAGE_TYPE && typeof data.id === 'string' && isResult(data.result)
}

/** Set while this tab awaits a consent result. Only the asking tab acts on a broadcast, so two tabs never both toast and sync. */
let awaitingReturn = false

export function isAwaitingGcalReturn(): boolean {
  return awaitingReturn
}

export function clearAwaitingGcalReturn() {
  awaitingReturn = false
}

export function openGcalChannel(): BroadcastChannel | null {
  return typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(CHANNEL_NAME)
}

/**
 * Start the consent flow; call from a user gesture. The popup opens on the click, before the request:
 * blockers (Safari especially) refuse one opened after an `await`. If still blocked, falls back to this tab.
 */
export async function startGcalConnect(): Promise<'popup' | 'same-tab'> {
  let popup: Window | null = null
  try {
    popup = window.open('', POPUP_NAME, POPUP_FEATURES)
  } catch {
    popup = null
  }
  if (popup) {
    try {
      popup.document.title = 'Connecting Google Calendar'
    } catch {
      // A popup reused from an earlier attempt may already be cross-origin.
    }
  }

  let authUrl: string
  try {
    authUrl = (await apiRequest<GcalConnectResponse>('/api/school/gcal/connect', { method: 'POST' })).auth_url
    if (!authUrl) throw new Error('The server did not return a Google sign-in link.')
  } catch (error: unknown) {
    popup?.close()
    throw error
  }

  awaitingReturn = true
  if (popup && !popup.closed) {
    popup.location.href = authUrl
    popup.focus()
    return 'popup'
  }
  window.location.assign(authUrl)
  return 'same-tab'
}

/** The `?gcal=` result this page was loaded with, if any. */
export function readGcalReturn(): GcalReturnResult | null {
  const value = new URLSearchParams(window.location.search).get('gcal')
  return isResult(value) ? value : null
}

/** Drop `?gcal=` so a reload does not announce the same result twice. */
export function stripGcalReturn() {
  const url = new URL(window.location.href)
  if (!url.searchParams.has('gcal')) return
  url.searchParams.delete('gcal')
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`)
}

function newId(): string {
  return `${String(Date.now())}-${Math.random().toString(36).slice(2, 10)}`
}

/** Hand a landed return to the starter: `'handed-off'` (this window then closes) or `'here'` if nobody took it. */
export async function handOffGcalReturn(result: GcalReturnResult): Promise<'handed-off' | 'here'> {
  const id = newId()
  const message: GcalReturnMessage = { type: GCAL_MESSAGE_TYPE, kind: 'return', id, result }

  let opener: Window | null = null
  try {
    opener = window.opener as Window | null
  } catch {
    opener = null
  }
  if (opener && opener !== window) {
    try {
      opener.postMessage(message, window.location.origin)
      window.close()
      return 'handed-off'
    } catch {
      // Fall through to the channel.
    }
  }

  const channel = openGcalChannel()
  if (!channel) return 'here'

  const acknowledged = await new Promise<boolean>((resolve) => {
    const timer = window.setTimeout(() => {
      resolve(false)
    }, ACK_TIMEOUT_MS)
    channel.onmessage = (event: MessageEvent) => {
      const data: unknown = event.data
      if (isGcalMessage(data) && data.kind === 'ack' && data.id === id) {
        window.clearTimeout(timer)
        resolve(true)
      }
    }
    channel.postMessage(message)
  })
  channel.close()

  if (acknowledged) {
    window.close()
    return 'handed-off'
  }
  return 'here'
}
