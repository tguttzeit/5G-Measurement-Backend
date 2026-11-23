import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RemoteConfigurationPage } from './RemoteConfigurationPage'
import { MemoryRouter } from 'react-router-dom'
import { ToastProvider } from '../components/ToastProvider'

// Command/queue feedback renders as a toast now, which needs a real ToastProvider above it.
function renderPage() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <RemoteConfigurationPage />
      </ToastProvider>
    </MemoryRouter>,
  )
}
import { ApiError, apiClient } from '../api/client'

vi.mock('../api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
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
const mockDelete = vi.mocked(apiClient.delete)
const mockPost = vi.mocked(apiClient.post)
const mockPut = vi.mocked(apiClient.put)

const fakeDevices = {
  devices: [{ device_id: 'device-01', online: true, last_heartbeat_at: null }],
}

const fakeQueue = {
  last_heartbeat_at: '2026-01-01T00:00:00Z',
  heartbeat_interval_s: 15,
  shutdown_confirm_mode: 'intervals' as const,
  shutdown_confirm_intervals: 4,
  shutdown_confirm_seconds: 60,
  shutdown_fail_heartbeats: 10,
  items: [
    {
      command_id: 1,
      kind: 'config',
      name: 'heartbeat_interval_s',
      detail: '= 15',
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
    },
  ],
}

const emptyQueue = { ...fakeQueue, items: [] }

const fakeCommandLog = {
  entries: [
    {
      id: 2,
      occurred_at: '2026-01-01T00:01:00Z',
      device_id: 'device-01',
      direction: 'from_device',
      kind: 'command',
      name: 'sim-reset-now',
      command_id: 7,
      status: 'failed',
      detail: 'modem not responding',
    },
    {
      id: 1,
      occurred_at: '2026-01-01T00:00:00Z',
      device_id: 'device-01',
      direction: 'to_device',
      kind: 'command',
      name: 'sim-reset-now',
      command_id: 7,
      status: 'queued',
      detail: null,
    },
  ],
}

function schemaField(overrides: Record<string, unknown>) {
  return {
    type: 'float',
    min: null,
    max: null,
    values: null,
    nullable: false,
    unit: null,
    requires_confirmation: false,
    no_effect_yet: false,
    ...overrides,
  }
}

// A subset of GET /config-schema that covers every control type and flag.
const fakeSchema = {
  groups: [
    {
      id: 'measurement_cycle',
      fields: [
        schemaField({ key: 'collector_capture_gate', type: 'enum', values: ['distance', 'time'] }),
        schemaField({ key: 'collector_position_threshold', min: 0.1, max: 1000, unit: 'm' }),
        schemaField({ key: 'idle_threshold_s', min: 1, max: 86400, unit: 's' }),
        schemaField({ key: 'collector_gps_enabled', type: 'bool' }),
      ],
    },
    {
      id: 'movement_detection',
      fields: [
        schemaField({ key: 'movement_gate_confirmations_required', type: 'int', min: 1, max: 10 }),
        schemaField({ key: 'movement_gate_home_latitude', min: -90, max: 90, nullable: true }),
        schemaField({ key: 'movement_gate_home_longitude', min: -180, max: 180, nullable: true }),
      ],
    },
    {
      id: 'backend_operation',
      fields: [
        schemaField({ key: 'heartbeat_interval_s', min: 1, max: 86400, unit: 's' }),
        schemaField({ key: 'day_end_threshold_s', min: 0, max: 86400, unit: 's', no_effect_yet: true }),
      ],
    },
    {
      id: 'risky',
      fields: [
        schemaField({
          key: 'modem_mode',
          type: 'enum',
          values: ['serving_cell', 'sa_scan'],
          requires_confirmation: true,
        }),
        schemaField({ key: 'gnss_receiver_retries', type: 'int', min: 0, max: 20, requires_confirmation: true }),
        schemaField({ key: 'future_field', type: 'matrix' }),
      ],
    },
  ],
}

function mockGetResponses(
  queueResponse: unknown,
  currentConfig: unknown = null,
  schema: unknown = fakeSchema,
  favoriteKeys: string[] = [],
) {
  mockGet.mockImplementation((path: string) => {
    if (path === '/config-schema') return Promise.resolve(schema)
    if (path === '/favorite-config-fields') return Promise.resolve({ field_keys: favoriteKeys })
    if (path === '/devices') return Promise.resolve(fakeDevices)
    if (path.startsWith('/command-log')) return Promise.resolve(fakeCommandLog)
    if (path.includes('/command-status')) return Promise.resolve(queueResponse)
    if (path.includes('/heartbeat/')) return Promise.resolve({ current_config: currentConfig })
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
}

async function selectDevice() {
  fireEvent.click(await screen.findByRole('button', { name: /device-01/ }))
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe('RemoteConfigurationPage remove queued', () => {
  it('disables the Remove queued button when the queue is empty', async () => {
    mockGetResponses(emptyQueue)

    renderPage()
    await selectDevice()

    await waitFor(() => expect(screen.getByText('Nothing queued for this device yet.')).toBeInTheDocument())
    expect(screen.getByText('Remove queued')).toBeDisabled()
  })

  it('asks for confirmation before removing, and calls the bulk delete endpoint on confirm', async () => {
    mockGetResponses(fakeQueue)
    mockDelete.mockResolvedValue(undefined)

    renderPage()
    await selectDevice()

    await waitFor(() => expect(screen.getByText('Remove queued')).not.toBeDisabled())
    fireEvent.click(screen.getByText('Remove queued'))

    expect(await screen.findByText('Remove queued items for device-01?')).toBeInTheDocument()
    expect(mockDelete).not.toHaveBeenCalled()

    fireEvent.click(screen.getAllByText('Remove queued')[1])

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('/devices/device-01/queue'))
  })

  it('cancelling the confirmation does not call the delete endpoint', async () => {
    mockGetResponses(fakeQueue)

    renderPage()
    await selectDevice()

    await waitFor(() => expect(screen.getByText('Remove queued')).not.toBeDisabled())
    fireEvent.click(screen.getByText('Remove queued'))
    await screen.findByText('Remove queued items for device-01?')

    fireEvent.click(screen.getByText('Cancel'))

    await waitFor(() =>
      expect(screen.queryByText('Remove queued items for device-01?')).not.toBeInTheDocument(),
    )
    expect(mockDelete).not.toHaveBeenCalled()
  })
})

const doneSelftest = {
  ...fakeQueue.items[0],
  command_id: 3,
  kind: 'command',
  name: 'run-selftest-now',
  detail: null,
  state: 'success',
  complete: true,
  in_queue: false,
  delivered_at: '2026-01-01T00:00:10Z',
  received_at: null,
  result_at: '2026-01-01T00:00:25Z',
}

// Applied, but still sent with every heartbeat until it is replaced or promoted.
const appliedOverride = {
  ...fakeQueue.items[0],
  state: 'success',
  complete: true,
  in_queue: true,
  delivered_at: '2026-01-01T00:00:10Z',
  result_at: '2026-01-01T00:00:40Z',
}

const pendingReboot = {
  ...fakeQueue.items[0],
  command_id: 4,
  kind: 'command',
  name: 'reboot-now',
  detail: null,
  state: 'delivered',
  delivered_at: '2026-01-01T00:00:50Z',
}

const mixedQueue = { ...fakeQueue, items: [pendingReboot, appliedOverride, doneSelftest] }

describe('RemoteConfigurationPage delete shown', () => {
  it('deletes only the finished commands that left the queue, not applied overrides or open commands', async () => {
    mockGetResponses(mixedQueue)
    mockPost.mockResolvedValue({ dismissed: [3] })

    renderPage()
    await selectDevice()

    await screen.findByText('command #3')
    mockGetResponses({ ...mixedQueue, items: [pendingReboot, appliedOverride] })
    fireEvent.click(screen.getByText('Delete shown'))

    await waitFor(() => expect(screen.queryByText('command #3')).not.toBeInTheDocument())
    expect(mockPost).toHaveBeenCalledWith('/devices/device-01/command-status/dismiss', {
      command_ids: [3],
    })
    expect(screen.getByText('config #1')).toBeInTheDocument()
    expect(screen.getByText('command #4')).toBeInTheDocument()
    expect(screen.getByText('Delete shown')).toBeDisabled()
  })

  it('replaces the browser-local Hide completed filter', async () => {
    mockGetResponses(mixedQueue)

    renderPage()
    await selectDevice()

    await screen.findByText('command #3')
    expect(screen.queryByText('Hide completed')).not.toBeInTheDocument()
    expect(screen.queryByText('Show')).not.toBeInTheDocument()
  })

  it('is disabled when nothing has finished', async () => {
    mockGetResponses(fakeQueue)

    renderPage()
    await selectDevice()

    await screen.findByText('config #1')
    expect(screen.getByText('Delete shown')).toBeDisabled()
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('keeps the items and shows the reason when deleting fails', async () => {
    mockGetResponses(mixedQueue)
    mockPost.mockRejectedValue(new ApiError('Forbidden', 403, { detail: 'Not allowed' }))

    renderPage()
    await selectDevice()
    await screen.findByText('command #3')
    fireEvent.click(screen.getByText('Delete shown'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed')
    expect(screen.getByText('command #3')).toBeInTheDocument()
  })
})

describe('RemoteConfigurationPage one-shot command buttons', () => {
  it.each([
    ['stop-measuring-now', 'Stop measuring'],
    ['reboot-now', 'Reboot'],
    ['promote-overrides-now', 'Promote overrides'],
  ])(
    'offers %s',
    async (command, label) => {
      mockGetResponses(emptyQueue)

      renderPage()
      await selectDevice()

      expect(screen.getByRole('button', { name: label })).toHaveAttribute('title', command)
    },
  )

  it('adds a clicked command to the preview, and removes it again', async () => {
    mockGetResponses(emptyQueue)

    renderPage()
    await selectDevice()
    fireEvent.click(screen.getByRole('button', { name: 'Reboot' }))

    expect(screen.getByText('Command: Reboot')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Remove'))
    expect(screen.queryByText('Command: Reboot')).not.toBeInTheDocument()
  })
})

describe('RemoteConfigurationPage sent toast', () => {
  async function sendCommand(command: string) {
    mockGetResponses(emptyQueue)
    mockPost.mockResolvedValue({ status: 'queued', command_id: 1 })

    renderPage()
    await selectDevice()
    fireEvent.click(screen.getByTitle(command))
    fireEvent.click(screen.getByRole('button', { name: 'Send & Confirm' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }))
    await screen.findByText('Changes sent to device-01.')
  }

  it('links to the self-test results when run-selftest-now was sent', async () => {
    await sendCommand('run-selftest-now')

    expect(screen.getByRole('link', { name: 'View self-test results' })).toHaveAttribute(
      'href',
      '/testing/visualization',
    )
  })

  it('has no link when another command was sent', async () => {
    await sendCommand('reboot-now')

    expect(screen.queryByRole('link', { name: 'View self-test results' })).not.toBeInTheDocument()
  })
})

describe('RemoteConfigurationPage command communication log', () => {
  it('shows the persisted history for the selected device', async () => {
    mockGetResponses(emptyQueue)

    renderPage()
    await selectDevice()

    await screen.findByText('Command Communication (2)')
    expect(screen.getByText('modem not responding')).toBeInTheDocument()
    expect(screen.getByText('from device')).toBeInTheDocument()
    expect(screen.getByText('to device')).toBeInTheDocument()
    expect(mockGet).toHaveBeenCalledWith('/command-log?device_id=device-01')
  })

  it('drops the device filter when "All devices" is ticked', async () => {
    mockGetResponses(emptyQueue)

    renderPage()
    await selectDevice()
    await screen.findByText('Command Communication (2)')

    fireEvent.click(screen.getByLabelText('All devices'))

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/command-log'))
  })
})

async function openOverrides(group?: string) {
  fireEvent.click(await screen.findByText('Config Overrides'))
  if (group) fireEvent.click(await screen.findByText(group))
}

async function renderOverrides(group?: string, currentConfig: unknown = null, favoriteKeys: string[] = []) {
  mockGetResponses(emptyQueue, currentConfig, fakeSchema, favoriteKeys)
  renderPage()
  await selectDevice()
  await openOverrides(group)
}

const sendButton = () => screen.getByRole('button', { name: 'Send & Confirm' })

describe('RemoteConfigurationPage config overrides', () => {
  it('keeps groups collapsed until opened, and force-opens one with a pending change', async () => {
    mockGetResponses(emptyQueue)

    renderPage()
    await selectDevice()

    const section = (await screen.findByText('Config Overrides')).closest('details')!
    expect(section).not.toHaveAttribute('open')
    fireEvent.click(screen.getByText('Config Overrides'))
    expect(section).toHaveAttribute('open')

    const group = await screen.findByText('Measurement cycle')
    expect(group.closest('details')).not.toHaveAttribute('open')

    fireEvent.click(group)
    expect(group.closest('details')).toHaveAttribute('open')

    fireEvent.change(screen.getByLabelText('Measurement cycle Idle threshold'), {
      target: { value: '60' },
    })
    expect(screen.getByText('1 change pending')).toBeInTheDocument()

    // Neither the group nor the section holding a change can be collapsed away.
    fireEvent.click(screen.getByText('Measurement cycle'))
    expect(group.closest('details')).toHaveAttribute('open')
    fireEvent.click(screen.getByText('Config Overrides'))
    expect(section).toHaveAttribute('open')
  })

  it('takes the groups and fields from the delivered specification, in the delivered order', async () => {
    await renderOverrides()

    const titles = Array.from(document.querySelectorAll('.remote-config__group-summary')).map(
      (el) => el.textContent,
    )
    expect(titles).toEqual([
      'Measurement cycle',
      'Movement detection before start',
      'Backend and operation',
      'Advanced - hardware',
    ])
    expect(screen.getByText('Overrides take effect', { exact: false })).toBeInTheDocument()
  })

  it('no longer offers the removed signal-threshold overrides', async () => {
    await renderOverrides()

    for (const name of ['rsrp_threshold', 'rsrq_threshold', 'sinr_threshold']) {
      expect(screen.queryByText(name)).not.toBeInTheDocument()
    }
    expect(document.body.textContent).not.toMatch(/rsrp|rsrq|sinr/i)
  })

  it('resets a single changed field', async () => {
    await renderOverrides('Measurement cycle')

    const input = screen.getByLabelText('Measurement cycle Idle threshold')
    fireEvent.change(input, { target: { value: '60' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Idle threshold' }))

    expect(input).toHaveValue(null)
    expect(screen.queryByText(/change(s)? pending/)).not.toBeInTheDocument()
  })

  it('shows the current value with its unit and renders null and booleans as text', async () => {
    await renderOverrides('Movement detection before start', {
      idle_threshold_s: 90,
      movement_gate_home_latitude: null,
      collector_gps_enabled: true,
    })

    const row = (label: string) => screen.getByLabelText(`Movement detection before start ${label}`).closest('tr')!
    expect(row('Home latitude')).toHaveTextContent('not set')
    expect(row('Home longitude')).toHaveTextContent('—')
  })

  describe('controls per type', () => {
    it('offers a number input with the delivered range, unit and an inline range violation', async () => {
      await renderOverrides('Measurement cycle')

      const input = screen.getByLabelText('Measurement cycle Idle threshold')
      expect(input).toHaveAttribute('type', 'number')
      expect(input).toHaveAttribute('min', '1')
      expect(input).toHaveAttribute('max', '86400')
      expect(within(input.closest('tr')!).getByText('Range: 1 to 86400')).toBeInTheDocument()

      fireEvent.change(input, { target: { value: '0' } })
      expect(screen.getByText('Must be at least 1.')).toBeInTheDocument()
      expect(input).toBeInvalid()
      expect(sendButton()).toBeDisabled()
      expect(screen.getByText('Fix the highlighted settings before sending.')).toBeInTheDocument()

      fireEvent.change(input, { target: { value: '90000' } })
      expect(screen.getByText('Must be at most 86400.')).toBeInTheDocument()

      fireEvent.change(input, { target: { value: '60' } })
      expect(screen.queryByText(/Must be at (least|most)/)).not.toBeInTheDocument()
      expect(sendButton()).not.toBeDisabled()
    })

    it('accepts decimals for a float and only whole numbers for an int', async () => {
      await renderOverrides('Measurement cycle')
      fireEvent.click(screen.getByText('Movement detection before start'))

      fireEvent.change(screen.getByLabelText('Measurement cycle Idle threshold'), { target: { value: '2.5' } })
      expect(screen.queryByText('Enter a whole number.')).not.toBeInTheDocument()

      const confirmations = screen.getByLabelText('Movement detection before start Confirmations required')
      expect(confirmations).toHaveAttribute('step', '1')
      fireEvent.change(confirmations, { target: { value: '2.5' } })
      expect(screen.getByText('Enter a whole number.')).toBeInTheDocument()
      expect(sendButton()).toBeDisabled()
    })

    it('offers exactly the listed values of an enum plus "unchanged", without free text', async () => {
      await renderOverrides('Measurement cycle')

      const select = screen.getByLabelText('Measurement cycle Capture gate')
      expect(select.tagName).toBe('SELECT')
      const options = Array.from(select.querySelectorAll('option')).map((o) => o.textContent)
      expect(options).toEqual(['unchanged', 'distance', 'time'])
      expect(select).toHaveValue('')
    })

    it('offers true / false / unchanged for a bool', async () => {
      await renderOverrides('Measurement cycle')

      const select = screen.getByLabelText('Measurement cycle GPS enabled')
      const options = Array.from(select.querySelectorAll('option')).map((o) => o.textContent)
      expect(options).toEqual(['unchanged', 'true', 'false'])
    })

    it('shows a type it does not know read-only and never sends it', async () => {
      await renderOverrides('Advanced - hardware')

      expect(screen.queryByLabelText('Advanced - hardware future_field')).not.toBeInTheDocument()
      expect(
        screen.getByText('This setting type is not supported by this version of the page.'),
      ).toBeInTheDocument()
      expect(screen.getByText('future_field')).toBeInTheDocument()
    })

    it('keeps "not set" for a nullable field visibly distinct from leaving it unchanged', async () => {
      await renderOverrides('Movement detection before start')

      const latitude = screen.getByLabelText('Movement detection before start Home latitude')
      const checkboxes = screen.getAllByRole('checkbox', { name: 'Not set (reset value)' })
      expect(checkboxes).toHaveLength(2)
      expect(checkboxes[0]).not.toBeChecked()
      expect(screen.queryByText('Will be reset to "not set"')).not.toBeInTheDocument()
      expect(screen.queryByText(/change(s)? pending/)).not.toBeInTheDocument()

      fireEvent.click(checkboxes[0])
      expect(latitude).toBeDisabled()
      expect(screen.getByText('Will be reset to "not set"')).toBeInTheDocument()
      expect(screen.getByText('1 change pending')).toBeInTheDocument()

      fireEvent.click(checkboxes[0])
      expect(latitude).not.toBeDisabled()
      expect(screen.queryByText('1 change pending')).not.toBeInTheDocument()
    })
  })

  describe('descriptions', () => {
    it('shows the description of a field in an info popover', async () => {
      await renderOverrides('Measurement cycle')

      fireEvent.click(screen.getByRole('button', { name: 'About Idle threshold' }))

      expect(screen.getByRole('note')).toHaveTextContent(
        'Time in seconds without detected movement after which the session is ended.',
      )
    })

    it('shows a dependency as text, and that day_end_threshold_s has no effect yet', async () => {
      await renderOverrides('Measurement cycle')
      fireEvent.click(screen.getByText('Backend and operation'))

      expect(screen.getByText('Only affects capture gate `distance`.')).toBeInTheDocument()
      expect(screen.getByText('Currently has no effect on the device.')).toBeInTheDocument()
      expect(screen.getAllByText('Currently has no effect on the device.')).toHaveLength(1)
    })
  })

  describe('sending', () => {
    async function change(group: string, label: string, value: string) {
      fireEvent.change(screen.getByLabelText(`${group} ${label}`), { target: { value } })
    }

    it('sends each value with its own type, including an explicit null', async () => {
      mockPost.mockResolvedValue({ status: 'ok', config_overrides: {} })
      await renderOverrides('Measurement cycle')
      fireEvent.click(screen.getByText('Movement detection before start'))

      await change('Measurement cycle', 'Idle threshold', '60')
      await change('Measurement cycle', 'Capture gate', 'time')
      await change('Measurement cycle', 'GPS enabled', 'false')
      await change('Movement detection before start', 'Confirmations required', '3')
      fireEvent.click(screen.getAllByRole('checkbox', { name: 'Not set (reset value)' })[0])

      expect(screen.getByText('Config: Home latitude = not set')).toBeInTheDocument()
      expect(screen.getByText('Config: GPS enabled = false')).toBeInTheDocument()

      fireEvent.click(sendButton())
      fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

      await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
      expect(mockPost).toHaveBeenCalledWith('/devices/device-01/config-overrides', {
        collector_capture_gate: 'time',
        idle_threshold_s: 60,
        collector_gps_enabled: false,
        movement_gate_confirmations_required: 3,
        movement_gate_home_latitude: null,
      })
    })

    it('does not send a field that was left unchanged', async () => {
      mockPost.mockResolvedValue({ status: 'ok', config_overrides: {} })
      await renderOverrides('Measurement cycle')

      await change('Measurement cycle', 'Idle threshold', '60')
      fireEvent.click(sendButton())
      fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

      await waitFor(() => expect(mockPost).toHaveBeenCalled())
      expect(mockPost).toHaveBeenCalledWith('/devices/device-01/config-overrides', { idle_threshold_s: 60 })
    })

    it('shows the field and constraint of a server-side validation error', async () => {
      mockPost.mockRejectedValue(
        new ApiError('Unprocessable', 422, {
          detail: [{ loc: ['body', 'idle_threshold_s'], msg: 'Input should be greater than or equal to 1' }],
        }),
      )
      await renderOverrides('Measurement cycle')

      await change('Measurement cycle', 'Idle threshold', '60')
      fireEvent.click(sendButton())
      fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

      expect(
        await screen.findByText('Idle threshold: Input should be greater than or equal to 1'),
      ).toBeInTheDocument()
    })
  })

  describe('risky fields', () => {
    async function changeRisky() {
      await renderOverrides('Advanced - hardware')
      fireEvent.change(screen.getByLabelText('Advanced - hardware GNSS receiver retries'), {
        target: { value: '17' },
      })
      fireEvent.change(screen.getByLabelText('Advanced - hardware Modem mode'), {
        target: { value: 'sa_scan' },
      })
    }

    it('asks "Do you know what you are doing?" and lists the risky changes before the regular confirmation', async () => {
      await changeRisky()
      fireEvent.click(sendButton())

      const dialog = await screen.findByRole('dialog', { name: 'Do you know what you are doing?' })
      expect(dialog).toHaveTextContent('can only be repaired on site')
      expect(dialog).toHaveTextContent('Config: GNSS receiver retries = 17')
      expect(dialog).toHaveTextContent('Config: Modem mode = sa_scan')
      expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
      expect(screen.queryByRole('dialog', { name: /Confirm changes/ })).not.toBeInTheDocument()
      expect(mockPost).not.toHaveBeenCalled()
    })

    it('goes on to the regular confirmation only after the extra one, then sends', async () => {
      mockPost.mockResolvedValue({ status: 'ok', config_overrides: {} })
      await changeRisky()
      fireEvent.click(sendButton())

      fireEvent.click(await screen.findByRole('button', { name: 'Yes, continue' }))
      expect(screen.queryByRole('dialog', { name: 'Do you know what you are doing?' })).not.toBeInTheDocument()
      fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

      await waitFor(() =>
        expect(mockPost).toHaveBeenCalledWith('/devices/device-01/config-overrides', {
          gnss_receiver_retries: 17,
          modem_mode: 'sa_scan',
        }),
      )
    })

    it('returns to the form on cancel without sending', async () => {
      await changeRisky()
      fireEvent.click(sendButton())

      fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(screen.getByLabelText('Advanced - hardware GNSS receiver retries')).toHaveValue(17)
      expect(mockPost).not.toHaveBeenCalled()
    })

    it('is not shown when only normal fields changed', async () => {
      await renderOverrides('Measurement cycle')
      fireEvent.change(screen.getByLabelText('Measurement cycle Idle threshold'), { target: { value: '60' } })
      fireEvent.click(sendButton())

      expect(await screen.findByRole('dialog', { name: /Confirm changes/ })).toBeInTheDocument()
      expect(screen.queryByText('Do you know what you are doing?')).not.toBeInTheDocument()
    })

    it('is not shown for a one-shot command alone', async () => {
      await renderOverrides()
      fireEvent.click(screen.getByRole('button', { name: 'Reboot' }))
      fireEvent.click(sendButton())

      expect(await screen.findByRole('dialog', { name: /Confirm changes/ })).toBeInTheDocument()
      expect(screen.queryByText('Do you know what you are doing?')).not.toBeInTheDocument()
    })
  })

  describe('soft warnings', () => {
    it('warns, without blocking, when only one home coordinate is changed', async () => {
      await renderOverrides('Movement detection before start')
      expect(screen.queryByText(/latitude and longitude should be set together/)).not.toBeInTheDocument()

      fireEvent.change(screen.getByLabelText('Movement detection before start Home latitude'), {
        target: { value: '48.1' },
      })

      expect(screen.getByText(/latitude and longitude should be set together/)).toBeInTheDocument()
      expect(sendButton()).not.toBeDisabled()

      fireEvent.change(screen.getByLabelText('Movement detection before start Home longitude'), {
        target: { value: '11.5' },
      })
      expect(screen.queryByText(/latitude and longitude should be set together/)).not.toBeInTheDocument()
    })
  })

  it('shows why the settings are missing when the specification cannot be loaded', async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === '/config-schema') return Promise.reject(new ApiError('Forbidden', 403, { detail: 'Not allowed' }))
      if (path === '/devices') return Promise.resolve(fakeDevices)
      if (path.startsWith('/command-log')) return Promise.resolve(fakeCommandLog)
      if (path.includes('/command-status')) return Promise.resolve(emptyQueue)
      return Promise.resolve({ current_config: null })
    })
    renderPage()
    await selectDevice()
    await openOverrides()

    expect(await screen.findByText('Not allowed')).toBeInTheDocument()
    expect(document.querySelector('.remote-config__group')).toBeNull()
  })
})

describe('RemoteConfigurationPage favorite fields', () => {
  const favoritesSummary = () => screen.queryByText('Favorites')
  const star = (label: string) => screen.getByRole('button', { name: `Favorite: ${label}` })

  it('shows no Favorites section while nothing is favorited', async () => {
    await renderOverrides()

    expect(favoritesSummary()).not.toBeInTheDocument()
  })

  it('lists a favorite in a Favorites section above the groups and only there', async () => {
    await renderOverrides(undefined, null, ['idle_threshold_s'])

    const titles = Array.from(document.querySelectorAll('.remote-config__group-summary')).map(
      (el) => el.textContent,
    )
    expect(titles.slice(0, 2)).toEqual(['Favorites', 'Measurement cycle'])
    const favorites = screen.getByText('Favorites').closest('details')!
    expect(favorites).toHaveAttribute('open')
    expect(within(favorites).getByLabelText('Measurement cycle Idle threshold')).toBeInTheDocument()
    expect(screen.getAllByLabelText('Measurement cycle Idle threshold')).toHaveLength(1)
  })

  it('hides a group whose fields are all favorites', async () => {
    await renderOverrides(undefined, null, ['heartbeat_interval_s', 'day_end_threshold_s'])

    expect(screen.queryByText('Backend and operation')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Backend and operation Heartbeat interval')).toBeInTheDocument()
  })

  it('ignores a favorite the specification does not know', async () => {
    await renderOverrides(undefined, null, ['field_removed_later'])

    expect(favoritesSummary()).not.toBeInTheDocument()
    expect(document.querySelectorAll('.remote-config__group-summary')).toHaveLength(4)
  })

  it('saves the full list when a star is toggled on, and moves the field into Favorites', async () => {
    mockPut.mockResolvedValue({ field_keys: [] })
    await renderOverrides('Measurement cycle', null, ['collector_capture_gate'])

    fireEvent.click(star('Idle threshold'))

    expect(mockPut).toHaveBeenCalledWith('/favorite-config-fields', {
      field_keys: ['collector_capture_gate', 'idle_threshold_s'],
    })
    const favorites = screen.getByText('Favorites').closest('details')!
    expect(within(favorites).getByLabelText('Measurement cycle Idle threshold')).toBeInTheDocument()
    expect(screen.getAllByLabelText('Measurement cycle Idle threshold')).toHaveLength(1)
  })

  it('moves a field back to its group when its star is toggled off', async () => {
    mockPut.mockResolvedValue({ field_keys: [] })
    await renderOverrides(undefined, null, ['idle_threshold_s'])

    fireEvent.click(star('Idle threshold'))

    expect(mockPut).toHaveBeenCalledWith('/favorite-config-fields', { field_keys: [] })
    expect(favoritesSummary()).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Measurement cycle'))
    expect(screen.getByLabelText('Measurement cycle Idle threshold')).toBeInTheDocument()
  })

  it('marks the state of each star', async () => {
    await renderOverrides('Measurement cycle', null, ['idle_threshold_s'])

    expect(star('Idle threshold')).toHaveAttribute('aria-pressed', 'true')
    expect(star('Position threshold')).toHaveAttribute('aria-pressed', 'false')
  })

  it('keeps the Favorites section open and counts its pending change', async () => {
    await renderOverrides(undefined, null, ['idle_threshold_s'])
    const favorites = screen.getByText('Favorites').closest('details')!

    fireEvent.change(screen.getByLabelText('Measurement cycle Idle threshold'), { target: { value: '60' } })

    expect(screen.getByText('1 change pending')).toBeInTheDocument()
    expect(within(favorites.querySelector('summary')!).getByText('1')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Favorites'))
    expect(favorites).toHaveAttribute('open')
    expect(sendButton()).not.toBeDisabled()
  })

  it('keeps a pending value when its field is favorited', async () => {
    mockPut.mockResolvedValue({ field_keys: [] })
    await renderOverrides('Measurement cycle')
    fireEvent.change(screen.getByLabelText('Measurement cycle Idle threshold'), { target: { value: '60' } })

    fireEvent.click(star('Idle threshold'))

    expect(screen.getByLabelText('Measurement cycle Idle threshold')).toHaveValue(60)
    expect(screen.getByText('1 change pending')).toBeInTheDocument()
  })

  it('reloads the stored favorites and says so when saving fails', async () => {
    mockPut.mockRejectedValue(new ApiError('Boom', 500))
    await renderOverrides('Measurement cycle')

    fireEvent.click(star('Idle threshold'))

    expect(await screen.findByText('Favorites could not be saved')).toBeInTheDocument()
    await waitFor(() => expect(favoritesSummary()).not.toBeInTheDocument())
  })

  it('offers no stars when the favorites could not be loaded, so nothing can overwrite them', async () => {
    mockGetResponses(emptyQueue)
    const base = mockGet.getMockImplementation()!
    mockGet.mockImplementation((path: string) =>
      path === '/favorite-config-fields' ? Promise.reject(new Error('down')) : base(path),
    )
    renderPage()
    await selectDevice()
    await openOverrides('Measurement cycle')

    expect(screen.getByLabelText('Measurement cycle Idle threshold')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Favorite:/ })).not.toBeInTheDocument()
  })
})

describe('RemoteConfigurationPage queued override values', () => {
  const configItem = (name: string, detail: string) => ({
    ...fakeQueue.items[0],
    name,
    detail,
  })

  it('renders null, booleans and enum strings of queued overrides as readable text', async () => {
    mockGetResponses({
      ...fakeQueue,
      items: [
        { ...configItem('movement_gate_home_latitude', '= None'), command_id: 1 },
        { ...configItem('collector_gps_enabled', '= False'), command_id: 2 },
        { ...configItem('modem_mode', '= sa_scan'), command_id: 3 },
        { ...configItem('not_a_known_field', '= 4'), command_id: 4 },
      ],
    })

    renderPage()
    await selectDevice()

    expect(await screen.findByText('Home latitude = not set')).toBeInTheDocument()
    expect(screen.getByText('GPS enabled = false')).toBeInTheDocument()
    expect(screen.getByText('Modem mode = sa_scan')).toBeInTheDocument()
    expect(screen.getByText('not_a_known_field = 4')).toBeInTheDocument()
  })
})

describe('RemoteConfigurationPage command status', () => {
  it('shows each queued item with its lifecycle', async () => {
    mockGetResponses(fakeQueue)

    renderPage()
    await selectDevice()

    expect(await screen.findByText('Heartbeat interval = 15')).toBeInTheDocument()
    expect(screen.getByText('Waiting for delivery')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Progress of Heartbeat interval' })).toBeInTheDocument()
  })
})
