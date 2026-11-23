import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RunsPage } from './RunsPage'
import i18n from '../i18n'
import { apiClient } from '../api/client'
import { useAuth } from '../components/AuthProvider'

vi.mock('../api/client', () => ({
  apiClient: { get: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}))
vi.mock('../components/AuthProvider', () => ({ useAuth: vi.fn() }))

const mockGet = vi.mocked(apiClient.get)
const mockPatch = vi.mocked(apiClient.patch)
const mockDelete = vi.mocked(apiClient.delete)
const mockUseAuth = vi.mocked(useAuth)

function loginAs(isSuperuser: boolean) {
  mockUseAuth.mockReturnValue({ user: { is_superuser: isSuperuser } } as ReturnType<typeof useAuth>)
}

function run(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    name: null,
    run_id: 'run-abc',
    device_id: 'device-1',
    mission_type: 'ground',
    start: '2026-08-01T10:00:00Z',
    end: '2026-08-01T11:05:30Z',
    point_count: 120,
    mean_rsrp: -90.04,
    mean_rsrq: -10,
    mean_sinr: null,
    campaign_id: 3,
    campaign_name: 'August',
    legacy: false,
    ...overrides,
  }
}

function runsResponse(runs: unknown[], total = runs.length, page = 1) {
  return { runs, total, page, page_size: 25 }
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname + location.search}</div>
}

function renderRunsPage(initialEntry = '/runs') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/map" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

function runsRequests(): URLSearchParams[] {
  return mockGet.mock.calls
    .map(([path]) => path as string)
    .filter((path) => path.startsWith('/runs?'))
    .map((path) => new URLSearchParams(path.slice('/runs?'.length)))
}

function lastRunsRequest(): URLSearchParams {
  const requests = runsRequests()
  return requests[requests.length - 1]
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          campaigns: [
            { id: 3, name: 'August', start: '2026-08-01', end: '2026-08-31' },
          ],
        }),
    }),
  )
  mockGet.mockResolvedValue(runsResponse([run()]))
  mockPatch.mockResolvedValue({})
  mockDelete.mockResolvedValue(undefined)
  loginAs(false)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('RunsPage', () => {
  it('lists runs with duration, point count and mean metrics', async () => {
    renderRunsPage()

    const row = (await screen.findByText('run-abc')).closest('tr') as HTMLElement
    expect(within(row).getByText('device-1')).toBeInTheDocument()
    expect(within(row).getByText('1h 5m')).toBeInTheDocument()
    expect(within(row).getByText('120')).toBeInTheDocument()
    expect(within(row).getByText('-90.0')).toBeInTheDocument()
    expect(within(row).getByText('August')).toBeInTheDocument()
    expect(within(row).queryByText('legacy')).not.toBeInTheDocument()
    // missing metric means show a dash, not NaN or 0
    expect(within(row).getAllByText('–').length).toBeGreaterThan(0)
  })

  it('shows run start and end in the selected language with the ISO value in the tooltip', async () => {
    renderRunsPage()

    const row = (await screen.findByText('run-abc')).closest('tr') as HTMLElement
    const times = row.querySelectorAll('time')
    expect(times).toHaveLength(2)
    expect(times[0]).toHaveAttribute('datetime', '2026-08-01T10:00:00.000Z')
    expect(times[1]).toHaveAttribute('datetime', '2026-08-01T11:05:30.000Z')
    expect(times[0].textContent).toMatch(/^\d{2}\/\d{2}\/2026, \d{2}:\d{2}:\d{2}$/)

    await act(() => i18n.changeLanguage('de'))
    expect(row.querySelectorAll('time')[0].textContent).toMatch(/^\d{2}\.\d{2}\.2026, \d{2}:\d{2}:\d{2}$/)
  })

  it('marks legacy runs', async () => {
    mockGet.mockResolvedValue(
      runsResponse([run({ run_id: 'legacy-device-1-ground-2026-08-01', legacy: true })]),
    )

    renderRunsPage()

    expect(await screen.findByText('legacy')).toBeInTheDocument()
  })

  it('shows an empty state when there are no runs', async () => {
    mockGet.mockResolvedValue(runsResponse([]))

    renderRunsPage()

    expect(await screen.findByText('No runs found.')).toBeInTheDocument()
  })

  it('shows an error banner when loading fails', async () => {
    mockGet.mockRejectedValue(new Error('boom'))

    renderRunsPage()

    expect(await screen.findByText('Failed to load runs.')).toBeInTheDocument()
  })

  it('requests the first page, newest first, by default', async () => {
    renderRunsPage()

    await screen.findByText('run-abc')
    const request = lastRunsRequest()
    expect(request.get('sort')).toBe('start')
    expect(request.get('order')).toBe('desc')
    expect(request.get('page')).toBe('1')
    expect(request.get('page_size')).toBe('25')
  })

  it('sends filters to the API and resets to the first page', async () => {
    mockGet.mockResolvedValue(runsResponse([run()], 60))
    renderRunsPage()
    await screen.findByText('run-abc')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(lastRunsRequest().get('page')).toBe('2'))

    fireEvent.change(screen.getByLabelText('Mission Type'), { target: { value: 'drone' } })
    fireEvent.change(screen.getByLabelText('Started from'), { target: { value: '2026-08-01' } })
    fireEvent.change(screen.getByLabelText('Started until'), { target: { value: '2026-08-31' } })

    await waitFor(() => {
      const request = lastRunsRequest()
      expect(request.get('mission_type')).toBe('drone')
      expect(request.get('from')).toBe('2026-08-01')
      expect(request.get('to')).toBe('2026-08-31')
      expect(request.get('page')).toBe('1')
    })
  })

  it('filters by campaign', async () => {
    renderRunsPage()
    await screen.findByText('run-abc')
    await screen.findByRole('option', { name: 'August' })

    fireEvent.change(screen.getByLabelText('Campaign'), { target: { value: '3' } })

    await waitFor(() => expect(lastRunsRequest().get('campaign_id')).toBe('3'))
  })

  it('filters by runs that are assigned to no campaign', async () => {
    renderRunsPage()
    await screen.findByText('run-abc')
    await screen.findByRole('option', { name: 'August' })

    fireEvent.change(screen.getByLabelText('Campaign'), { target: { value: 'unassigned' } })

    await waitFor(() => expect(lastRunsRequest().get('unassigned')).toBe('true'))
    expect(lastRunsRequest().has('campaign_id')).toBe(false)
  })

  it('does not send the unassigned filter for a campaign or for all runs', async () => {
    renderRunsPage()
    await screen.findByText('run-abc')

    expect(lastRunsRequest().has('unassigned')).toBe(false)
    fireEvent.change(screen.getByLabelText('Campaign'), { target: { value: '3' } })
    await waitFor(() => expect(lastRunsRequest().get('campaign_id')).toBe('3'))
    expect(lastRunsRequest().has('unassigned')).toBe(false)
  })

  it('debounces the device filter instead of fetching per keystroke', async () => {
    renderRunsPage()
    await screen.findByText('run-abc')
    const callsBefore = runsRequests().length

    fireEvent.change(screen.getByLabelText('Device ID'), { target: { value: 'dev' } })
    fireEvent.change(screen.getByLabelText('Device ID'), { target: { value: 'device-9' } })

    await waitFor(() => expect(lastRunsRequest().get('device_id')).toBe('device-9'))
    expect(runsRequests().length).toBe(callsBefore + 1)
  })

  it('sorts by a column and flips the direction on a second click', async () => {
    renderRunsPage()
    await screen.findByText('run-abc')

    fireEvent.click(screen.getByRole('button', { name: 'Points' }))
    await waitFor(() => {
      expect(lastRunsRequest().get('sort')).toBe('point_count')
      expect(lastRunsRequest().get('order')).toBe('desc')
    })

    fireEvent.click(screen.getByRole('button', { name: /Points/ }))
    await waitFor(() => expect(lastRunsRequest().get('order')).toBe('asc'))
    expect(screen.getByRole('columnheader', { name: /Points/ })).toHaveAttribute(
      'aria-sort',
      'ascending',
    )
  })

  it('pages through results', async () => {
    mockGet.mockResolvedValue(runsResponse([run()], 60))
    renderRunsPage()

    expect(await screen.findByText('Page 1 of 3 (60 runs)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(lastRunsRequest().get('page')).toBe('2'))
  })

  it('opens the map filtered to the run, its device and its campaign', async () => {
    renderRunsPage()
    await screen.findByText('run-abc')

    fireEvent.click(screen.getByRole('button', { name: 'Show on map' }))

    const location = (await screen.findByTestId('location')).textContent as string
    const url = new URL(location, 'http://localhost')
    expect(url.pathname).toBe('/map')
    expect(url.searchParams.get('run')).toBe('run-abc')
    expect(url.searchParams.get('device')).toBe('device-1')
    expect(url.searchParams.get('campaign')).toBe('3')
    expect(url.searchParams.get('mission')).toBe('ground')
  })

  it('highlights the run named in ?run_id=, from the "upload successful" toast link', async () => {
    mockGet.mockResolvedValue(runsResponse([run(), run({ run_id: 'run-other' })]))
    renderRunsPage('/runs?device_id=device-1&run_id=run-abc')

    const row = (await screen.findByText('run-abc')).closest('tr') as HTMLElement
    const otherRow = screen.getByText('run-other').closest('tr') as HTMLElement
    expect(row).toHaveClass('runs-table__row--new')
    expect(otherRow).not.toHaveClass('runs-table__row--new')
  })

  it('stops highlighting the run once the user hovers it', async () => {
    mockGet.mockResolvedValue(runsResponse([run()]))
    renderRunsPage('/runs?run_id=run-abc')

    const row = (await screen.findByText('run-abc')).closest('tr') as HTMLElement
    expect(row).toHaveClass('runs-table__row--new')

    fireEvent.mouseEnter(row)

    expect(row).not.toHaveClass('runs-table__row--new')
  })

  it('does not highlight anything without ?run_id=', async () => {
    renderRunsPage()

    const row = (await screen.findByText('run-abc')).closest('tr') as HTMLElement

    expect(row).not.toHaveClass('runs-table__row--new')
  })
})

describe('RunsPage editing (superuser)', () => {
  beforeEach(() => loginAs(true))

  it('shows no edit controls to a regular user', async () => {
    loginAs(false)
    renderRunsPage()
    await screen.findByText('run-abc')

    expect(screen.queryByRole('button', { name: /Edit run/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Delete run/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Trash' })).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('shows the name of a run with its device run id beneath', async () => {
    mockGet.mockResolvedValue(runsResponse([run({ name: 'Morning flight' })]))

    renderRunsPage()

    const row = (await screen.findByText('Morning flight')).closest('tr') as HTMLElement
    expect(within(row).getByText('run-abc')).toBeInTheDocument()
  })

  it('edits a run and sends only the changed fields', async () => {
    renderRunsPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit run run-abc' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit run' })

    // device and run id can be read but not changed
    expect(within(dialog).getByLabelText('Device ID')).toHaveAttribute('readonly')
    expect(within(dialog).getByLabelText('Run ID (set by the device)')).toHaveAttribute('readonly')
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()

    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: ' Lap 1 ' } })
    fireEvent.change(within(dialog).getByLabelText('Mission type'), { target: { value: 'drone' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(mockPatch).toHaveBeenCalledWith('/runs/7', { name: 'Lap 1', mission_type: 'drone' }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('unassigns the campaign of a run', async () => {
    renderRunsPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit run run-abc' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('Campaign')).toHaveValue('3')

    fireEvent.change(within(dialog).getByLabelText('Campaign'), { target: { value: 'none' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/runs/7', { campaign_id: null }))
  })

  it('clears the name of a run', async () => {
    mockGet.mockResolvedValue(runsResponse([run({ name: 'Old' })]))
    renderRunsPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit run Old' }))
    const dialog = await screen.findByRole('dialog')

    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: '' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/runs/7', { name: null }))
  })

  it('reloads the list after saving and keeps the dialog open with an error when saving fails', async () => {
    mockPatch.mockRejectedValueOnce(new Error('boom'))
    renderRunsPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit run run-abc' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'x' } })

    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    expect(await within(dialog).findByText('Failed to save the run.')).toBeInTheDocument()
    const requestsBefore = runsRequests().length

    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(runsRequests().length).toBe(requestsBefore + 1))
  })

  it('applies only the filled-in fields to all selected runs', async () => {
    mockGet.mockResolvedValue(
      runsResponse([run(), run({ id: 8, run_id: 'run-two' }), run({ id: 9, run_id: 'run-three' })]),
    )
    renderRunsPage()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select run run-abc of device-1' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select run run-three of device-1' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Edit selected' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit 2 runs' })
    expect(within(dialog).getByRole('button', { name: 'Apply to selected' })).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('Mission type'), { target: { value: 'drone' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply to selected' }))

    await waitFor(() =>
      expect(mockPatch).toHaveBeenCalledWith('/runs', {
        ids: [7, 9],
        changes: { mission_type: 'drone' },
      }),
    )
    await waitFor(() => expect(screen.queryByText('2 selected')).not.toBeInTheDocument())
  })

  it('can unassign all selected runs from their campaign', async () => {
    renderRunsPage()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select all runs on this page' }))
    fireEvent.click(screen.getByRole('button', { name: 'Edit selected' }))
    const dialog = await screen.findByRole('dialog')

    fireEvent.change(within(dialog).getByLabelText('Campaign'), { target: { value: 'none' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply to selected' }))

    await waitFor(() =>
      expect(mockPatch).toHaveBeenCalledWith('/runs', { ids: [7], changes: { campaign_id: null } }),
    )
  })

  it('drops the selection when the page changes', async () => {
    mockGet.mockResolvedValue(runsResponse([run()], 60))
    renderRunsPage()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select run run-abc of device-1' }))
    expect(screen.getByText('1 selected')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(screen.queryByText('1 selected')).not.toBeInTheDocument())
  })

  it('asks for confirmation naming the number of measurements before moving a run to the trash', async () => {
    renderRunsPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete run run-abc' }))
    const dialog = await screen.findByRole('dialog', { name: 'Move run to trash' })

    expect(dialog).toHaveTextContent('120 measurements')
    expect(dialog).toHaveTextContent('restore')
    expect(mockDelete).not.toHaveBeenCalled()

    fireEvent.click(within(dialog).getByRole('button', { name: 'Move to trash' }))

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('/runs/7'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('does not delete anything when the confirmation is cancelled', async () => {
    renderRunsPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete run run-abc' }))
    const dialog = await screen.findByRole('dialog')

    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mockDelete).not.toHaveBeenCalled()
  })

  it('steps back a page after deleting the only run of the last page', async () => {
    mockGet.mockResolvedValue(runsResponse([run()], 26))
    renderRunsPage()
    await screen.findByText('run-abc')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(lastRunsRequest().get('page')).toBe('2'))

    fireEvent.click(await screen.findByRole('button', { name: 'Delete run run-abc' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Move to trash' }))

    await waitFor(() => expect(lastRunsRequest().get('page')).toBe('1'))
  })

  it('links superusers to the trash', async () => {
    loginAs(true)
    renderRunsPage()

    expect(await screen.findByRole('link', { name: 'Trash' })).toHaveAttribute('href', '/runs/trash')
  })
})
