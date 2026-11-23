import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../components/AuthProvider'
import { openCommandAckStream } from './commandAckStream'

const encoder = new TextEncoder()

function sseResponse() {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
    },
  })
  return {
    response: new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }),
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    end: () => controller.close(),
  }
}

function ackFrame(
  deviceId = '5gmu_1',
  commandId = 46,
  command = 'reboot-now',
  status: 'success' | 'failed' | 'received' = 'received',
  error: string | null = null,
  receivedAt = '2026-01-01T00:00:30+00:00',
) {
  return `event: command_ack\ndata: ${JSON.stringify({ device_id: deviceId, command_id: commandId, command, status, error, received_at: receivedAt })}\n\n`
}

const flush = () => vi.advanceTimersByTimeAsync(0)

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.setItem(TOKEN_KEY, 'test-token')
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('openCommandAckStream', () => {
  it('requests the global stream with the Bearer token, not in the URL', async () => {
    fetchMock.mockResolvedValue(sseResponse().response)

    const close = openCommandAckStream({ onAck: vi.fn() })
    await flush()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/commands/stream')
    expect(url).not.toContain('test-token')
    expect(init.headers.Authorization).toBe('Bearer test-token')
    expect(init.headers.Accept).toBe('text/event-stream')
    close()
  })

  it('calls onAck with device_id, command_id, command, status and error', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onAck = vi.fn()

    const close = openCommandAckStream({ onAck })
    await flush()
    stream.push(ackFrame('5gmu_1', 46, 'fan-override-now', 'failed', 'Fan control is disabled'))
    await flush()

    expect(onAck).toHaveBeenCalledWith({
      device_id: '5gmu_1',
      command_id: 46,
      command: 'fan-override-now',
      status: 'failed',
      error: 'Fan control is disabled',
      received_at: '2026-01-01T00:00:30+00:00',
    })
    close()
  })

  it('ignores keep-alive comments, other event types and malformed data', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onAck = vi.fn()

    const close = openCommandAckStream({ onAck })
    await flush()
    stream.push(
      ': connected\n\n: keep-alive\n\nevent: other\ndata: {}\n\nevent: command_ack\ndata: not json\n\n',
    )
    await flush()

    expect(onAck).not.toHaveBeenCalled()
    close()
  })

  it('on 401 clears auth storage, redirects to login and does not retry', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 401 }))
    const location = { href: '/status' }
    vi.stubGlobal('location', location)

    const close = openCommandAckStream({ onAck: vi.fn() })
    await flush()
    await vi.advanceTimersByTimeAsync(120000)

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(location.href).toBe('/login?sessionExpired=1')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    close()
  })

  it('does not retry for a non-superuser (403)', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 403 }))

    const close = openCommandAckStream({ onAck: vi.fn() })
    await flush()
    await vi.advanceTimersByTimeAsync(120000)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    close()
  })

  it('close() aborts the request, stops reconnecting and stops delivering events', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onAck = vi.fn()

    const close = openCommandAckStream({ onAck })
    await flush()
    const signal: AbortSignal = fetchMock.mock.calls[0][1].signal
    close()
    expect(signal.aborted).toBe(true)

    stream.push(ackFrame())
    await vi.advanceTimersByTimeAsync(120000)

    expect(onAck).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
