import { TOKEN_KEY, clearAuthStorage } from '../components/AuthProvider'

// Same-origin API base, see client.ts.
const API_BASE = '/api'

const INITIAL_RETRY_DELAY_MS = 1000
const MAX_RETRY_DELAY_MS = 30000

export interface CommandAckEvent {
  device_id: string
  command_id: number
  command: string
  status: 'success' | 'failed' | 'not_applicable' | 'received'
  error: string | null
  received_at: string
}

export interface CommandAckStreamHandlers {
  onAck: (event: CommandAckEvent) => void
}

// Same fetch()-based approach as heartbeatStream.ts/uploadStream.ts, for the same reason:
// EventSource cannot send the Authorization header this app authenticates with. Global (no
// device filter, see the description of GET /commands/stream in the API reference), so one
// subscription covers every device's acks - a client queuing a command doesn't know in advance
// which device's ack will land first.
export function openCommandAckStream(handlers: CommandAckStreamHandlers): () => void {
  const controller = new AbortController()
  const { signal } = controller
  let retryDelayMs = INITIAL_RETRY_DELAY_MS

  async function connectOnce(): Promise<'retry' | 'stop'> {
    const token = localStorage.getItem(TOKEN_KEY)
    const response = await fetch(`${API_BASE}/commands/stream`, {
      headers: {
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal,
    })

    if (response.status === 401) {
      clearAuthStorage()
      window.location.href = '/login?sessionExpired=1'
      return 'stop'
    }
    // Not a superuser: retrying will never succeed, and there's nothing actionable to show.
    if (response.status === 403) return 'stop'
    if (!response.ok || !response.body) return 'retry'

    retryDelayMs = INITIAL_RETRY_DELAY_MS
    await readFrames(response.body, (frame) => {
      const event = parseAckFrame(frame)
      if (event && !signal.aborted) handlers.onAck(event)
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

function parseAckFrame(frame: string): CommandAckEvent | null {
  let eventName = 'message'
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) eventName = line.slice('event:'.length).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice('data:'.length).trim())
  }
  if (eventName !== 'command_ack') return null

  try {
    const data = JSON.parse(dataLines.join('\n'))
    if (
      typeof data?.device_id === 'string' &&
      typeof data?.command_id === 'number' &&
      typeof data?.command === 'string' &&
      (data?.status === 'success' ||
        data?.status === 'failed' ||
        data?.status === 'not_applicable' ||
        data?.status === 'received') &&
      (data?.error === null || typeof data?.error === 'string') &&
      typeof data?.received_at === 'string'
    ) {
      return {
        device_id: data.device_id,
        command_id: data.command_id,
        command: data.command,
        status: data.status,
        error: data.error,
        received_at: data.received_at,
      }
    }
  } catch {
    // Malformed data: skip the frame.
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
