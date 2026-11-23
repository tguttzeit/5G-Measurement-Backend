import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TestingVisualizationPage } from './TestingVisualizationPage'
import { apiClient } from '../api/client'
import { useAuth } from '../components/AuthProvider'

vi.mock('../api/client', () => ({
  apiClient: {
    get: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.status = status
    }
  },
}))

vi.mock('../components/AuthProvider', () => ({ useAuth: vi.fn() }))

const mockUseAuth = vi.mocked(useAuth)
const mockGet = vi.mocked(apiClient.get)
const mockDelete = vi.mocked(apiClient.delete)

const fakeResults = [
  {
    id: 1,
    device_id: 'probe-device-01',
    test_type: 'modem',
    status: 'passed',
    executed_at: '2026-01-01T00:00:00Z',
    is_testing: true,
    duration_ms: 100,
    error_message: null,
  },
  {
    id: 2,
    device_id: 'probe-device-02',
    test_type: 'gps',
    status: 'failed',
    executed_at: '2026-01-01T00:00:00Z',
    is_testing: true,
    duration_ms: 200,
    error_message: 'boom',
  },
]

const fakeSummary = {
  total_tests: 2,
  passed: 1,
  failed: 1,
  running: 0,
  skipped: 0,
  by_test_type: {},
  recent_executions: [],
  failures_by_type_and_message: [],
}

function mockListResponses() {
  mockGet.mockImplementation((path: string) => {
    if (path.startsWith('/testing/results')) {
      return Promise.resolve({ results: fakeResults, total: fakeResults.length, page: 1, page_size: 50 })
    }
    if (path.startsWith('/testing/summary')) {
      return Promise.resolve(fakeSummary)
    }
    if (path === '/devices') return Promise.resolve({ devices: [] })
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
}

beforeEach(() => {
  mockUseAuth.mockReturnValue({ user: { is_superuser: false } } as ReturnType<typeof useAuth>)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe('TestingVisualizationPage delete actions', () => {
  it('deletes only the selected rows after confirmation', async () => {
    mockListResponses()
    mockDelete.mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<TestingVisualizationPage />)

    await waitFor(() => expect(screen.getByText('probe-device-01')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('Select test result 1'))
    fireEvent.click(screen.getByText(/Delete selected \(1\)/))

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('/testing/results/1'))
    expect(mockDelete).not.toHaveBeenCalledWith('/testing/results/2')
  })

  it('does not delete when the confirmation dialog is cancelled', async () => {
    mockListResponses()
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(<TestingVisualizationPage />)

    await waitFor(() => expect(screen.getByText('probe-device-01')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('Select test result 1'))
    fireEvent.click(screen.getByText(/Delete selected \(1\)/))

    expect(mockDelete).not.toHaveBeenCalled()
  })

  it('calls the bulk delete endpoint when Delete All is confirmed', async () => {
    mockListResponses()
    mockDelete.mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<TestingVisualizationPage />)

    await waitFor(() => expect(screen.getByText('probe-device-01')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Delete All'))

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('/testing/results'))
  })
})

describe('TestingVisualizationPage GPS fix panel', () => {
  it('is only offered to superusers', async () => {
    mockListResponses()

    const { unmount } = render(<TestingVisualizationPage />)
    await waitFor(() => expect(screen.getByText('probe-device-01')).toBeInTheDocument())
    expect(screen.queryByText('Find GPS Fix')).not.toBeInTheDocument()
    unmount()

    mockUseAuth.mockReturnValue({ user: { is_superuser: true } } as ReturnType<typeof useAuth>)
    render(<TestingVisualizationPage />)
    expect(await screen.findByText('Find GPS Fix')).toBeInTheDocument()
  })
})
