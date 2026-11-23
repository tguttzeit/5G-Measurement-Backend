import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { MissionStatusPage } from './MissionStatusPage'
import { apiClient } from '../api/client'
import { openHeartbeatStream, type HeartbeatStreamHandlers } from '../api/heartbeatStream'

vi.mock('../api/client', () => ({
  apiClient: { get: vi.fn() },
  ApiError: class ApiError extends Error {},
}))
vi.mock('../api/heartbeatStream', () => ({ openHeartbeatStream: vi.fn() }))

const mockGet = vi.mocked(apiClient.get)
const mockOpen = vi.mocked(openHeartbeatStream)

const POLL_INTERVAL_MS = 30000

let handlersByDevice: Record<string, HeartbeatStreamHandlers>
let closeByDevice: Record<string, Mock<() => void>>

function heartbeatCalls() {
  return mockGet.mock.calls.filter(([url]) => url === '/heartbeat').length
}

async function settle(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

async function selectDevice(deviceId: string) {
  fireEvent.click(screen.getByRole('button', { name: new RegExp(deviceId) }))
  await settle()
}

beforeEach(() => {
  vi.useFakeTimers()
  handlersByDevice = {}
  closeByDevice = {}
  mockGet.mockImplementation(async (url: string) => {
    if (url === '/devices') {
      return {
        devices: [
          { device_id: 'device-01', online: true, last_heartbeat_at: null },
          { device_id: 'device-02', online: true, last_heartbeat_at: null },
        ],
      }
    }
    return { heartbeats: [] }
  })
  mockOpen.mockImplementation((deviceId, handlers) => {
    handlersByDevice[deviceId] = handlers
    closeByDevice[deviceId] = vi.fn<() => void>()
    return closeByDevice[deviceId]
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe('MissionStatusPage heartbeat stream', () => {
  it('opens no stream until a device is selected', async () => {
    render(<MissionStatusPage />)
    await settle()

    expect(mockOpen).not.toHaveBeenCalled()
  })

  it('subscribes for the selected device', async () => {
    render(<MissionStatusPage />)
    await settle()

    await selectDevice('device-01')

    expect(mockOpen).toHaveBeenCalledTimes(1)
    expect(mockOpen.mock.calls[0][0]).toBe('device-01')
  })

  it('reloads immediately when a heartbeat event arrives for the selected device', async () => {
    render(<MissionStatusPage />)
    await settle()
    await selectDevice('device-01')
    const before = heartbeatCalls()

    await act(async () => {
      handlersByDevice['device-01'].onHeartbeat({ device_id: 'device-01', received_at: '2026-01-01T00:00:30+00:00' })
    })
    await settle()

    expect(heartbeatCalls()).toBe(before + 1)
  })

  it('closes the stream and subscribes again when the selected device changes', async () => {
    render(<MissionStatusPage />)
    await settle()
    await selectDevice('device-01')

    await selectDevice('device-02')

    expect(closeByDevice['device-01']).toHaveBeenCalledTimes(1)
    expect(mockOpen.mock.calls.map(([id]) => id)).toEqual(['device-01', 'device-02'])
  })

  it('closes the stream on unmount', async () => {
    const { unmount } = render(<MissionStatusPage />)
    await settle()
    await selectDevice('device-01')

    unmount()

    expect(closeByDevice['device-01']).toHaveBeenCalledTimes(1)
  })

  it('stops polling while the stream is connected', async () => {
    render(<MissionStatusPage />)
    await settle()
    await selectDevice('device-01')
    await act(async () => handlersByDevice['device-01'].onConnectionChange?.(true))
    const before = heartbeatCalls()

    await settle(POLL_INTERVAL_MS * 3)

    expect(heartbeatCalls()).toBe(before)
  })

  it('falls back to polling when the stream drops and stops again when it recovers', async () => {
    render(<MissionStatusPage />)
    await settle()
    await selectDevice('device-01')
    await act(async () => handlersByDevice['device-01'].onConnectionChange?.(true))
    await act(async () => handlersByDevice['device-01'].onConnectionChange?.(false))
    const before = heartbeatCalls()

    await settle(POLL_INTERVAL_MS)
    expect(heartbeatCalls()).toBe(before + 1)

    await act(async () => handlersByDevice['device-01'].onConnectionChange?.(true))
    await settle(POLL_INTERVAL_MS * 3)
    expect(heartbeatCalls()).toBe(before + 1)
  })

  it('polls as before when no device is selected', async () => {
    render(<MissionStatusPage />)
    await settle()
    const before = heartbeatCalls()

    await settle(POLL_INTERVAL_MS)

    expect(heartbeatCalls()).toBe(before + 1)
  })
})
