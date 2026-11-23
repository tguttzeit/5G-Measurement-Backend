import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MissionStatusPage } from './MissionStatusPage'
import i18n from '../i18n'
import { apiClient } from '../api/client'
import { openCommandAckStream } from '../api/commandAckStream'
import { dismissCommandStatus, listCommandStatus, queueCommand, type CommandStatusItem, type CommandStatusResponse } from '../api/commands'
import { useAuth } from '../components/AuthProvider'
import { ToastProvider } from '../components/ToastProvider'

vi.mock('../components/AuthProvider', () => ({ useAuth: vi.fn() }))

// Command feedback renders as a toast now, which needs a real ToastProvider above it - the
// messages themselves are still asserted on directly, same as the old inline banner.
function renderPage() {
  return render(
    <ToastProvider>
      <MissionStatusPage />
    </ToastProvider>,
  )
}
vi.mock('../api/commands', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/commands')>()),
  queueCommand: vi.fn(),
  listCommandStatus: vi.fn(),
  dismissCommandStatus: vi.fn(),
}))
vi.mock('../api/commandAckStream', () => ({ openCommandAckStream: vi.fn() }))
vi.mock('../api/client', () => ({
  apiClient: {
    get: vi.fn(),
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

const mockGet = vi.mocked(apiClient.get)
const mockQueueCommand = vi.mocked(queueCommand)
const mockListCommandStatus = vi.mocked(listCommandStatus)
const mockDismissCommandStatus = vi.mocked(dismissCommandStatus)
const mockOpenAckStream = vi.mocked(openCommandAckStream)
const mockUseAuth = vi.mocked(useAuth)

function loginAs(isSuperuser: boolean) {
  mockUseAuth.mockReturnValue({ user: { is_superuser: isSuperuser } } as ReturnType<typeof useAuth>)
}

function commandItem(overrides: Partial<CommandStatusItem> = {}): CommandStatusItem {
  return {
    command_id: 1,
    kind: 'command',
    name: 'reboot-now',
    detail: null,
    state: 'received',
    complete: false,
    in_queue: true,
    queued_at: '2026-01-01T00:00:00Z',
    delivered_at: '2026-01-01T00:00:10Z',
    received_at: '2026-01-01T00:00:20Z',
    result_at: null,
    removed_at: null,
    promoted_at: null,
    expired_at: null,
    expires_at: null,
    error: null,
    ...overrides,
  }
}

function commandStatus(items: CommandStatusItem[], overrides: Partial<CommandStatusResponse> = {}): CommandStatusResponse {
  return {
    items,
    last_heartbeat_at: '2026-01-01T00:00:30Z',
    heartbeat_interval_s: 30,
    shutdown_confirm_mode: 'intervals' as const,
    shutdown_confirm_intervals: 3,
    shutdown_confirm_seconds: 90,
    shutdown_fail_heartbeats: 10,
    ...overrides,
  }
}

const NOW = new Date('2026-01-01T00:01:00Z')

function baseHeartbeat(overrides: Record<string, unknown> = {}) {
  return {
    device_id: 'device-01',
    received_at: '2026-01-01T00:00:30Z',
    datapoints_total: 10,
    datapoints_valid: 9,
    datapoints_invalid: 1,
    pipeline_broken: false,
    storage_pending_files: 3,
    storage_disk_free_bytes: 2048,
    ...overrides,
  }
}

function device(device_id: string, online: boolean) {
  return { device_id, online, last_heartbeat_at: online ? '2026-01-01T00:00:30Z' : null }
}

function mockApi(devices: ReturnType<typeof device>[], heartbeats: ReturnType<typeof baseHeartbeat>[]) {
  mockGet.mockImplementation(async (url: string) => {
    if (url === '/devices') return { devices }
    if (url === '/heartbeat') return { heartbeats }
    throw new Error(`unexpected GET ${url}`)
  })
}

async function selectDevice(deviceId: string) {
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(deviceId) }))
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
  loginAs(true)
  let nextCommandId = 1
  mockQueueCommand.mockImplementation(async () => ({ status: 'queued', command_id: nextCommandId++ }))
  mockListCommandStatus.mockResolvedValue(commandStatus([]))
  mockOpenAckStream.mockReturnValue(() => {})
  localStorage.clear()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe('MissionStatusPage device selector', () => {
  it('lists every registered device, including ones that never sent a heartbeat', async () => {
    mockApi([device('device-01', true), device('device-02', false)], [baseHeartbeat()])

    renderPage()

    expect(await screen.findByRole('button', { name: /device-01/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /device-02/ })).toBeInTheDocument()
  })

  it('marks devices online or offline from the /devices online flag', async () => {
    mockApi([device('device-01', true), device('device-02', false)], [])

    renderPage()

    expect(await screen.findByRole('button', { name: /^online\s*device-01/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^offline\s*device-02/ })).toBeInTheDocument()
  })

  it('shows an empty state for a selected device that never sent a heartbeat', async () => {
    mockApi([device('device-02', false)], [])

    renderPage()
    await selectDevice('device-02')

    expect(screen.getByText(/has not sent a heartbeat yet/i)).toBeInTheDocument()
  })

  it('shows a prompt to select a device before one is chosen', async () => {
    mockApi([device('device-01', true)], [baseHeartbeat()])

    renderPage()

    expect(await screen.findByText(/select a device/i)).toBeInTheDocument()
  })

  it('shows an error banner when loading fails', async () => {
    mockGet.mockRejectedValue(new Error('boom'))

    renderPage()

    await waitFor(() => expect(screen.getByText(/Failed to load/)).toBeInTheDocument())
  })
})

describe('MissionStatusPage phase pipeline', () => {
  it('renders all phases in order and highlights only the current one', async () => {
    mockApi([device('device-01', true)], [baseHeartbeat({ run_phase: 'waiting_for_movement' })])

    renderPage()
    await selectDevice('device-01')

    const pipeline = await screen.findByRole('list', { name: /run phase/i })
    const nodes = within(pipeline).getAllByRole('listitem')
    expect(nodes.map((n) => n.textContent)).toEqual([
      'Recovering pending data',
      'Waiting for GPS fix',
      'Waiting for movement',
      'Idle in Manual Mode',
      'Measuring',
      'Finalizing',
      'Done',
    ])
    expect(nodes.filter((n) => n.getAttribute('aria-current') === 'step')).toEqual([nodes[2]])
  })

  it('highlights no node when run_phase is absent or unknown', async () => {
    mockApi(
      [device('device-01', true), device('device-02', true)],
      [baseHeartbeat(), baseHeartbeat({ device_id: 'device-02', run_phase: '__proto__' })],
    )

    renderPage()
    await selectDevice('device-01')
    const pipeline = await screen.findByRole('list', { name: /run phase/i })
    expect(within(pipeline).getAllByRole('listitem').some((n) => n.hasAttribute('aria-current'))).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: /device-02/ }))
    expect(within(screen.getByRole('list', { name: /run phase/i })).getAllByRole('listitem').some((n) => n.hasAttribute('aria-current'))).toBe(false)
  })

  it.each([
    ['shutting_down', /device is shutting down/i],
    ['rebooting', /device is rebooting/i],
  ])('shows a banner instead of the pipeline for run_phase %s', async (runPhase, expectedText) => {
    mockApi([device('device-01', true)], [baseHeartbeat({ run_phase: runPhase })])

    renderPage()
    await selectDevice('device-01')

    expect(await screen.findByText(expectedText)).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: /run phase/i })).not.toBeInTheDocument()
  })
})

describe('MissionStatusPage tiles', () => {
  it('shows the heartbeat timestamp with a live "ago" computed from now', async () => {
    mockApi([device('device-01', true)], [baseHeartbeat()])

    renderPage()
    await selectDevice('device-01')

    const tile = (await screen.findByText('Latest Heartbeat')).closest('.mission-tile') as HTMLElement
    expect(within(tile).getByText(/30 s ago/)).toBeInTheDocument()
  })

  it('shows the GPS fix breakdown with fix age advanced by time since the heartbeat', async () => {
    mockApi(
      [device('device-01', true)],
      [baseHeartbeat({ run_phase: 'active_measuring', gps_fix: { has_fix: true, num_satellites: 9, fix_age_s: 4 } })],
    )

    renderPage()
    await selectDevice('device-01')

    const tile = (await screen.findByText('GPS Fix')).closest('.mission-tile') as HTMLElement
    expect(within(tile).getByText(/Fix acquired/)).toBeInTheDocument()
    expect(within(tile).getByText(/9 sats/)).toBeInTheDocument()
    expect(within(tile).getByText(/34 s ago/)).toBeInTheDocument()
  })

  it('shows a no-fix status without satellite/age details when absent', async () => {
    mockApi(
      [device('device-01', true)],
      [baseHeartbeat({ gps_fix: { has_fix: false, num_satellites: null, fix_age_s: null } })],
    )

    renderPage()
    await selectDevice('device-01')

    expect(await screen.findByText('No fix')).toBeInTheDocument()
  })

  it('shows Unknown GPS status for older device builds without gps_fix', async () => {
    mockApi([device('device-01', true)], [baseHeartbeat()])

    renderPage()
    await selectDevice('device-01')

    expect(await screen.findByText('Unknown')).toBeInTheDocument()
    expect(screen.queryByText('undefined')).not.toBeInTheDocument()
    expect(screen.queryByText('null')).not.toBeInTheDocument()
  })

  it('shows pending files and formatted disk free', async () => {
    mockApi([device('device-01', true)], [baseHeartbeat()])

    renderPage()
    await selectDevice('device-01')

    const pending = (await screen.findByText('Pending Files')).closest('.mission-tile') as HTMLElement
    expect(within(pending).getByText('3')).toBeInTheDocument()
    const disk = screen.getByText('Disk Free').closest('.mission-tile') as HTMLElement
    expect(within(disk).getByText('2 KB')).toBeInTheDocument()
  })
})

describe('MissionStatusPage state and mode tiles', () => {
  async function openDevice(heartbeatOverrides: Record<string, unknown> = {}) {
    mockApi([device('device-01', true)], [baseHeartbeat(heartbeatOverrides)])
    renderPage()
    await selectDevice('device-01')
    return (await screen.findByText('State')).closest('.mission-tile') as HTMLElement
  }

  it.each([
    ['waiting_for_gps_fix', 'Waiting for GPS fix'],
    ['active_measuring', 'Measuring'],
    ['shutting_down', 'Shutting down'],
    ['rebooting', 'Rebooting'],
    ['manual_mode_idle', 'Idle in Manual Mode'],
    ['recovery_idle', 'Idle (recovery)'],
    ['starting_up', 'Starting up'],
    ['stopping', 'Stopping'],
  ])('shows run_phase %s as "%s" without error styling', async (runPhase, label) => {
    const tile = await openDevice({ run_phase: runPhase })

    const value = within(tile).getByText(label)
    expect(value).not.toHaveClass('mission-tile__value--critical')
  })

  it('shows critical_error bold and red', async () => {
    const tile = await openDevice({ run_phase: 'critical_error' })

    expect(within(tile).getByText('Critical error')).toHaveClass('mission-tile__value--critical')
  })

  it('shows an unknown phase as its raw value and does not crash', async () => {
    const tile = await openDevice({ run_phase: 'brand_new_phase' })

    expect(within(tile).getByText('brand_new_phase')).toBeInTheDocument()
  })

  it('shows a placeholder when no run_phase is reported', async () => {
    const tile = await openDevice()

    expect(within(tile).getByText('–')).toBeInTheDocument()
  })

  it.each([
    ['manual', 'Manual Mode'],
    ['auto', 'Auto Mode'],
  ])('shows system_mode %s as "%s" for a superuser', async (systemMode, label) => {
    await openDevice({ system_mode: systemMode })

    const tile = screen.getByText('Mode').closest('.mission-tile') as HTMLElement
    expect(within(tile).getByText(label)).toBeInTheDocument()
  })

  it('shows the mode to a non-superuser, who never receives current_config', async () => {
    loginAs(false)
    await openDevice({ system_mode: 'auto', current_config: null })

    const tile = screen.getByText('Mode').closest('.mission-tile') as HTMLElement
    expect(within(tile).getByText('Auto Mode')).toBeInTheDocument()
  })

  it.each([[null], ['bogus']])('shows a placeholder for system_mode %s', async (systemMode) => {
    await openDevice({ system_mode: systemMode })

    const tile = screen.getByText('Mode').closest('.mission-tile') as HTMLElement
    expect(within(tile).getByText('–')).toBeInTheDocument()
    expect(within(tile).queryByText('bogus')).not.toBeInTheDocument()
  })
})

describe('MissionStatusPage critical error banner', () => {
  const criticalError = {
    fingerprint: 'gps_reader.read_fix:TimeoutError',
    same_error_count: 3,
    consecutive_reboots: 2,
    action: 'maintenance_mode',
  }

  async function openCriticalError(heartbeatOverrides: Record<string, unknown> = {}) {
    mockApi(
      [device('device-01', true)],
      [baseHeartbeat({ run_phase: 'critical_error', critical_error: criticalError, ...heartbeatOverrides })],
    )
    renderPage()
    await selectDevice('device-01')
    return screen.findByRole('alert')
  }

  it('replaces the pipeline with a danger banner', async () => {
    const banner = await openCriticalError()

    expect(banner).toHaveTextContent(/maintenance mode/i)
    expect(screen.queryByRole('list', { name: /run phase/i })).not.toBeInTheDocument()
  })

  it('shows error count, reboots, action and fingerprint to a superuser', async () => {
    const banner = await openCriticalError()

    expect(banner).toHaveTextContent('3')
    expect(banner).toHaveTextContent('2')
    expect(banner).toHaveTextContent('maintenance_mode')
    expect(banner).toHaveTextContent('gps_reader.read_fix:TimeoutError')
  })

  it('shows no details when the backend withholds them from a non-superuser', async () => {
    loginAs(false)
    const banner = await openCriticalError({ critical_error: null })

    expect(banner).toHaveTextContent(/maintenance mode/i)
    expect(banner).not.toHaveTextContent('maintenance_mode')
  })

  it('renders the fingerprint as plain text, never as HTML', async () => {
    const banner = await openCriticalError({
      critical_error: { ...criticalError, fingerprint: '<img src=x onerror=alert(1)>' },
    })

    expect(banner.querySelector('img')).toBeNull()
    expect(banner).toHaveTextContent('<img src=x onerror=alert(1)>')
  })
})

describe('MissionStatusPage recovery', () => {
  const crashDetails = {
    fingerprint: 'gps_reader.read_fix:TimeoutError',
    same_error_count: 1,
    consecutive_reboots: 1,
    action: 'recovered',
  }

  async function openRecovery(heartbeatOverrides: Record<string, unknown> = {}) {
    mockApi(
      [device('device-01', true)],
      [baseHeartbeat({ run_phase: 'recovery_idle', critical_error: crashDetails, ...heartbeatOverrides })],
    )
    renderPage()
    await selectDevice('device-01')
    return screen.findByRole('status')
  }

  it('shows the crash details to a superuser', async () => {
    const banner = await openRecovery()

    expect(banner).toHaveTextContent(/recovered from a crash/i)
    expect(banner).toHaveTextContent('recovered')
    expect(banner).toHaveTextContent('gps_reader.read_fix:TimeoutError')
  })

  it('shows no details when the backend withholds them from a non-superuser', async () => {
    loginAs(false)
    const banner = await openRecovery({ critical_error: null })

    expect(banner).toHaveTextContent(/recovered from a crash/i)
    expect(banner).not.toHaveTextContent('gps_reader')
  })

  it('renders the fingerprint as plain text, never as HTML', async () => {
    const banner = await openRecovery({ critical_error: { ...crashDetails, fingerprint: '<img src=x onerror=alert(1)>' } })

    expect(banner.querySelector('img')).toBeNull()
  })
})

describe('MissionStatusPage datapoints', () => {
  it('shows the valid count alongside total and invalid', async () => {
    mockApi([device('device-01', true)], [baseHeartbeat({ datapoints_total: 1500, datapoints_valid: 1400, datapoints_invalid: 100 })])

    renderPage()
    await selectDevice('device-01')

    const total = (await screen.findByText('Total')).closest('.mission-tile') as HTMLElement
    expect(within(total).getByText('1,500')).toBeInTheDocument()
    const valid = screen.getByText('Valid').closest('.mission-tile') as HTMLElement
    expect(within(valid).getByText('1,400')).toBeInTheDocument()
    const invalid = screen.getByText('Invalid').closest('.mission-tile') as HTMLElement
    expect(within(invalid).getByText('100')).toBeInTheDocument()
    expect(screen.queryByText('Good')).not.toBeInTheDocument()
    expect(screen.queryByText('Bad')).not.toBeInTheDocument()
  })

  it('groups digits like the selected language', async () => {
    mockApi([device('device-01', true)], [baseHeartbeat({ datapoints_total: 1500, datapoints_valid: 1400, datapoints_invalid: 100 })])

    renderPage()
    await selectDevice('device-01')
    await act(() => i18n.changeLanguage('de'))

    const total = (await screen.findByText('Gesamt')).closest('.mission-tile') as HTMLElement
    expect(within(total).getByText('1.500')).toBeInTheDocument()
  })

  it('exposes the valid:invalid ratio as an accessible gauge', async () => {
    mockApi([device('device-01', true)], [baseHeartbeat({ datapoints_total: 100, datapoints_valid: 75, datapoints_invalid: 25 })])

    renderPage()
    await selectDevice('device-01')

    const gauge = await screen.findByRole('img', { name: /75% valid/i })
    expect(gauge).toBeInTheDocument()
  })

  it('renders an empty gauge without dividing by zero when there are no datapoints', async () => {
    mockApi([device('device-01', true)], [baseHeartbeat({ datapoints_total: 0, datapoints_valid: 0, datapoints_invalid: 0 })])

    renderPage()
    await selectDevice('device-01')

    expect(await screen.findByRole('img', { name: /no datapoints/i })).toBeInTheDocument()
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
  })
})

describe('MissionStatusPage remote commands', () => {
  const BUTTON_NAMES = [
    'Start measuring',
    'Stop measuring',
    'Force upload',
    'Reboot',
    'Shut down',
    /^(Auto|Manual) mode$/,
  ]

  async function openDevice(heartbeatOverrides: Record<string, unknown> = {}, online = true) {
    mockApi([device('device-01', online)], [baseHeartbeat(heartbeatOverrides)])
    renderPage()
    await selectDevice('device-01')
    await screen.findByRole('list', { name: /run phase/i })
  }

  async function confirmDialog() {
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^(Confirm|Queue)/ }))
  }

  it('shows the command buttons to superusers', async () => {
    await openDevice()

    for (const name of BUTTON_NAMES) {
      expect(screen.getAllByRole('button', { name }).length).toBeGreaterThan(0)
    }
  })

  it('hides the command buttons from non-superusers', async () => {
    loginAs(false)
    await openDevice()

    for (const name of BUTTON_NAMES) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
  })

  it('queues nothing until the dialog is confirmed, and nothing when it is cancelled', async () => {
    await openDevice()

    fireEvent.click(screen.getByRole('button', { name: 'Force upload' }))
    const dialog = await screen.findByRole('dialog')
    expect(mockQueueCommand).not.toHaveBeenCalled()

    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mockQueueCommand).not.toHaveBeenCalled()
  })

  it.each([
    ['Start measuring', 'start-measuring-now'],
    ['Stop measuring', 'stop-measuring-now'],
    ['Force upload', 'force-upload-now'],
    ['Reboot', 'reboot-now'],
    ['Shut down', 'shutdown-now'],
  ])('%s queues %s after confirmation and reports delivery on next heartbeat', async (label, command) => {
    await openDevice()

    fireEvent.click(screen.getByRole('button', { name: label }))
    await confirmDialog()

    expect(await screen.findByText('Command queued, sent with the next heartbeat')).toBeInTheDocument()
    expect(mockQueueCommand).toHaveBeenCalledExactlyOnceWith('device-01', { command })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('hints in the dialog that the command waits when the device is offline, and still allows queuing', async () => {
    await openDevice({}, false)

    fireEvent.click(screen.getByRole('button', { name: 'Force upload' }))
    const dialog = await screen.findByRole('dialog')

    expect(within(dialog).getByText(/device is offline/i)).toBeInTheDocument()
    await confirmDialog()
    expect(await screen.findByText('Command queued, sent with the next heartbeat')).toBeInTheDocument()
  })

  it('shows no offline hint for an online device', async () => {
    await openDevice()

    fireEvent.click(screen.getByRole('button', { name: 'Force upload' }))

    expect(within(await screen.findByRole('dialog')).queryByText(/device is offline/i)).not.toBeInTheDocument()
  })

  it('keeps the dialog open and shows the error when queuing fails', async () => {
    await openDevice()
    mockQueueCommand.mockRejectedValueOnce(new Error('boom'))

    fireEvent.click(screen.getByRole('button', { name: 'Reboot' }))
    await confirmDialog()

    expect(await within(screen.getByRole('dialog')).findByText(/Failed to queue command/)).toBeInTheDocument()
    expect(screen.queryByText('Command queued, sent with the next heartbeat')).not.toBeInTheDocument()
  })

  describe('Start/Stop gating', () => {
    it('enables Start only while idle in Manual Mode, and Stop only while measuring', async () => {
      await openDevice({ run_phase: 'manual_mode_idle', system_mode: 'manual' })

      expect(screen.getByRole('button', { name: 'Start measuring' })).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Stop measuring' })).toBeDisabled()
    })

    it.each(['auto', 'manual'])('enables Start in recovery_idle in %s mode', async (systemMode) => {
      mockApi([device('device-01', true)], [baseHeartbeat({ run_phase: 'recovery_idle', system_mode: systemMode })])
      renderPage()
      await selectDevice('device-01')

      expect(await screen.findByRole('button', { name: 'Start measuring' })).toBeEnabled()
    })

    it.each(['starting_up', 'stopping'])('disables Start in %s', async (runPhase) => {
      await openDevice({ run_phase: runPhase, system_mode: 'manual' })

      expect(screen.getByRole('button', { name: 'Start measuring' })).toBeDisabled()
    })

    it('enables Stop and disables Start while measuring', async () => {
      await openDevice({ run_phase: 'active_measuring', system_mode: 'manual' })

      expect(screen.getByRole('button', { name: 'Start measuring' })).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Stop measuring' })).toBeEnabled()
    })

    it('disables Start in Auto Mode even when the run phase is manual_mode_idle', async () => {
      await openDevice({ run_phase: 'manual_mode_idle', system_mode: 'auto' })

      expect(screen.getByRole('button', { name: 'Start measuring' })).toBeDisabled()
    })

    it('keeps Start and Stop enabled when run_phase and mode are missing (older device builds)', async () => {
      await openDevice()

      expect(screen.getByRole('button', { name: 'Start measuring' })).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Stop measuring' })).toBeEnabled()
    })

    it('treats an unrecognised system_mode as unknown', async () => {
      await openDevice({ run_phase: 'active_measuring', system_mode: 'bogus' })

      expect(screen.getByRole('button', { name: 'Start measuring' })).toBeEnabled()
    })

    it('keeps Start enabled when only mode is missing and the run phase allows it', async () => {
      await openDevice({ run_phase: 'manual_mode_idle', system_mode: null })

      expect(screen.getByRole('button', { name: 'Start measuring' })).toBeEnabled()
    })

    it('never gates Force upload, Reboot, Shut down or the mode switch', async () => {
      await openDevice({ run_phase: 'finalizing', system_mode: 'auto' })

      for (const name of ['Force upload', 'Reboot', 'Shut down', 'Manual mode']) {
        expect(screen.getByRole('button', { name })).toBeEnabled()
      }
    })
  })

  describe('mode switch', () => {
    it('offers the opposite of the reported mode', async () => {
      await openDevice({ system_mode: 'manual' })

      expect(screen.getByRole('button', { name: 'Auto mode' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Manual mode' })).not.toBeInTheDocument()
    })

    it('offers both directions while the device does not report its mode', async () => {
      await openDevice()

      expect(screen.getByRole('button', { name: 'Auto mode' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Manual mode' })).toBeInTheDocument()
    })

    it('queues only the mode command when "Reboot afterwards" is left unchecked', async () => {
      await openDevice({ system_mode: 'manual' })

      fireEvent.click(screen.getByRole('button', { name: 'Auto mode' }))
      const dialog = await screen.findByRole('dialog')
      expect(within(dialog).getByRole('checkbox', { name: 'Reboot afterwards' })).not.toBeChecked()
      await confirmDialog()

      expect(await screen.findByText('Command queued, sent with the next heartbeat')).toBeInTheDocument()
      expect(mockQueueCommand.mock.calls).toEqual([['device-01', { command: 'mode-auto-now' }]])
    })

    it('queues the mode command, then the reboot, when "Reboot afterwards" is checked', async () => {
      await openDevice({ system_mode: 'auto' })

      fireEvent.click(screen.getByRole('button', { name: 'Manual mode' }))
      const dialog = await screen.findByRole('dialog')
      fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Reboot afterwards' }))
      await confirmDialog()

      expect(await screen.findByText('Command queued, sent with the next heartbeat')).toBeInTheDocument()
      expect(mockQueueCommand.mock.calls).toEqual([
        ['device-01', { command: 'mode-manual-now' }],
        ['device-01', { command: 'reboot-now' }],
      ])
    })

    it('waits for the mode command to be queued before queuing the reboot', async () => {
      await openDevice({ system_mode: 'auto' })
      let resolveMode: (value: { status: string; command_id: number }) => void = () => {}
      mockQueueCommand.mockReset()
      mockQueueCommand.mockImplementationOnce(() => new Promise((resolve) => (resolveMode = resolve)))
      mockQueueCommand.mockResolvedValue({ status: 'queued', command_id: 2 })

      fireEvent.click(screen.getByRole('button', { name: 'Manual mode' }))
      const dialog = await screen.findByRole('dialog')
      fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Reboot afterwards' }))
      await confirmDialog()

      await waitFor(() => expect(mockQueueCommand).toHaveBeenCalledTimes(1))
      expect(mockQueueCommand).toHaveBeenLastCalledWith('device-01', { command: 'mode-manual-now' })

      resolveMode({ status: 'queued', command_id: 1 })

      await waitFor(() => expect(mockQueueCommand).toHaveBeenCalledTimes(2))
      expect(mockQueueCommand).toHaveBeenLastCalledWith('device-01', { command: 'reboot-now' })
    })

    it('does not queue the reboot when the mode command fails', async () => {
      await openDevice({ system_mode: 'auto' })
      mockQueueCommand.mockReset()
      mockQueueCommand.mockRejectedValueOnce(new Error('boom'))

      fireEvent.click(screen.getByRole('button', { name: 'Manual mode' }))
      const dialog = await screen.findByRole('dialog')
      fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Reboot afterwards' }))
      await confirmDialog()

      expect(await within(screen.getByRole('dialog')).findByText(/Failed to queue command/)).toBeInTheDocument()
      expect(mockQueueCommand).toHaveBeenCalledTimes(1)
    })

    it('reports a partial result when the mode command is queued but the reboot fails', async () => {
      await openDevice({ system_mode: 'auto' })
      mockQueueCommand.mockReset()
      mockQueueCommand.mockResolvedValueOnce({ status: 'queued', command_id: 1 })
      mockQueueCommand.mockRejectedValueOnce(new Error('boom'))

      fireEvent.click(screen.getByRole('button', { name: 'Manual mode' }))
      const dialog = await screen.findByRole('dialog')
      fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Reboot afterwards' }))
      await confirmDialog()

      expect(await screen.findByText(/Mode switch was queued, but queuing the reboot failed/)).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

  describe('command status timeline', () => {
    const OPEN_KEY = 'mission-status.command-status-open'

    function panel() {
      return screen.getByText(/^Command status/).closest('details')!
    }

    function toggle() {
      fireEvent.click(screen.getByText(/^Command status/))
    }

    it('is hidden from non-superusers, which also request no command status', async () => {
      loginAs(false)
      await openDevice()

      expect(screen.queryByText(/^Command status/)).not.toBeInTheDocument()
      expect(mockListCommandStatus).not.toHaveBeenCalled()
      expect(mockOpenAckStream).not.toHaveBeenCalled()
    })

    it('is collapsed by default and says so when no command was sent yet', async () => {
      await openDevice()

      expect(panel().open).toBe(false)
      expect(await screen.findByText(/No commands yet/)).toBeInTheDocument()
      expect(mockListCommandStatus).toHaveBeenCalledWith('device-01')
    })

    it('summarises the newest matching command and its state', async () => {
      mockListCommandStatus.mockResolvedValue(
        commandStatus([
          commandItem({ command_id: 3, name: 'reboot-now', state: 'received' }),
          commandItem({ command_id: 2, name: 'force-upload-now', state: 'success' }),
        ]),
      )
      await openDevice()

      await waitFor(() => expect(panel().querySelector('summary')).toHaveTextContent('Command status - Reboot - Received'))
    })

    it('lists only the commands of the buttons, never config overrides or other commands', async () => {
      mockListCommandStatus.mockResolvedValue(
        commandStatus([
          commandItem({ command_id: 4, name: 'mode-auto-now' }),
          commandItem({ command_id: 3, kind: 'config', name: 'upload_interval_s', detail: '60' }),
          commandItem({ command_id: 2, name: 'run-gps-fix-test-now' }),
          commandItem({ command_id: 1, name: 'start-measuring-now' }),
        ]),
      )
      await openDevice()
      toggle()

      await screen.findAllByText(/Auto mode - /)
      const listed = [...document.querySelectorAll('.command-status__name')]
      expect(listed.map((el) => el.textContent)).toEqual(['Auto mode', 'Start measuring'])
      expect(listed.map((el) => el.getAttribute('title'))).toEqual(['mode-auto-now', 'start-measuring-now'])
      expect(screen.queryByText(/upload_interval_s/)).not.toBeInTheDocument()
      expect(screen.queryByText('Start GPS fix test')).not.toBeInTheDocument()
    })

    it('shows at most the 5 most recent items', async () => {
      mockListCommandStatus.mockResolvedValue(
        commandStatus([6, 5, 4, 3, 2, 1].map((id) => commandItem({ command_id: id }))),
      )
      await openDevice()
      toggle()

      expect(await screen.findByText('command #6')).toBeInTheDocument()
      expect(screen.getByText('command #2')).toBeInTheDocument()
      expect(screen.queryByText('command #1')).not.toBeInTheDocument()
    })

    it('expands after a command was queued from the page and refreshes the status', async () => {
      await openDevice()
      await screen.findByText(/No commands yet/)
      const callsBefore = mockListCommandStatus.mock.calls.length
      expect(panel().open).toBe(false)

      fireEvent.click(screen.getByRole('button', { name: 'Force upload' }))
      await confirmDialog()

      await waitFor(() => expect(panel().open).toBe(true))
      expect(mockListCommandStatus.mock.calls.length).toBeGreaterThan(callsBefore)
    })

    it('does not expand when queuing fails', async () => {
      await openDevice()
      mockQueueCommand.mockRejectedValueOnce(new Error('boom'))

      fireEvent.click(screen.getByRole('button', { name: 'Reboot' }))
      await confirmDialog()
      await screen.findByText(/Failed to queue command/)

      expect(panel().open).toBe(false)
    })

    it('remembers a manual open and close across mounts', async () => {
      await openDevice()
      toggle()
      expect(panel().open).toBe(true)
      expect(localStorage.getItem(OPEN_KEY)).toBe('true')

      cleanup()
      await openDevice()
      expect(panel().open).toBe(true)

      toggle()
      expect(localStorage.getItem(OPEN_KEY)).toBe('false')
    })

    it('falls back to collapsed for an invalid stored value or unavailable storage', async () => {
      localStorage.setItem(OPEN_KEY, 'maybe')
      await openDevice()
      expect(panel().open).toBe(false)

      cleanup()
      const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('blocked')
      })
      const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('blocked')
      })
      await openDevice()
      expect(panel().open).toBe(false)
      toggle()
      expect(panel().open).toBe(true)
      getItem.mockRestore()
      setItem.mockRestore()
    })

    it('deletes the finished button commands that are shown, and refreshes the status', async () => {
      mockListCommandStatus.mockResolvedValue(
        commandStatus([
          commandItem({ command_id: 3, name: 'reboot-now', state: 'received' }),
          commandItem({ command_id: 2, name: 'force-upload-now', state: 'success', complete: true, in_queue: false }),
          commandItem({ command_id: 9, name: 'idle_threshold_s', kind: 'config', state: 'success', complete: true, in_queue: false }),
        ]),
      )
      mockDismissCommandStatus.mockResolvedValue({ dismissed: [2] })
      await openDevice()
      toggle()

      await screen.findByText('command #2')
      mockListCommandStatus.mockResolvedValue(
        commandStatus([commandItem({ command_id: 3, name: 'reboot-now', state: 'received' })]),
      )
      fireEvent.click(screen.getByRole('button', { name: 'Delete shown' }))

      await waitFor(() => expect(mockDismissCommandStatus).toHaveBeenCalledWith('device-01', [2]))
      await waitFor(() => expect(screen.queryByText('command #2')).not.toBeInTheDocument())
      expect(screen.getByText('command #3')).toBeInTheDocument()
    })

    it('disables Delete shown while every shown command is still in progress', async () => {
      mockListCommandStatus.mockResolvedValue(commandStatus([commandItem()]))
      await openDevice()
      toggle()

      expect(await screen.findByRole('button', { name: 'Delete shown' })).toBeDisabled()
    })

    it('renders the shutdown progress from the heartbeat info', async () => {
      mockListCommandStatus.mockResolvedValue(
        commandStatus([commandItem({ name: 'shutdown-now', state: 'received' })]),
      )
      await openDevice()
      toggle()

      expect(await screen.findByText('Offline 1/3')).toBeInTheDocument()
    })
  })
})
