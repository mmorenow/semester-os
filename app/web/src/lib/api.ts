/**
 * Fetch wrapper for the local API. The token from /api/bootstrap lives only in module memory
 * (never storage, cookies or the URL) and is sent as X-SemesterOS-Token.
 */

let tokenPromise: Promise<string> | null = null
let token: string | null = null

export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string' && detail.trim()) return detail
    }
  } catch {
    // Body was not JSON. Fall back to the status text below.
  }
  return response.statusText || `Request failed with status ${response.status}`
}

async function fetchToken(): Promise<string> {
  const response = await fetch('/api/bootstrap', { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new ApiError(await readErrorDetail(response), response.status)
  }
  const body = (await response.json()) as { token?: string }
  if (!body.token) {
    throw new ApiError('The server did not return an access token.', 500)
  }
  token = body.token
  return body.token
}

function getToken(): Promise<string> {
  if (token) return Promise.resolve(token)
  if (!tokenPromise) {
    tokenPromise = fetchToken().catch((error: unknown) => {
      tokenPromise = null
      throw error
    })
  }
  return tokenPromise
}

/** Drops the cached token so the next call bootstraps again. */
export function resetToken() {
  token = null
  tokenPromise = null
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  /** Health and bootstrap are the two endpoints that take no token. */
  skipToken?: boolean
}

async function send<T>(path: string, options: RequestOptions, retryOn401: boolean): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (!options.skipToken) {
    headers['X-SemesterOS-Token'] = await getToken()
  }
  // A Blob (a dropped file) travels as raw bytes; everything else is JSON.
  const raw = options.body instanceof Blob
  if (options.body !== undefined) {
    headers['Content-Type'] = raw ? 'application/octet-stream' : 'application/json'
  }

  const response = await fetch(path, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : raw ? (options.body as Blob) : JSON.stringify(options.body),
    signal: options.signal,
  })

  if (response.status === 401 && retryOn401 && !options.skipToken) {
    // The server restarted and rotated its token. Bootstrap once more.
    resetToken()
    return send<T>(path, options, false)
  }

  if (!response.ok) {
    throw new ApiError(await readErrorDetail(response), response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return send<T>(path, options, true)
}

export function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}
