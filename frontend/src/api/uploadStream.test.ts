import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../components/AuthProvider'
import { openUploadStream } from './uploadStream'

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

function uploadFrame(
  deviceId = 'device-01',
  runIds: (string | null)[] = ['run-01'],
  pointCount = 3,
  receivedAt = '2026-01-01T00:00:30+00:00',
) {
  return `event: upload\ndata: ${JSON.stringify({ device_id: deviceId, run_ids: runIds, point_count: pointCount, received_at: receivedAt })}\n\n`
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

describe('openUploadStream', () => {
  it('requests the global stream (no device filter) with the Bearer token, not in the URL', async () => {
    fetchMock.mockResolvedValue(sseResponse().response)

    const close = openUploadStream({ onUpload: vi.fn() })
    await flush()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/measurements/stream')
    expect(url).not.toContain('test-token')
    expect(init.headers.Authorization).toBe('Bearer test-token')
    expect(init.headers.Accept).toBe('text/event-stream')
    close()
  })

  it('calls onUpload with device_id, run_ids and point_count', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onUpload = vi.fn()

    const close = openUploadStream({ onUpload })
    await flush()
    stream.push(uploadFrame('5gmu_1', ['run-abc'], 3))
    await flush()

    expect(onUpload).toHaveBeenCalledWith({
      device_id: '5gmu_1',
      run_ids: ['run-abc'],
      point_count: 3,
      received_at: '2026-01-01T00:00:30+00:00',
    })
    close()
  })

  it('passes through a null run id (legacy datapoints without an explicit run_id)', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onUpload = vi.fn()

    const close = openUploadStream({ onUpload })
    await flush()
    stream.push(uploadFrame('5gmu_1', [null], 3))
    await flush()

    expect(onUpload).toHaveBeenCalledWith(expect.objectContaining({ run_ids: [null] }))
    close()
  })

  it('ignores keep-alive comments, other event types and malformed data', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onUpload = vi.fn()

    const close = openUploadStream({ onUpload })
    await flush()
    stream.push(': connected\n\n: keep-alive\n\nevent: other\ndata: {}\n\nevent: upload\ndata: not json\n\n')
    await flush()

    expect(onUpload).not.toHaveBeenCalled()
    close()
  })

  it('on 401 clears auth storage, redirects to login and does not retry', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 401 }))
    const location = { href: '/runs' }
    vi.stubGlobal('location', location)

    const close = openUploadStream({ onUpload: vi.fn() })
    await flush()
    await vi.advanceTimersByTimeAsync(120000)

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(location.href).toBe('/login?sessionExpired=1')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    close()
  })

  it('does not retry for a non-superuser (403)', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 403 }))

    const close = openUploadStream({ onUpload: vi.fn() })
    await flush()
    await vi.advanceTimersByTimeAsync(120000)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    close()
  })

  it('reconnects with exponential backoff when the stream ends', async () => {
    const first = sseResponse()
    const second = sseResponse()
    fetchMock.mockResolvedValueOnce(first.response).mockResolvedValueOnce(second.response)

    const close = openUploadStream({ onUpload: vi.fn() })
    await flush()
    first.end()
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    close()
  })

  it('close() aborts the request, stops reconnecting and stops delivering events', async () => {
    const stream = sseResponse()
    fetchMock.mockResolvedValue(stream.response)
    const onUpload = vi.fn()

    const close = openUploadStream({ onUpload })
    await flush()
    const signal: AbortSignal = fetchMock.mock.calls[0][1].signal
    close()
    expect(signal.aborted).toBe(true)

    stream.push(uploadFrame())
    await vi.advanceTimersByTimeAsync(120000)

    expect(onUpload).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
