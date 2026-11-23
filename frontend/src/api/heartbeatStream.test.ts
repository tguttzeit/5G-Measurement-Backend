import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../components/AuthProvider'
import { openHeartbeatStream } from './heartbeatStream'

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

function heartbeatFrame(deviceId = 'device-01', receivedAt = '2026-01-01T00:00:30+00:00') {
  return `event: heartbeat\ndata: ${JSON.stringify({ device_id: deviceId, received_at: receivedAt })}\n\n`
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

describe('openHeartbeatStream', () => {
  it('requests the device stream with the Bearer token, not in the URL', async () => {
    fetchMock.mockResolvedValue(sseResponse().response)

    const close = openHeartbeatStream('device 01', { onHeartbeat: vi.fn() })
    await flush()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/heartbeat/stream?device_id=device%2001')
    expect(url).not.toContain('test-token')
    expect(init.headers.Authorization).toBe('Bearer test-token')
    expect(init.headers.Accept).toBe('text/event-stream')
    close()
  })

  it('reports connected once the stream opens', async () => {
    fetchMock.mockResolvedValue(sseResponse().response)
    const onConnectionChange = vi.fn()

    const close = openHeartbeatStream('device-01', { onHeartbeat: vi.fn(), onConnectionChange })
    await flush()

    expect(onConnectionChange).toHaveBeenCalledWith(true)
    close()
  })

  it('calls onHeartbeat for each heartbeat frame, including frames split across chunks', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onHeartbeat = vi.fn()

    const close = openHeartbeatStream('device-01', { onHeartbeat })
    await flush()
    const frame = heartbeatFrame()
    stream.push(frame.slice(0, 20))
    await flush()
    expect(onHeartbeat).not.toHaveBeenCalled()
    stream.push(frame.slice(20) + heartbeatFrame('device-01', '2026-01-01T00:01:30+00:00'))
    await flush()

    expect(onHeartbeat).toHaveBeenCalledTimes(2)
    expect(onHeartbeat).toHaveBeenNthCalledWith(1, {
      device_id: 'device-01',
      received_at: '2026-01-01T00:00:30+00:00',
    })
    close()
  })

  it('ignores keep-alive comments, other event types and malformed data', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onHeartbeat = vi.fn()

    const close = openHeartbeatStream('device-01', { onHeartbeat })
    await flush()
    stream.push(': connected\n\n: keep-alive\n\nevent: other\ndata: {}\n\nevent: heartbeat\ndata: not json\n\n')
    await flush()

    expect(onHeartbeat).not.toHaveBeenCalled()
    close()
  })

  it('handles CRLF line endings', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onHeartbeat = vi.fn()

    const close = openHeartbeatStream('device-01', { onHeartbeat })
    await flush()
    stream.push(heartbeatFrame().replaceAll('\n', '\r\n'))
    await flush()

    expect(onHeartbeat).toHaveBeenCalledTimes(1)
    close()
  })

  it('reports disconnected and reconnects with exponential backoff when the stream ends', async () => {
    const first = sseResponse()
    const second = sseResponse()
    const third = sseResponse()
    fetchMock
      .mockResolvedValueOnce(first.response)
      .mockResolvedValueOnce(second.response)
      .mockResolvedValueOnce(third.response)
    const onConnectionChange = vi.fn()

    const close = openHeartbeatStream('device-01', { onHeartbeat: vi.fn(), onConnectionChange })
    await flush()
    first.end()
    await flush()
    expect(onConnectionChange).toHaveBeenLastCalledWith(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(onConnectionChange).toHaveBeenLastCalledWith(true)
    close()
  })

  it('doubles the delay across consecutive failures and caps it', async () => {
    fetchMock.mockRejectedValue(new TypeError('network down'))

    const close = openHeartbeatStream('device-01', { onHeartbeat: vi.fn() })
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(999)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(4000)
    expect(fetchMock).toHaveBeenCalledTimes(4)

    await vi.advanceTimersByTimeAsync(8000 + 16000)
    expect(fetchMock).toHaveBeenCalledTimes(6)
    await vi.advanceTimersByTimeAsync(30000)
    expect(fetchMock).toHaveBeenCalledTimes(7)
    await vi.advanceTimersByTimeAsync(30000)
    expect(fetchMock).toHaveBeenCalledTimes(8)
    close()
  })

  it('resets the backoff after a successful connection', async () => {
    const first = sseResponse()
    fetchMock
      .mockRejectedValueOnce(new TypeError('down'))
      .mockRejectedValueOnce(new TypeError('down'))
      .mockResolvedValueOnce(first.response)
      .mockRejectedValue(new TypeError('down'))

    const close = openHeartbeatStream('device-01', { onHeartbeat: vi.fn() })
    await flush()
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchMock).toHaveBeenCalledTimes(3)

    first.end()
    await flush()
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchMock).toHaveBeenCalledTimes(4)
    close()
  })

  it('retries after a non-OK response', async () => {
    fetchMock
      .mockResolvedValueOnce(new Response('busy', { status: 429 }))
      .mockResolvedValueOnce(sseResponse().response)
    const onConnectionChange = vi.fn()

    const close = openHeartbeatStream('device-01', { onHeartbeat: vi.fn(), onConnectionChange })
    await flush()
    expect(onConnectionChange).not.toHaveBeenCalledWith(true)

    await vi.advanceTimersByTimeAsync(1000)
    expect(onConnectionChange).toHaveBeenCalledWith(true)
    close()
  })

  it('on 401 clears auth storage, redirects to login and does not retry', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 401 }))
    const location = { href: '/mission-status' }
    vi.stubGlobal('location', location)

    const close = openHeartbeatStream('device-01', { onHeartbeat: vi.fn() })
    await flush()
    await vi.advanceTimersByTimeAsync(120000)

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(location.href).toBe('/login?sessionExpired=1')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    close()
  })

  it('does not retry when the device is unknown (404)', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 404 }))

    const close = openHeartbeatStream('device-01', { onHeartbeat: vi.fn() })
    await flush()
    await vi.advanceTimersByTimeAsync(120000)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    close()
  })

  it('close() aborts the request, stops reconnecting and stops delivering events', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onHeartbeat = vi.fn()

    const close = openHeartbeatStream('device-01', { onHeartbeat })
    await flush()
    const signal: AbortSignal = fetchMock.mock.calls[0][1].signal
    close()
    expect(signal.aborted).toBe(true)

    stream.push(heartbeatFrame())
    await vi.advanceTimersByTimeAsync(120000)

    expect(onHeartbeat).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('close() cancels a pending reconnect', async () => {
    fetchMock.mockRejectedValue(new TypeError('down'))

    const close = openHeartbeatStream('device-01', { onHeartbeat: vi.fn() })
    await flush()
    close()
    await vi.advanceTimersByTimeAsync(120000)

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
