import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { openCommandAckStream, type CommandAckStreamHandlers } from '../api/commandAckStream'
import { useAuth } from './AuthProvider'
import { CommandAckNotifications } from './CommandAckNotifications'
import { TOAST_DURATION_MS, TOAST_FADE_MS, ToastProvider } from './ToastProvider'

vi.mock('./AuthProvider', () => ({ useAuth: vi.fn() }))
vi.mock('../api/commandAckStream', () => ({ openCommandAckStream: vi.fn() }))

const mockUseAuth = vi.mocked(useAuth)
const mockOpenCommandAckStream = vi.mocked(openCommandAckStream)

function renderBridge() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <CommandAckNotifications />
      </ToastProvider>
    </MemoryRouter>,
  )
}

function loginAs(isSuperuser: boolean) {
  mockUseAuth.mockReturnValue({ user: { is_superuser: isSuperuser } } as ReturnType<typeof useAuth>)
}

function captureHandlers(): { get: () => CommandAckStreamHandlers } {
  let handlers!: CommandAckStreamHandlers
  mockOpenCommandAckStream.mockImplementation((h) => {
    handlers = h
    return vi.fn()
  })
  return { get: () => handlers }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('CommandAckNotifications', () => {
  it('does not open the stream for a non-superuser', () => {
    loginAs(false)

    renderBridge()

    expect(mockOpenCommandAckStream).not.toHaveBeenCalled()
  })

  it('shows a success toast that auto-dismisses', () => {
    loginAs(true)
    const handlers = captureHandlers()
    vi.useFakeTimers()

    renderBridge()
    act(() => {
      handlers.get().onAck({
        device_id: '5gmu_1',
        command_id: 45,
        command: 'promote-overrides-now',
        status: 'success',
        error: null,
        received_at: '2026-01-01T00:00:30+00:00',
      })
    })

    expect(screen.getByText('Command succeeded: Promote overrides on 5gmu_1.')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(TOAST_DURATION_MS)
    })
    act(() => {
      vi.advanceTimersByTime(TOAST_FADE_MS)
    })
    expect(screen.queryByText(/Command succeeded/)).not.toBeInTheDocument()
    vi.useRealTimers()
  })

  it('shows a failure toast with the error message that auto-dismisses like any other', () => {
    loginAs(true)
    const handlers = captureHandlers()
    vi.useFakeTimers()

    renderBridge()
    act(() => {
      handlers.get().onAck({
        device_id: '5gmu_1',
        command_id: 46,
        command: 'fan-override-now',
        status: 'failed',
        error: 'Fan control is disabled locally - ignoring fan override.',
        received_at: '2026-01-01T00:00:30+00:00',
      })
    })

    expect(
      screen.getByText(
        'Command failed: fan-override-now on 5gmu_1 - Fan control is disabled locally - ignoring fan override.',
      ),
    ).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(TOAST_DURATION_MS)
    })
    act(() => {
      vi.advanceTimersByTime(TOAST_FADE_MS)
    })
    expect(screen.queryByText(/Command failed/)).not.toBeInTheDocument()
    vi.useRealTimers()
  })

  it.each([
    ['shutdown-now', 'is shutting down'],
    ['reboot-now', 'is rebooting'],
  ])('describes a "received" ack for %s as the device %s', (command, phrase) => {
    loginAs(true)
    const handlers = captureHandlers()

    renderBridge()
    act(() => {
      handlers.get().onAck({
        device_id: '5gmu_1',
        command_id: 47,
        command,
        status: 'received',
        error: null,
        received_at: '2026-01-01T00:00:30+00:00',
      })
    })

    expect(screen.getByText(`5gmu_1 ${phrase}.`)).toBeInTheDocument()

  })

  it('closes the stream subscription on unmount', () => {
    loginAs(true)
    const closeSpy = vi.fn()
    mockOpenCommandAckStream.mockReturnValue(closeSpy)

    const { unmount } = renderBridge()
    unmount()

    expect(closeSpy).toHaveBeenCalled()
  })

  describe('self-test results link', () => {
    function ack(command: string, status: 'success' | 'failed' | 'not_applicable') {
      const handlers = captureHandlers()
      loginAs(true)
      renderBridge()
      act(() => {
        handlers.get().onAck({
          device_id: '5gmu_1',
          command_id: 46,
          command,
          status,
          error: status === 'success' ? null : 'boom',
          received_at: '2026-01-01T00:00:30+00:00',
        })
      })
    }

    it('is shown for a succeeded run-selftest-now', () => {
      ack('run-selftest-now', 'success')

      expect(screen.getByRole('link', { name: 'View self-test results' })).toHaveAttribute(
        'href',
        '/testing/visualization',
      )
    })

    it.each(['failed', 'not_applicable'] as const)('is not shown for a %s run-selftest-now', (status) => {
      ack('run-selftest-now', status)

      expect(screen.queryByRole('link')).not.toBeInTheDocument()
    })

    it('is not shown for another succeeded command', () => {
      ack('reboot-now', 'success')

      expect(screen.queryByRole('link')).not.toBeInTheDocument()
    })
  })
})
