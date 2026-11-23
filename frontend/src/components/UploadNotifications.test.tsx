import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { openUploadStream, type UploadStreamHandlers } from '../api/uploadStream'
import { useAuth } from './AuthProvider'
import { ToastProvider } from './ToastProvider'
import { UploadNotifications } from './UploadNotifications'

vi.mock('./AuthProvider', () => ({ useAuth: vi.fn() }))
vi.mock('../api/uploadStream', () => ({ openUploadStream: vi.fn() }))

const mockUseAuth = vi.mocked(useAuth)
const mockOpenUploadStream = vi.mocked(openUploadStream)

function renderBridge() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <UploadNotifications />
      </ToastProvider>
    </MemoryRouter>,
  )
}

function loginAs(isSuperuser: boolean) {
  mockUseAuth.mockReturnValue({ user: { is_superuser: isSuperuser } } as ReturnType<typeof useAuth>)
}

// The message is JSX (the run id renders inside its own <code>), so its text is split across
// several nodes - screen.getByText can't match a sentence spanning them. Read the whole thing
// off the message span's textContent instead, same as a user reading the rendered toast.
function toastMessageText(): string {
  return document.querySelector('.toast__message')?.textContent ?? ''
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('UploadNotifications', () => {
  it('does not open the stream for a non-superuser', () => {
    loginAs(false)

    renderBridge()

    expect(mockOpenUploadStream).not.toHaveBeenCalled()
  })

  it('shows a success toast with the run id and point count, linking to Runs', () => {
    loginAs(true)
    let handlers!: UploadStreamHandlers
    mockOpenUploadStream.mockImplementation((h) => {
      handlers = h
      return vi.fn()
    })

    renderBridge()
    act(() => {
      handlers.onUpload({
        device_id: '5gmu_1',
        run_ids: ['746841d6-bbdb-4dc3-bfc6-ac6153f37720'],
        point_count: 3,
        received_at: '2026-10-16T10:08:45+00:00',
      })
    })

    expect(toastMessageText()).toMatch(
      /Upload successful: 5gmu_1 sent 3 points from run 746841d6-bbdb-4dc3-bfc6-ac6153f37720\./,
    )
    // The run id is its own <code> element, not just plain text.
    expect(document.querySelector('.toast__message code')?.textContent).toBe(
      '746841d6-bbdb-4dc3-bfc6-ac6153f37720',
    )
    const link = screen.getByRole('link', { name: 'View in Runs' })
    expect(link).toHaveAttribute(
      'href',
      '/runs?device_id=5gmu_1&run_id=746841d6-bbdb-4dc3-bfc6-ac6153f37720',
    )
  })

  it('uses singular "point" for a single-point upload', () => {
    loginAs(true)
    let handlers!: UploadStreamHandlers
    mockOpenUploadStream.mockImplementation((h) => {
      handlers = h
      return vi.fn()
    })

    renderBridge()
    act(() => {
      handlers.onUpload({ device_id: '5gmu_1', run_ids: ['run-01'], point_count: 1, received_at: '2026-10-16T10:08:45+00:00' })
    })

    expect(toastMessageText()).toMatch(/sent 1 point from run run-01\./)
  })

  it('describes a batch with no run id as unlabeled', () => {
    loginAs(true)
    let handlers!: UploadStreamHandlers
    mockOpenUploadStream.mockImplementation((h) => {
      handlers = h
      return vi.fn()
    })

    renderBridge()
    act(() => {
      handlers.onUpload({ device_id: '5gmu_1', run_ids: [null], point_count: 2, received_at: '2026-10-16T10:08:45+00:00' })
    })

    expect(screen.getByText(/from an unlabeled run/)).toBeInTheDocument()
  })

  it('closes the stream subscription on unmount', () => {
    loginAs(true)
    const closeSpy = vi.fn()
    mockOpenUploadStream.mockReturnValue(closeSpy)

    const { unmount } = renderBridge()
    unmount()

    expect(closeSpy).toHaveBeenCalled()
  })
})
