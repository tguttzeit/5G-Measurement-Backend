import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useNow } from './useNow'

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-23T12:00:00Z'))
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('useNow', () => {
  it('advances every second', () => {
    const { result } = renderHook(() => useNow())
    const start = result.current

    act(() => {
      vi.advanceTimersByTime(3000)
    })

    expect(result.current - start).toBe(3000)
  })

  it('shares one interval between all subscribers', () => {
    const first = renderHook(() => useNow())
    const second = renderHook(() => useNow())
    const third = renderHook(() => useNow())

    expect(vi.getTimerCount()).toBe(1)
    first.unmount()
    second.unmount()
    expect(vi.getTimerCount()).toBe(1)
    third.unmount()
  })

  it('stops the interval when the last subscriber unmounts and restarts it for a new one', () => {
    const first = renderHook(() => useNow())
    first.unmount()
    expect(vi.getTimerCount()).toBe(0)

    const second = renderHook(() => useNow())
    expect(vi.getTimerCount()).toBe(1)
    second.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not tick while disabled', () => {
    const { result, rerender } = renderHook(({ enabled }) => useNow(enabled), { initialProps: { enabled: false } })
    expect(vi.getTimerCount()).toBe(0)

    rerender({ enabled: true })
    expect(vi.getTimerCount()).toBe(1)
    const start = result.current
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(result.current - start).toBe(1000)

    rerender({ enabled: false })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('catches up to the current time when a subscriber mounts after a pause', () => {
    const first = renderHook(() => useNow())
    first.unmount()
    vi.setSystemTime(new Date('2026-10-23T12:10:00Z'))

    const second = renderHook(() => useNow())
    expect(second.result.current).toBe(Date.now())
    second.unmount()
  })
})
