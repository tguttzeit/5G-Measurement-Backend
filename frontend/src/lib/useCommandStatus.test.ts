import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CommandAckEvent, CommandAckStreamHandlers } from '../api/commandAckStream'
import type { CommandStatusResponse } from '../api/commands'
import { useCommandStatus } from './useCommandStatus'

vi.mock('../api/commands', () => ({ listCommandStatus: vi.fn() }))
vi.mock('../api/commandAckStream', () => ({ openCommandAckStream: vi.fn() }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    body?: unknown
    constructor(message: string, status: number, body?: unknown) {
      super(message)
      this.status = status
      this.body = body
    }
  },
}))

import { ApiError } from '../api/client'
import { openCommandAckStream } from '../api/commandAckStream'
import { listCommandStatus } from '../api/commands'

const mockList = vi.mocked(listCommandStatus)
const mockOpenStream = vi.mocked(openCommandAckStream)

function response(commandIds: number[]): CommandStatusResponse {
  return {
    items: commandIds.map((command_id) => ({
      command_id,
      kind: 'command',
      name: 'run-gps-fix-test-now',
      detail: null,
      state: 'queued',
      complete: false,
      in_queue: true,
      queued_at: '2026-01-01T00:00:00Z',
      delivered_at: null,
      received_at: null,
      result_at: null,
      removed_at: null,
      promoted_at: null,
      expired_at: null,
      expires_at: null,
      error: null,
    })),
    last_heartbeat_at: '2026-01-01T00:00:00Z',
    heartbeat_interval_s: 30,
    shutdown_confirm_mode: 'intervals' as const,
    shutdown_confirm_intervals: 3,
    shutdown_confirm_seconds: 90,
    shutdown_fail_heartbeats: 10,
  }
}

function ack(deviceId: string): CommandAckEvent {
  return {
    device_id: deviceId,
    command_id: 1,
    command: 'run-gps-fix-test-now',
    status: 'received',
    error: null,
    received_at: '2026-01-01T00:00:02Z',
  }
}

// The handlers of the most recently opened ack stream.
function latestHandlers(): CommandAckStreamHandlers {
  return mockOpenStream.mock.calls[mockOpenStream.mock.calls.length - 1][0]
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('useCommandStatus', () => {
  it('loads the items and heartbeat info of the device', async () => {
    mockList.mockResolvedValue(response([1]))
    mockOpenStream.mockReturnValue(() => {})

    const { result } = renderHook(() => useCommandStatus('device-01', { enabled: true }))

    await waitFor(() => expect(result.current.items).toHaveLength(1))
    expect(mockList).toHaveBeenCalledWith('device-01')
    expect(result.current.heartbeat?.heartbeat_interval_s).toBe(30)
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('makes no request and opens no stream while disabled', () => {
    renderHook(() => useCommandStatus('device-01', { enabled: false }))

    expect(mockList).not.toHaveBeenCalled()
    expect(mockOpenStream).not.toHaveBeenCalled()
  })

  it('makes no request and opens no stream without a device', () => {
    renderHook(() => useCommandStatus('', { enabled: true }))

    expect(mockList).not.toHaveBeenCalled()
    expect(mockOpenStream).not.toHaveBeenCalled()
  })

  it('refreshes silently when an ack arrives for its device', async () => {
    mockList.mockResolvedValueOnce(response([1])).mockResolvedValueOnce(response([1, 2]))
    mockOpenStream.mockReturnValue(() => {})

    const { result } = renderHook(() => useCommandStatus('device-01', { enabled: true }))
    await waitFor(() => expect(result.current.items).toHaveLength(1))

    act(() => latestHandlers().onAck(ack('device-01')))

    await waitFor(() => expect(result.current.items).toHaveLength(2))
    expect(result.current.loading).toBe(false)
  })

  it("ignores acks of other devices", async () => {
    mockList.mockResolvedValue(response([1]))
    mockOpenStream.mockReturnValue(() => {})

    const { result } = renderHook(() => useCommandStatus('device-01', { enabled: true }))
    await waitFor(() => expect(result.current.items).toHaveLength(1))

    act(() => latestHandlers().onAck(ack('device-02')))

    expect(mockList).toHaveBeenCalledTimes(1)
  })

  it('reloads on demand with refresh()', async () => {
    mockList.mockResolvedValueOnce(response([1])).mockResolvedValueOnce(response([1, 2]))
    mockOpenStream.mockReturnValue(() => {})

    const { result } = renderHook(() => useCommandStatus('device-01', { enabled: true }))
    await waitFor(() => expect(result.current.items).toHaveLength(1))

    act(() => result.current.refresh())

    await waitFor(() => expect(result.current.items).toHaveLength(2))
  })

  it('reports a failed load as an error', async () => {
    mockList.mockRejectedValue(new ApiError('boom', 500, { detail: 'Database unavailable' }))
    mockOpenStream.mockReturnValue(() => {})

    const { result } = renderHook(() => useCommandStatus('device-01', { enabled: true }))

    await waitFor(() => expect(result.current.error).toBe('Database unavailable'))
  })

  it('closes the stream and clears the items when disabled', async () => {
    const close = vi.fn()
    mockList.mockResolvedValue(response([1]))
    mockOpenStream.mockReturnValue(close)

    const { result, rerender } = renderHook(
      ({ enabled }) => useCommandStatus('device-01', { enabled }),
      { initialProps: { enabled: true } },
    )
    await waitFor(() => expect(result.current.items).toHaveLength(1))

    rerender({ enabled: false })

    expect(close).toHaveBeenCalled()
    expect(result.current.items).toEqual([])
    expect(result.current.heartbeat).toBeNull()
  })

  it('drops the previous device\'s items when the device changes', async () => {
    mockList.mockResolvedValueOnce(response([1])).mockResolvedValueOnce(response([]))
    mockOpenStream.mockReturnValue(() => {})

    const { result, rerender } = renderHook(
      ({ deviceId }) => useCommandStatus(deviceId, { enabled: true }),
      { initialProps: { deviceId: 'device-01' } },
    )
    await waitFor(() => expect(result.current.items).toHaveLength(1))

    rerender({ deviceId: 'device-02' })

    await waitFor(() => expect(mockList).toHaveBeenCalledWith('device-02'))
    await waitFor(() => expect(result.current.items).toEqual([]))
  })

  it('ignores a response that arrives after the device changed', async () => {
    let resolveFirst: (value: CommandStatusResponse) => void = () => {}
    mockList
      .mockReturnValueOnce(new Promise((resolve) => (resolveFirst = resolve)))
      .mockResolvedValueOnce(response([]))
    mockOpenStream.mockReturnValue(() => {})

    const { result, rerender } = renderHook(
      ({ deviceId }) => useCommandStatus(deviceId, { enabled: true }),
      { initialProps: { deviceId: 'device-01' } },
    )
    rerender({ deviceId: 'device-02' })
    await waitFor(() => expect(mockList).toHaveBeenCalledWith('device-02'))

    await act(async () => resolveFirst(response([1])))

    expect(result.current.items).toEqual([])
  })
})
