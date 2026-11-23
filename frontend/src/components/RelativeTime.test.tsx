import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { Duration } from './Duration'
import { RelativeTime } from './RelativeTime'

const NOW = new Date('2026-10-23T12:00:00Z')

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('RelativeTime', () => {
  it('renders the elapsed time since an ISO string with the absolute time as tooltip', () => {
    render(<RelativeTime since="2026-10-23T11:58:55Z" />)

    const element = screen.getByText('1 min 5 s ago')
    expect(element.tagName).toBe('TIME')
    expect(element).toHaveAttribute('datetime', '2026-10-23T11:58:55.000Z')
    expect(element.getAttribute('title')).toMatch(/2026/)
  })

  it('accepts epoch milliseconds', () => {
    render(<RelativeTime since={NOW.getTime() - 45_000} />)
    expect(screen.getByText('45 s ago')).toBeInTheDocument()
  })

  it('keeps ticking', () => {
    render(<RelativeTime since={NOW.getTime()} />)
    expect(screen.getByText('0 s ago')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(65_000)
    })

    expect(screen.getByText('1 min 5 s ago')).toBeInTheDocument()
  })

  it('switches language live', async () => {
    render(<RelativeTime since={NOW.getTime() - 65_000} />)
    await act(async () => {
      await i18n.changeLanguage('de')
    })
    expect(screen.getByText('vor 1 Min. 5 Sek.')).toBeInTheDocument()
  })

  it.each([null, undefined, 'not a date', Number.NaN, Infinity, 1e20])(
    'renders a neutral placeholder without attributes for %s',
    (since) => {
      const { container } = render(<RelativeTime since={since} />)
      expect(container).toHaveTextContent('—')
      expect(container.querySelector('time')).toBeNull()
    },
  )

  it('clears its timer on unmount', () => {
    const { unmount } = render(<RelativeTime since={NOW.getTime()} />)
    expect(vi.getTimerCount()).toBe(1)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('shares one timer between many labels', () => {
    render(
      <>
        <RelativeTime since={NOW.getTime()} />
        <RelativeTime since={NOW.getTime() - 5000} />
        <RelativeTime since={NOW.getTime() - 10_000} />
      </>,
    )
    expect(vi.getTimerCount()).toBe(1)
  })
})

describe('Duration', () => {
  it('renders an elapsed value without "ago"', () => {
    render(<Duration seconds={125} />)
    expect(screen.getByText('2 min 5 s')).toBeInTheDocument()
  })

  it('does not start a timer', () => {
    render(<Duration seconds={5} />)
    expect(vi.getTimerCount()).toBe(0)
  })

  it.each([null, undefined, Number.NaN, Infinity])('renders a placeholder for %s', (seconds) => {
    const { container } = render(<Duration seconds={seconds} />)
    expect(container).toHaveTextContent('—')
  })
})
