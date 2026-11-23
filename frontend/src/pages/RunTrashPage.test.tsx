import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RunTrashPage } from './RunTrashPage'
import { apiClient } from '../api/client'

vi.mock('../api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

const mockGet = vi.mocked(apiClient.get)
const mockPost = vi.mocked(apiClient.post)
const mockDelete = vi.mocked(apiClient.delete)

function trashedRun(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    name: 'Morning drive',
    run_id: 'run-abc',
    device_id: 'device-1',
    mission_type: 'ground',
    start: '2026-08-01T10:00:00Z',
    end: '2026-08-01T11:05:30Z',
    point_count: 120,
    latency_result_count: 3,
    campaign_id: 3,
    campaign_name: 'August',
    legacy: false,
    deleted_at: '2026-11-20T09:00:00Z',
    deleted_by: 1,
    deleted_by_email: 'admin',
    ...overrides,
  }
}

function trashResponse(runs: unknown[], total = runs.length, page = 1) {
  return { runs, total, page, page_size: 25 }
}

function renderTrashPage() {
  return render(
    <MemoryRouter initialEntries={['/runs/trash']}>
      <Routes>
        <Route path="/runs/trash" element={<RunTrashPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function trashRequests(): URLSearchParams[] {
  return mockGet.mock.calls
    .map(([path]) => path as string)
    .filter((path) => path.startsWith('/runs/trash?'))
    .map((path) => new URLSearchParams(path.slice('/runs/trash?'.length)))
}

beforeEach(() => {
  mockGet.mockResolvedValue(trashResponse([trashedRun()]))
  mockPost.mockResolvedValue(undefined)
  mockDelete.mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('RunTrashPage', () => {
  it('lists trashed runs with their data and who deleted them', async () => {
    renderTrashPage()

    const row = (await screen.findByText('Morning drive')).closest('tr') as HTMLElement
    expect(within(row).getByText('run-abc')).toBeInTheDocument()
    expect(within(row).getByText('device-1')).toBeInTheDocument()
    expect(within(row).getByText('120')).toBeInTheDocument()
    expect(within(row).getByText('3')).toBeInTheDocument()
    expect(within(row).getByText('August')).toBeInTheDocument()
    expect(within(row).getByText('admin')).toBeInTheDocument()
    expect(trashRequests()[0].get('page')).toBe('1')
  })

  it('shows an empty trash', async () => {
    mockGet.mockResolvedValue(trashResponse([]))
    renderTrashPage()

    expect(await screen.findByText('The trash is empty.')).toBeInTheDocument()
  })

  it('shows a dash for a run without measurements or a removed deleting user', async () => {
    mockGet.mockResolvedValue(
      trashResponse([
        trashedRun({ start: null, end: null, point_count: 0, deleted_by: null, deleted_by_email: null }),
      ]),
    )
    renderTrashPage()

    const row = (await screen.findByText('Morning drive')).closest('tr') as HTMLElement
    expect(within(row).getAllByText('–').length).toBeGreaterThanOrEqual(2)
  })

  it('restores a run and reloads the trash', async () => {
    renderTrashPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Restore run Morning drive' }))

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/runs/7/restore'))
    await waitFor(() => expect(trashRequests()).toHaveLength(2))
  })

  it('asks for confirmation before deleting a run permanently', async () => {
    renderTrashPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete run Morning drive permanently' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete run permanently' })

    expect(dialog).toHaveTextContent('120 measurements')
    expect(dialog).toHaveTextContent('cannot be undone')
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    expect(mockDelete).not.toHaveBeenCalled()

    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete permanently' }))

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('/runs/trash/7'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(trashRequests()).toHaveLength(2))
  })

  it('does not delete anything when the confirmation is cancelled', async () => {
    renderTrashPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete run Morning drive permanently' }))

    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mockDelete).not.toHaveBeenCalled()
  })

  it('pages through the trash', async () => {
    mockGet.mockResolvedValue(trashResponse([trashedRun()], 26))
    renderTrashPage()
    await screen.findByText('Morning drive')

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(trashRequests().at(-1)?.get('page')).toBe('2'))
  })
})
