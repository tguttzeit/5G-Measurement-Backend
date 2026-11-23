import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOAST_DURATION_MS, TOAST_FADE_MS, ToastProvider, useToast, type ToastOptions } from './ToastProvider'

let showToast!: (options: ToastOptions) => void

function Capture() {
  showToast = useToast().showToast
  return null
}

function renderProvider() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <Capture />
      </ToastProvider>
    </MemoryRouter>,
  )
}

function show(message: string, extra: Partial<ToastOptions> = {}) {
  act(() => showToast({ tone: 'success', message, ...extra }))
}

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms)
  })
}

// The fade timer is scheduled by an effect after the re-render the first timer causes, so the two
// phases have to be advanced separately.
function advanceThroughFade(ms: number) {
  advance(ms)
  advance(TOAST_FADE_MS)
}

function mockReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches: reduce && query.includes('prefers-reduced-motion'),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  )
}

beforeEach(() => {
  vi.useFakeTimers()
  mockReducedMotion(false)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('ToastProvider auto-dismiss', () => {
  it('removes a toast after the toast duration plus the fade', () => {
    renderProvider()
    show('Saved')

    advance(TOAST_DURATION_MS - 1)
    expect(screen.getByText('Saved')).toBeInTheDocument()
    expect(document.querySelector('.toast')).not.toHaveClass('toast--leaving')

    advance(1)
    expect(document.querySelector('.toast')).toHaveClass('toast--leaving')

    advance(TOAST_FADE_MS)
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
  })

  it('dismisses danger toasts too', () => {
    renderProvider()
    show('Failed', { tone: 'danger' })

    advanceThroughFade(TOAST_DURATION_MS)
    expect(screen.queryByText('Failed')).not.toBeInTheDocument()
  })

  it('stops the countdown on hover and restarts it from the full duration on leave', () => {
    renderProvider()
    show('Saved')
    const toast = document.querySelector('.toast') as HTMLElement

    advance(TOAST_DURATION_MS - 1000)
    fireEvent.mouseEnter(toast)
    advance(TOAST_DURATION_MS * 3)
    expect(screen.getByText('Saved')).toBeInTheDocument()

    fireEvent.mouseLeave(toast)
    advance(TOAST_DURATION_MS - 1)
    expect(screen.getByText('Saved')).toBeInTheDocument()
    advanceThroughFade(1)
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
  })

  it('behaves the same for keyboard focus within the toast', () => {
    renderProvider()
    show('Saved')
    const close = screen.getByRole('button', { name: 'Dismiss notification' })

    advance(TOAST_DURATION_MS - 1000)
    act(() => close.focus())
    advance(TOAST_DURATION_MS * 3)
    expect(screen.getByText('Saved')).toBeInTheDocument()

    act(() => close.blur())
    advance(TOAST_DURATION_MS - 1)
    expect(screen.getByText('Saved')).toBeInTheDocument()
    advanceThroughFade(1)
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
  })

  it('cancels a fade in progress when the pointer enters', () => {
    renderProvider()
    show('Saved')
    const toast = document.querySelector('.toast') as HTMLElement

    advance(TOAST_DURATION_MS)
    expect(toast).toHaveClass('toast--leaving')

    fireEvent.mouseEnter(toast)
    expect(toast).not.toHaveClass('toast--leaving')
    advance(TOAST_FADE_MS * 5)
    expect(screen.getByText('Saved')).toBeInTheDocument()
  })

  it('restarts the countdown on touch', () => {
    renderProvider()
    show('Saved')
    const toast = document.querySelector('.toast') as HTMLElement

    advance(TOAST_DURATION_MS - 1000)
    fireEvent.touchStart(toast)
    advance(TOAST_DURATION_MS - 1)
    expect(screen.getByText('Saved')).toBeInTheDocument()
    advanceThroughFade(1)
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
  })

  it('clears the timer when a toast is dismissed manually', () => {
    const clearSpy = vi.spyOn(globalThis, 'clearTimeout')
    renderProvider()
    show('Saved')

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }))
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
    expect(clearSpy).toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('runs independent timers per toast', () => {
    renderProvider()
    show('First')
    advance(2000)
    show('Second')

    advanceThroughFade(TOAST_DURATION_MS - 2000)
    expect(screen.queryByText('First')).not.toBeInTheDocument()
    expect(screen.getByText('Second')).toBeInTheDocument()

    advanceThroughFade(2000 - TOAST_FADE_MS)
    expect(screen.queryByText('Second')).not.toBeInTheDocument()
  })

  it('hovering one toast does not pause the others', () => {
    renderProvider()
    show('First')
    show('Second')
    const first = screen.getByText('First').closest('.toast') as HTMLElement

    fireEvent.mouseEnter(first)
    advanceThroughFade(TOAST_DURATION_MS)
    expect(screen.getByText('First')).toBeInTheDocument()
    expect(screen.queryByText('Second')).not.toBeInTheDocument()
  })

  it('leaves no pending timers after unmount', () => {
    const { unmount } = renderProvider()
    show('Saved')
    advance(TOAST_DURATION_MS)

    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('ToastProvider progress bar', () => {
  it('renders a decorative progress bar running for the toast duration', () => {
    renderProvider()
    show('Saved')

    const bar = document.querySelector('.toast__progress') as HTMLElement
    expect(bar).toHaveAttribute('aria-hidden', 'true')
    expect(bar.style.animationDuration).toBe(`${TOAST_DURATION_MS}ms`)
    expect(bar).not.toHaveClass('toast__progress--paused')
  })

  it('shows a full, paused bar while hovered and a fresh bar after leaving', () => {
    renderProvider()
    show('Saved')
    const toast = document.querySelector('.toast') as HTMLElement
    const initialBar = document.querySelector('.toast__progress')

    fireEvent.mouseEnter(toast)
    const pausedBar = document.querySelector('.toast__progress')
    expect(pausedBar).toHaveClass('toast__progress--paused')
    expect(pausedBar).not.toBe(initialBar)

    fireEvent.mouseLeave(toast)
    expect(document.querySelector('.toast__progress')).not.toHaveClass('toast__progress--paused')
  })
})

describe('ToastProvider with reduced motion', () => {
  it('shows a static bar and removes the toast after the timer without a fade', () => {
    mockReducedMotion(true)
    renderProvider()
    show('Saved')

    expect(document.querySelector('.toast__progress')).toHaveClass('toast__progress--static')

    advance(TOAST_DURATION_MS)
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
  })
})
