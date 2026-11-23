import { TOKEN_KEY, clearAuthStorage } from '../components/AuthProvider'

// Same-origin API base, see client.ts.
const API_BASE = '/api'

const INITIAL_RETRY_DELAY_MS = 1000
const MAX_RETRY_DELAY_MS = 30000

export interface HeartbeatEvent {
  device_id: string
  received_at: string
}

export interface HeartbeatStreamHandlers {
  onHeartbeat: (event: HeartbeatEvent) => void
  // true once the stream is open, false when it drops (the client then retries on its own).
  onConnectionChange?: (connected: boolean) => void
}

// Why fetch() and not EventSource: EventSource cannot send an Authorization header, and the
// app authenticates with a Bearer token only (a token in the URL would end up in proxy logs).
// That also means no built-in reconnect, hence the backoff loop below.
export function openHeartbeatStream(deviceId: string, handlers: HeartbeatStreamHandlers): () => void {
  const controller = new AbortController()
  const { signal } = controller
  let retryDelayMs = INITIAL_RETRY_DELAY_MS

  async function connectOnce(): Promise<'retry' | 'stop'> {
    const token = localStorage.getItem(TOKEN_KEY)
    const response = await fetch(`${API_BASE}/heartbeat/stream?device_id=${encodeURIComponent(deviceId)}`, {
      headers: {
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal,
    })

    if (response.status === 401) {
      // Same handling as apiClient: whatever invalidated the token, the session is over.
      clearAuthStorage()
      window.location.href = '/login?sessionExpired=1'
      return 'stop'
    }
    // An unknown device will not become known by retrying.
    if (response.status === 404) return 'stop'
    if (!response.ok || !response.body) return 'retry'

    handlers.onConnectionChange?.(true)
    retryDelayMs = INITIAL_RETRY_DELAY_MS
    await readFrames(response.body, (frame) => {
      const event = parseHeartbeatFrame(frame)
      if (event && !signal.aborted) handlers.onHeartbeat(event)
    })
    return 'retry'
  }

  async function run() {
    while (!signal.aborted) {
      let outcome: 'retry' | 'stop' = 'retry'
      try {
        outcome = await connectOnce()
      } catch {
        // Network error or abort; an abort is caught by the loop condition below.
      }
      if (signal.aborted) return
      handlers.onConnectionChange?.(false)
      if (outcome === 'stop') return

      await sleep(retryDelayMs, signal)
      retryDelayMs = Math.min(retryDelayMs * 2, MAX_RETRY_DELAY_MS)
    }
  }

  void run()

  return () => controller.abort()
}

async function readFrames(body: ReadableStream<Uint8Array>, onFrame: (frame: string) => void) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) return
      buffer += decoder.decode(value, { stream: true }).replaceAll('\r\n', '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        onFrame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseHeartbeatFrame(frame: string): HeartbeatEvent | null {
  let eventName = 'message'
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) eventName = line.slice('event:'.length).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice('data:'.length).trim())
  }
  if (eventName !== 'heartbeat') return null

  try {
    const data = JSON.parse(dataLines.join('\n'))
    if (typeof data?.device_id === 'string' && typeof data?.received_at === 'string') {
      return { device_id: data.device_id, received_at: data.received_at }
    }
  } catch {
    // Malformed data: skip the frame, the next heartbeat or the polling fallback recovers.
  }
  return null
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        resolve()
      },
      { once: true },
    )
  })
}
