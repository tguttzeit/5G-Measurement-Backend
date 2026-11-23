import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminCampaignsPage } from './AdminCampaignsPage'
import {
  assignRuns,
  type Campaign,
  createCampaign,
  deleteCampaign,
  listAdminCampaigns,
  unassignRuns,
  updateCampaign,
} from '../api/campaigns'
import { ApiError } from '../api/client'
import { fetchRuns, type Run } from '../api/runs'

vi.mock('../api/campaigns', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/campaigns')>()),
  listAdminCampaigns: vi.fn(),
  createCampaign: vi.fn(),
  updateCampaign: vi.fn(),
  deleteCampaign: vi.fn(),
  assignRuns: vi.fn(),
  unassignRuns: vi.fn(),
}))
vi.mock('../api/runs', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/runs')>()),
  fetchRuns: vi.fn(),
}))

const mockedList = vi.mocked(listAdminCampaigns)
const mockedCreate = vi.mocked(createCampaign)
const mockedUpdate = vi.mocked(updateCampaign)
const mockedDelete = vi.mocked(deleteCampaign)
const mockedAssign = vi.mocked(assignRuns)
const mockedUnassign = vi.mocked(unassignRuns)
const mockedFetchRuns = vi.mocked(fetchRuns)

const SUMMER: Campaign = {
  id: 1,
  name: 'summer-2026',
  start: '2026-06-10',
  end: '2026-08-21',
}
const EMPTY: Campaign = { id: 2, name: 'empty-one', start: null, end: null }

function run(overrides: Partial<Run> = {}): Run {
  return {
    id: 1,
    name: null,
    run_id: 'run-a',
    device_id: 'device-1',
    mission_type: 'ground',
    start: '2026-06-10T08:00:00Z',
    end: '2026-06-10T09:00:00Z',
    point_count: 10,
    mean_rsrp: -90,
    mean_rsrq: -10,
    mean_sinr: 5,
    campaign_id: null,
    campaign_name: null,
    legacy: false,
    ...overrides,
  }
}

function runsResponse(runs: Run[]) {
  return { runs, total: runs.length, page: 1, page_size: 25 }
}

// Serves the runs panel: the campaign's own runs for `campaignId`, the rest for everything else.
function serveRuns({ members = [], unassigned = [], others = [] }: {
  members?: Run[]
  unassigned?: Run[]
  others?: Run[]
}) {
  mockedFetchRuns.mockImplementation(async (params) => {
    if (params.campaignId != null) return runsResponse(members)
    if (params.unassigned) return runsResponse(unassigned)
    return runsResponse([...members, ...unassigned, ...others])
  })
}

beforeEach(() => {
  mockedList.mockResolvedValue({ campaigns: [SUMMER, EMPTY] })
  serveRuns({})
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

async function openRunsPanel(name: string) {
  const row = (await screen.findByText(name)).closest('tr') as HTMLElement
  fireEvent.click(within(row).getByRole('button', { name: 'Manage runs' }))
  return screen.findByRole('region', { name: `Runs of ${name}` })
}

describe('AdminCampaignsPage campaign list', () => {
  it('shows the period derived from the runs, read-only, and says so for an empty campaign', async () => {
    render(<AdminCampaignsPage />)

    const summer = (await screen.findByText('summer-2026')).closest('tr') as HTMLElement
    expect(within(summer).getByText('10/06/2026 – 21/08/2026')).toBeInTheDocument()
    const empty = screen.getByText('empty-one').closest('tr') as HTMLElement
    expect(within(empty).getByText('No runs')).toBeInTheDocument()
  })

  it('creates a campaign from the name alone, without date inputs', async () => {
    mockedCreate.mockResolvedValue(EMPTY)
    render(<AdminCampaignsPage />)
    await screen.findByText('summer-2026')

    expect(screen.queryByLabelText(/start date/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/end date/i)).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'autumn-2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Campaign' }))

    await waitFor(() => expect(mockedCreate).toHaveBeenCalledWith({ name: 'autumn-2026' }))
  })

  it('renames a campaign with only the name, without date inputs', async () => {
    mockedUpdate.mockResolvedValue(SUMMER)
    render(<AdminCampaignsPage />)
    const row = (await screen.findByText('summer-2026')).closest('tr') as HTMLElement

    fireEvent.click(within(row).getByRole('button', { name: 'Edit' }))

    expect(row.querySelectorAll('input[type="date"]')).toHaveLength(0)
    fireEvent.change(within(row).getByDisplayValue('summer-2026'), {
      target: { value: 'summer-renamed' },
    })
    fireEvent.click(within(row).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith(1, { name: 'summer-renamed' }))
  })

  it('deletes a campaign after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockedDelete.mockResolvedValue(undefined)
    render(<AdminCampaignsPage />)
    const row = (await screen.findByText('summer-2026')).closest('tr') as HTMLElement

    fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith(1))
  })
})

describe('AdminCampaignsPage run assignment', () => {
  it('lists the campaign\'s runs and the unassigned runs that can be added', async () => {
    serveRuns({
      members: [run({ run_id: 'member-run', campaign_id: 1, campaign_name: 'summer-2026' })],
      unassigned: [run({ run_id: 'free-run' })],
    })
    render(<AdminCampaignsPage />)

    const panel = await openRunsPanel('summer-2026')

    expect(await within(panel).findByText('member-run')).toBeInTheDocument()
    expect(await within(panel).findByText('free-run')).toBeInTheDocument()
    expect(mockedFetchRuns).toHaveBeenCalledWith(
      expect.objectContaining({ campaignId: 1 }),
      expect.anything(),
    )
    expect(mockedFetchRuns).toHaveBeenCalledWith(
      expect.objectContaining({ unassigned: true }),
      expect.anything(),
    )
  })

  it('adds the selected runs to the campaign and refreshes the campaign list', async () => {
    serveRuns({ unassigned: [run({ run_id: 'free-1' }), run({ run_id: 'free-2' })] })
    mockedAssign.mockResolvedValue(SUMMER)
    render(<AdminCampaignsPage />)
    const panel = await openRunsPanel('summer-2026')
    await within(panel).findByText('free-1')
    const listCallsBefore = mockedList.mock.calls.length

    fireEvent.click(within(panel).getByLabelText('Select run free-2 of device-1'))
    fireEvent.click(within(panel).getByRole('button', { name: 'Add selected' }))

    await waitFor(() =>
      expect(mockedAssign).toHaveBeenCalledWith(1, [{ device_id: 'device-1', run_id: 'free-2' }]),
    )
    await waitFor(() => expect(mockedList.mock.calls.length).toBeGreaterThan(listCallsBefore))
  })

  it('disables adding while nothing is selected', async () => {
    serveRuns({ unassigned: [run({ run_id: 'free-1' })] })
    render(<AdminCampaignsPage />)
    const panel = await openRunsPanel('summer-2026')
    await within(panel).findByText('free-1')

    expect(within(panel).getByRole('button', { name: 'Add selected' })).toBeDisabled()
  })

  it('removes the selected runs from the campaign', async () => {
    serveRuns({
      members: [
        run({ run_id: 'member-1', campaign_id: 1, campaign_name: 'summer-2026' }),
        run({ run_id: 'member-2', device_id: 'device-2', campaign_id: 1, campaign_name: 'summer-2026' }),
      ],
    })
    mockedUnassign.mockResolvedValue(SUMMER)
    render(<AdminCampaignsPage />)
    const panel = await openRunsPanel('summer-2026')
    await within(panel).findByText('member-1')

    fireEvent.click(within(panel).getByLabelText('Select run member-1 of device-1'))
    fireEvent.click(within(panel).getByLabelText('Select run member-2 of device-2'))
    fireEvent.click(within(panel).getByRole('button', { name: 'Remove selected' }))

    await waitFor(() =>
      expect(mockedUnassign).toHaveBeenCalledWith(1, [
        { device_id: 'device-1', run_id: 'member-1' },
        { device_id: 'device-2', run_id: 'member-2' },
      ]),
    )
  })

  it('can also offer runs of other campaigns, naming where they currently are', async () => {
    serveRuns({
      members: [run({ run_id: 'member-run', campaign_id: 1, campaign_name: 'summer-2026' })],
      unassigned: [run({ run_id: 'free-run' })],
      others: [run({ run_id: 'elsewhere', campaign_id: 9, campaign_name: 'winter-2026' })],
    })
    render(<AdminCampaignsPage />)
    const panel = await openRunsPanel('summer-2026')
    await within(panel).findByText('free-run')
    expect(within(panel).queryByText('elsewhere')).not.toBeInTheDocument()

    fireEvent.click(within(panel).getByLabelText('Include runs of other campaigns'))

    expect(await within(panel).findByText('elsewhere')).toBeInTheDocument()
    expect(within(panel).getByText('winter-2026')).toBeInTheDocument()
    // runs already in this campaign are not offered again
    const candidates = within(panel).getByRole('table', { name: 'Runs available to add' })
    expect(within(candidates).queryByText('member-run')).not.toBeInTheDocument()
  })

  it('shows the error when the backend rejects the change', async () => {
    serveRuns({ unassigned: [run({ run_id: 'free-1' })] })
    mockedAssign.mockRejectedValue(new ApiError('Not Found', 404, { detail: 'Run not found' }))
    render(<AdminCampaignsPage />)
    const panel = await openRunsPanel('summer-2026')
    await within(panel).findByText('free-1')

    fireEvent.click(within(panel).getByLabelText('Select run free-1 of device-1'))
    fireEvent.click(within(panel).getByRole('button', { name: 'Add selected' }))

    expect(await within(panel).findByText('Run not found')).toBeInTheDocument()
  })
})
