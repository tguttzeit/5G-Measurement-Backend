import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GpsFixTestPanel } from './GpsFixTestPanel'
import { apiClient } from '../api/client'
import { openCommandAckStream } from '../api/commandAckStream'
import type { GpsFixTestStatus } from '../api/gpsFixTest'
import type { CommandAckStreamHandlers } from '../api/commandAckStream'
import type { CommandStatusItem } from '../api/commands'

vi.mock('../api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
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

vi.mock('../api/commandAckStream', () => ({ openCommandAckStream: vi.fn() }))

const mockGet = vi.mocked(apiClient.get)
const mockOpenStream = vi.mocked(openCommandAckStream)
const mockPost = vi.mocked(apiClient.post)

const fakeDevices = {
  devices: [{ device_id: 'device-01', online: true, last_heartbeat_at: null }],
}

const inactiveStatus: GpsFixTestStatus = {
  run_active: false,
  num_satellites: null,
  has_fix: null,
  elapsed_s: null,
  updated_at: null,
}

const activeStatus: GpsFixTestStatus = {
  run_active: true,
  num_satellites: 7,
  has_fix: true,
  elapsed_s: 42,
  updated_at: '2026-01-01T00:00:00Z',
}

function commandItem(overrides: Partial<CommandStatusItem> = {}): CommandStatusItem {
  return {
    command_id: 1,
    kind: 'command',
    name: 'run-gps-fix-test-now',
    detail: null,
    state: 'delivered',
    complete: false,
    in_queue: true,
    queued_at: '2026-01-01T00:00:00Z',
    delivered_at: '2026-01-01T00:00:01Z',
    received_at: null,
    result_at: null,
    removed_at: null,
    promoted_at: null,
    expired_at: null,
    expires_at: null,
    error: null,
    ...overrides,
  }
}

function commandStatus(items: CommandStatusItem[]) {
  return {
    items,
    last_heartbeat_at: null,
    heartbeat_interval_s: 30,
    shutdown_confirm_mode: 'intervals' as const,
    shutdown_confirm_intervals: 3,
    shutdown_confirm_seconds: 90,
    shutdown_fail_heartbeats: 10,
  }
}

function mockGetResponses(
  statusResponse: GpsFixTestStatus,
  items: CommandStatusItem[] = [],
) {
  mockOpenStream.mockReturnValue(() => {})
  mockGet.mockImplementation((path: string) => {
    if (path === '/devices') return Promise.resolve(fakeDevices)
    if (path === '/devices/device-01/command-status') return Promise.resolve(commandStatus(items))
    if (path.includes('/gps-fix-test/status')) return Promise.resolve(statusResponse)
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
}

// The panel is collapsed by default and only polls once opened; jsdom fires no toggle event on
// a click of <summary>, so open it the way the browser would.
async function openPanelAndSelectDevice() {
  const details = screen.getByText('Find GPS Fix').closest('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  fireEvent.click(await screen.findByRole('button', { name: /device-01/ }))
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe('GpsFixTestPanel', () => {
  it('does not poll the device while collapsed', async () => {
    mockGetResponses(activeStatus)

    render(<GpsFixTestPanel />)
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/devices'))

    expect(mockGet).not.toHaveBeenCalledWith(expect.stringContaining('/gps-fix-test/status'))
  })

  it('shows no-run-active messaging once a device is selected', async () => {
    mockGetResponses(inactiveStatus)

    render(<GpsFixTestPanel />)
    await openPanelAndSelectDevice()

    await waitFor(() => expect(screen.getByText(/No run active/)).toBeInTheDocument())
  })

  it('shows the live satellite count, fix and elapsed time once a run is active', async () => {
    mockGetResponses(activeStatus)

    render(<GpsFixTestPanel />)
    await openPanelAndSelectDevice()

    await waitFor(() => expect(screen.getByText('7')).toBeInTheDocument())
    expect(screen.getByText('Yes')).toBeInTheDocument()
    expect(screen.getByText('42 s')).toBeInTheDocument()
  })

  it('queues run-gps-fix-test-now when Start is clicked', async () => {
    mockGetResponses(inactiveStatus)
    mockPost.mockResolvedValue({ status: 'ok', command_id: 1 })

    render(<GpsFixTestPanel />)
    await openPanelAndSelectDevice()
    fireEvent.click(await screen.findByRole('button', { name: 'Start GPS fix test' }))

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/devices/device-01/commands', {
        command: 'run-gps-fix-test-now',
      }),
    )
  })

  it('shows the timeline of a sent Start command instead of a waiting banner', async () => {
    mockGetResponses(inactiveStatus, [])
    mockPost.mockResolvedValue({ status: 'ok', command_id: 1 })

    render(<GpsFixTestPanel />)
    await openPanelAndSelectDevice()
    mockGet.mockImplementation((path: string) => {
      if (path === '/devices') return Promise.resolve(fakeDevices)
      if (path === '/devices/device-01/command-status')
        return Promise.resolve(commandStatus([commandItem()]))
      return Promise.resolve(inactiveStatus)
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Start GPS fix test' }))

    expect(await screen.findByLabelText('Progress of Start GPS fix test')).toBeInTheDocument()
    expect(screen.getByText('Sent, waiting for device')).toBeInTheDocument()
    expect(screen.queryByText(/waiting for the device to pick it up/)).not.toBeInTheDocument()
  })

  it('shows only the GPS fix test commands, newest five', async () => {
    const gps = [1, 2, 3, 4, 5, 6].map((id) =>
      commandItem({
        command_id: id,
        name: id % 2 ? 'run-gps-fix-test-now' : 'stop-gps-fix-test-now',
      }),
    )
    mockGetResponses(inactiveStatus, [commandItem({ command_id: 99, name: 'reboot-now' }), ...gps])

    render(<GpsFixTestPanel />)
    await openPanelAndSelectDevice()

    await waitFor(() => expect(screen.getAllByText(/^command #/)).toHaveLength(5))
    expect(screen.queryByText('Reboot')).not.toBeInTheDocument()
  })

  it('updates the timeline when an ack arrives', async () => {
    mockGetResponses(inactiveStatus, [commandItem()])

    render(<GpsFixTestPanel />)
    await openPanelAndSelectDevice()
    expect(await screen.findByText('Sent, waiting for device')).toBeInTheDocument()

    mockGetResponses(inactiveStatus, [
      commandItem({ state: 'success', complete: true, received_at: '2026-01-01T00:00:02Z', result_at: '2026-01-01T00:00:03Z' }),
    ])
    const handlers: CommandAckStreamHandlers = mockOpenStream.mock.calls[0][0]
    act(() => handlers.onAck({
      device_id: 'device-01',
      command_id: 1,
      command: 'run-gps-fix-test-now',
      status: 'success',
      error: null,
      received_at: '2026-01-01T00:00:03Z',
    }))

    await waitFor(() =>
      expect(screen.queryByText('Sent, waiting for device')).not.toBeInTheDocument(),
    )
    expect(screen.getAllByText('Success').length).toBeGreaterThan(0)
  })

  it('does not load command status while collapsed', async () => {
    mockGetResponses(activeStatus)

    render(<GpsFixTestPanel />)
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/devices'))

    expect(mockGet).not.toHaveBeenCalledWith('/devices/device-01/command-status')
    expect(mockOpenStream).not.toHaveBeenCalled()
  })

  it('deletes only the finished GPS fix test commands that are shown', async () => {
    const finished = commandItem({
      command_id: 2,
      name: 'stop-gps-fix-test-now',
      state: 'success',
      complete: true,
      in_queue: false,
      result_at: '2026-01-01T00:00:03Z',
    })
    mockGetResponses(inactiveStatus, [
      commandItem({ command_id: 1 }),
      finished,
      commandItem({ command_id: 99, name: 'reboot-now', state: 'success', complete: true, in_queue: false }),
    ])
    mockPost.mockResolvedValue({ dismissed: [2] })

    render(<GpsFixTestPanel />)
    await openPanelAndSelectDevice()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete shown' }))

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/devices/device-01/command-status/dismiss', {
        command_ids: [2],
      }),
    )
  })

  it('disables Delete shown while every shown command is still in progress', async () => {
    mockGetResponses(inactiveStatus, [commandItem()])

    render(<GpsFixTestPanel />)
    await openPanelAndSelectDevice()

    expect(await screen.findByRole('button', { name: 'Delete shown' })).toBeDisabled()
  })

  it('queues stop-gps-fix-test-now when Stop is clicked', async () => {
    mockGetResponses(activeStatus)
    mockPost.mockResolvedValue({ status: 'ok', command_id: 2 })

    render(<GpsFixTestPanel />)
    await openPanelAndSelectDevice()
    fireEvent.click(await screen.findByRole('button', { name: 'Stop GPS fix test' }))

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/devices/device-01/commands', {
        command: 'stop-gps-fix-test-now',
      }),
    )
  })
})
