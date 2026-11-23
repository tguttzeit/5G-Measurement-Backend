import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CommandStatusItem } from '../api/commands'
import { buildSteps, CommandStatusList } from './CommandStatusList'

afterEach(cleanup)

function item(overrides: Partial<CommandStatusItem> = {}): CommandStatusItem {
  return {
    command_id: 1,
    kind: 'command',
    name: 'force-upload-now',
    detail: null,
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
    ...overrides,
  }
}

const summary_ = (steps: ReturnType<typeof buildSteps>) =>
  steps.map((step) => `${step.label}:${step.tone}`)
const summary = (i: CommandStatusItem) => summary_(buildSteps(i))

describe('buildSteps', () => {
  it('shows a freshly queued command as waiting for delivery', () => {
    expect(summary(item())).toEqual([
      'Queued:done',
      'Sent:current',
      'Received:upcoming',
      'Result:upcoming',
    ])
  })

  it('marks every step done on success', () => {
    const done = item({
      state: 'success',
      complete: true,
      delivered_at: '2026-01-01T00:00:01Z',
      received_at: '2026-01-01T00:00:02Z',
      result_at: '2026-01-01T00:00:03Z',
    })
    expect(summary(done)).toEqual([
      'Queued:done',
      'Sent:done',
      'Received:done',
      'Success:done',
    ])
  })

  it('shows a failed result in the danger tone', () => {
    const failed = item({
      state: 'failed',
      complete: true,
      delivered_at: '2026-01-01T00:00:01Z',
      result_at: '2026-01-01T00:00:03Z',
    })
    expect(summary(failed).at(-1)).toBe('Failed:danger')
    // No "received" timestamp, but a later step was reached, so there is no gap in the line.
    expect(summary(failed)).toContain('Received:done')
  })

  it('shows a received shutdown-now counting elapsed time up to a fixed time span', () => {
    const shutdown = item({ name: 'shutdown-now', state: 'received', received_at: '2026-01-01T00:00:02Z' })
    const [last] = buildSteps(shutdown, { mode: 'seconds', elapsed: 45, required: 90 }).slice(-1)
    expect(last.label).toBe('Offline 45 s / 1 min 30 s')
    expect(last.progress).toBe(0.5)
    // Never counts past the required time span.
    expect(buildSteps(shutdown, { mode: 'seconds', elapsed: 500, required: 90 }).at(-1)?.label).toBe(
      'Offline 1 min 30 s / 1 min 30 s',
    )
  })

  it('shows a received shutdown-now counting up to the silent intervals', () => {
    const shutdown = item({
      name: 'shutdown-now',
      state: 'received',
      delivered_at: '2026-01-01T00:00:01Z',
      received_at: '2026-01-01T00:00:02Z',
    })
    const at = (missedIntervals: number) =>
      summary_(buildSteps(shutdown, { mode: 'intervals', elapsed: missedIntervals, required: 4 }))
    expect(at(0)).toEqual(['Queued:done', 'Sent:done', 'Received:done', 'Offline 0/4:current'])
    expect(at(2).at(-1)).toBe('Offline 2/4:current')
    expect(buildSteps(shutdown, { mode: 'intervals', elapsed: 2, required: 4 }).at(-1)?.progress).toBe(0.5)
    // Never counts past the required number, even if the page was left open for a long time.
    expect(at(9).at(-1)).toBe('Offline 4/4:current')
  })

  it('ends a shutdown-now whose device kept sending heartbeats on Still online', () => {
    const shutdown = item({
      name: 'shutdown-now',
      state: 'failed',
      complete: true,
      in_queue: false,
      delivered_at: '2026-01-01T00:00:01Z',
      received_at: '2026-01-01T00:00:02Z',
      result_at: '2026-01-01T00:03:02Z',
      error: 'device still sending heartbeats 10 heartbeats after acknowledging the shutdown',
    })
    expect(summary(shutdown)).toEqual([
      'Queued:done',
      'Sent:done',
      'Received:done',
      'Still online:danger',
    ])
  })

  it('ends a confirmed shutdown-now on Offline', () => {
    const shutdown = item({
      name: 'shutdown-now',
      state: 'success',
      complete: true,
      in_queue: false,
      delivered_at: '2026-01-01T00:00:01Z',
      received_at: '2026-01-01T00:00:02Z',
      result_at: '2026-01-01T00:01:02Z',
    })
    expect(summary(shutdown)).toEqual([
      'Queued:done',
      'Sent:done',
      'Received:done',
      'Offline:done',
    ])
  })

  it('keeps waiting for the result after reboot-now was received', () => {
    const reboot = item({
      name: 'reboot-now',
      state: 'received',
      delivered_at: '2026-01-01T00:00:01Z',
      received_at: '2026-01-01T00:00:02Z',
    })
    expect(summary(reboot)).toEqual([
      'Queued:done',
      'Sent:done',
      'Received:done',
      'Result:current',
    ])
  })

  it('has no received step for a config override, and ends on Applied', () => {
    const config = item({ kind: 'config', name: 'idle_threshold_s', state: 'delivered' })
    expect(summary({ ...config, delivered_at: '2026-01-01T00:00:01Z' })).toEqual([
      'Queued:done',
      'Sent:done',
      'Applied:current',
    ])
    expect(
      summary({
        ...config,
        state: 'success',
        complete: true,
        delivered_at: '2026-01-01T00:00:01Z',
        result_at: '2026-01-01T00:00:09Z',
      }).at(-1),
    ).toBe('Applied:done')
  })

  it('ends a promoted override on Promoted, not on Applied', () => {
    const promoted = item({
      kind: 'config',
      name: 'idle_threshold_s',
      state: 'promoted',
      complete: true,
      in_queue: false,
      delivered_at: '2026-01-01T00:00:01Z',
      promoted_at: '2026-01-01T00:00:01Z',
    })
    expect(summary(promoted)).toEqual(['Queued:done', 'Sent:done', 'Promoted:done'])
  })

  it('ends an expired command on Expired', () => {
    const expired = item({
      state: 'expired',
      complete: true,
      in_queue: false,
      expired_at: '2026-01-02T00:00:00Z',
    })
    expect(summary(expired)).toEqual(['Queued:done', 'Expired:danger'])
  })

  it('ends a removed command with a Removed step after the last reached one', () => {
    const removed = item({
      state: 'removed',
      complete: true,
      in_queue: false,
      removed_at: '2026-01-01T00:00:05Z',
    })
    expect(summary(removed)).toEqual(['Queued:done', 'Removed:danger'])
  })
})

describe('CommandStatusList shutdown progress', () => {
  const shutdown = item({
    name: 'shutdown-now',
    state: 'received',
    delivered_at: '2026-01-01T00:00:01Z',
    received_at: '2026-01-01T00:00:02Z',
  })

  afterEach(() => vi.useRealTimers())

  it('counts the intervals missed since the last heartbeat', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:00:40Z')) // 40s after the last heartbeat, 15s each

    render(
      <CommandStatusList
        items={[shutdown]}
        heartbeat={{
          last_heartbeat_at: '2026-01-01T00:00:00Z',
          heartbeat_interval_s: 15,
          shutdown_confirm_mode: 'intervals' as const,
          shutdown_confirm_intervals: 4,
          shutdown_confirm_seconds: 60,
          shutdown_fail_heartbeats: 10,
        }}
      />,
    )

    expect(screen.getByText('Offline 2/4')).toBeInTheDocument()
    expect(screen.getByText('Waiting for device to go offline')).toBeInTheDocument()
  })

  it('counts elapsed time up to a configured fixed time span', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:00:40Z'))

    render(
      <CommandStatusList
        items={[shutdown]}
        heartbeat={{
          last_heartbeat_at: '2026-01-01T00:00:00Z',
          heartbeat_interval_s: 15,
          shutdown_confirm_mode: 'seconds',
          shutdown_confirm_intervals: 6,
          shutdown_confirm_seconds: 90,
          shutdown_fail_heartbeats: 10,
        }}
      />,
    )

    expect(screen.getByText('Offline 40 s / 1 min 30 s')).toBeInTheDocument()
  })

  it('asks for a refresh once a fixed time span is used up, not after the heartbeat intervals', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:01:20Z')) // 80 s: past 4 x 15 s, short of 90 s
    const onShutdownDue = vi.fn()
    const heartbeat = {
      last_heartbeat_at: '2026-01-01T00:00:00Z',
      heartbeat_interval_s: 15,
      shutdown_confirm_mode: 'seconds' as const,
      shutdown_confirm_intervals: 6,
      shutdown_confirm_seconds: 90,
      shutdown_fail_heartbeats: 10,
    }

    render(<CommandStatusList items={[shutdown]} heartbeat={heartbeat} onShutdownDue={onShutdownDue} />)
    expect(onShutdownDue).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(10_000)
    })

    expect(onShutdownDue).toHaveBeenCalledTimes(1)
  })

  it('asks for a refresh once, when all intervals are used up', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:00:50Z'))
    const onShutdownDue = vi.fn()
    const heartbeat = {
      last_heartbeat_at: '2026-01-01T00:00:00Z',
      heartbeat_interval_s: 15,
      shutdown_confirm_mode: 'intervals' as const,
      shutdown_confirm_intervals: 4,
      shutdown_confirm_seconds: 60,
      shutdown_fail_heartbeats: 10,
    }

    const { rerender } = render(
      <CommandStatusList items={[shutdown]} heartbeat={heartbeat} onShutdownDue={onShutdownDue} />,
    )
    expect(onShutdownDue).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(15_000)
    })
    expect(screen.getByText('Offline 4/4')).toBeInTheDocument()
    expect(onShutdownDue).toHaveBeenCalledTimes(1)

    rerender(
      <CommandStatusList items={[shutdown]} heartbeat={heartbeat} onShutdownDue={onShutdownDue} />,
    )
    expect(onShutdownDue).toHaveBeenCalledTimes(1)
  })
})

describe('CommandStatusList', () => {
  it('shows the name, id, state label and the error text', () => {
    render(
      <CommandStatusList
        items={[
          item({
            name: 'sim-reset-now',
            command_id: 7,
            state: 'failed',
            complete: true,
            result_at: '2026-01-01T00:00:03Z',
            error: 'modem not responding',
          }),
        ]}
      />,
    )

    expect(screen.getByText('Reset SIM')).toBeInTheDocument()
    expect(screen.getByText('command #7')).toBeInTheDocument()
    expect(screen.getAllByText('Failed').length).toBeGreaterThan(0)
    expect(screen.getByText('modem not responding')).toBeInTheDocument()
  })

  it('keeps the API name as tooltip and shows unknown commands and config overrides raw', () => {
    render(
      <CommandStatusList
        items={[
          item({ name: 'reboot-now', command_id: 1 }),
          item({ name: 'brand-new-now', command_id: 2 }),
          item({ name: 'reboot-now', command_id: 3, kind: 'config' }),
        ]}
      />,
    )

    expect(screen.getAllByText('Reboot')).toHaveLength(1)
    expect(screen.getByText('brand-new-now')).toHaveAttribute('title', 'brand-new-now')
    expect(screen.getAllByText('reboot-now')).toHaveLength(1)
  })

  it('shows a config override with its value', () => {
    render(
      <CommandStatusList
        items={[item({ kind: 'config', name: 'rsrp_threshold', detail: '= -95' })]}
      />,
    )

    expect(screen.getByText('rsrp_threshold = -95')).toBeInTheDocument()
    expect(screen.getByText('Waiting for delivery')).toBeInTheDocument()
  })
})

describe('CommandStatusList names filter', () => {
  const upload = item({ command_id: 1, name: 'force-upload-now' })
  const gpsStart = item({ command_id: 2, name: 'run-gps-fix-test-now' })
  const gpsStop = item({ command_id: 3, name: 'stop-gps-fix-test-now' })

  it('shows every item without a names filter', () => {
    render(<CommandStatusList items={[upload, gpsStart, gpsStop]} />)

    expect(screen.getAllByRole('listitem').filter((li) => li.className === 'command-status')).toHaveLength(3)
  })

  it('shows only the items whose name is listed', () => {
    render(
      <CommandStatusList
        items={[upload, gpsStart, gpsStop]}
        names={['run-gps-fix-test-now', 'stop-gps-fix-test-now']}
      />,
    )

    expect(screen.queryByText('Force upload')).not.toBeInTheDocument()
    expect(screen.getByText('Start GPS fix test')).toBeInTheDocument()
    expect(screen.getByText('Stop GPS fix test')).toBeInTheDocument()
  })

  it('does not run the shutdown countdown for filtered-out items', () => {
    const shutdown = item({ command_id: 4, name: 'shutdown-now', state: 'received' })
    const onShutdownDue = vi.fn()
    render(
      <CommandStatusList
        items={[shutdown]}
        names={['run-gps-fix-test-now']}
        heartbeat={{
          last_heartbeat_at: '2000-01-01T00:00:00Z',
          heartbeat_interval_s: 1,
          shutdown_confirm_mode: 'intervals' as const,
          shutdown_confirm_intervals: 1,
          shutdown_confirm_seconds: 1,
          shutdown_fail_heartbeats: 10,
        }}
        onShutdownDue={onShutdownDue}
      />,
    )

    expect(onShutdownDue).not.toHaveBeenCalled()
  })
})

describe('CommandStatusList timestamps', () => {
  afterEach(() => vi.useRealTimers())

  const queued = item({ queued_at: '2026-03-10T09:15:00Z', delivered_at: '2026-03-05T09:15:00Z' })

  it('shows only the time for steps from today and the date as well for earlier ones', () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-03-10T12:00:00Z'))

    const { container } = render(<CommandStatusList items={[queued]} />)

    const texts = Array.from(container.querySelectorAll('.command-timeline__time time')).map((el) => el.textContent)
    expect(texts[0]).toMatch(/^\d{2}:\d{2}:\d{2}$/)
    expect(texts[1]).toMatch(/^\d{2}\/\d{2}\/2026, \d{2}:\d{2}:\d{2}$/)
  })
})

describe('CommandStatusList shutdown result info', () => {
  const heartbeat = {
    last_heartbeat_at: '2026-01-01T00:00:00Z',
    heartbeat_interval_s: 15,
    shutdown_confirm_mode: 'intervals' as const,
    shutdown_confirm_intervals: 4,
    shutdown_confirm_seconds: 60,
    shutdown_fail_heartbeats: 10,
  }
  const shutdown = (overrides: Partial<CommandStatusItem> = {}) =>
    item({
      name: 'shutdown-now',
      state: 'received',
      delivered_at: '2026-01-01T00:00:01Z',
      received_at: '2026-01-01T00:00:02Z',
      ...overrides,
    })
  const open = () => fireEvent.click(screen.getByRole('button', { name: 'How the result is determined' }))

  afterEach(() => vi.useRealTimers())

  it('explains the pending result with progress and the numbers from the response', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:00:40Z'))
    render(<CommandStatusList items={[shutdown()]} heartbeat={heartbeat} />)

    open()

    const text = screen.getByRole('note').textContent
    expect(text).toContain('So far 2 of 4 heartbeat intervals')
    expect(text).toContain('no heartbeat arrived for 4 heartbeat intervals (15 s each, 1 min in total)')
    expect(text).toContain('still sends heartbeats 10 heartbeats after')
  })

  it('uses other numbers when the response has other numbers', () => {
    render(
      <CommandStatusList
        items={[shutdown({ state: 'success', complete: true, result_at: '2026-01-01T00:01:00Z' })]}
        heartbeat={{ ...heartbeat, heartbeat_interval_s: 30, shutdown_confirm_intervals: 6, shutdown_confirm_seconds: 180, shutdown_fail_heartbeats: 7 }}
      />,
    )

    open()

    const text = screen.getByRole('note').textContent
    expect(text).toContain('counted as successful')
    expect(text).toContain('6 heartbeat intervals (30 s each, 3 min in total)')
    expect(text).toContain('7 heartbeats after')
  })

  it('explains a fixed time span without heartbeat intervals', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:00:40Z'))
    render(
      <CommandStatusList
        items={[shutdown()]}
        heartbeat={{ ...heartbeat, shutdown_confirm_mode: 'seconds', shutdown_confirm_intervals: 6, shutdown_confirm_seconds: 90 }}
      />,
    )

    open()

    const text = screen.getByRole('note').textContent
    expect(text).toContain('So far 40 s of 1 min 30 s have passed')
    expect(text).toContain('no heartbeat arrived for 1 min 30 s after the device acknowledged')
    expect(text).not.toContain('heartbeat intervals')
    expect(text).toContain('still sends heartbeats 10 heartbeats after')
  })

  it('explains a failed shutdown', () => {
    render(
      <CommandStatusList
        items={[shutdown({ state: 'failed', complete: true, result_at: '2026-01-01T00:10:00Z' })]}
        heartbeat={heartbeat}
      />,
    )

    open()

    expect(screen.getByRole('note').textContent).toContain('shutdown counted as failed')
  })

  it('shows a placeholder instead of a non-finite number', () => {
    render(
      <CommandStatusList
        items={[shutdown({ state: 'failed', complete: true, result_at: '2026-01-01T00:10:00Z' })]}
        heartbeat={{ ...heartbeat, shutdown_fail_heartbeats: Number.NaN }}
      />,
    )

    open()

    expect(screen.getByRole('note').textContent).not.toContain('NaN')
  })

  it('is only offered on the result step of a shutdown-now', () => {
    render(
      <CommandStatusList
        items={[
          item({ command_id: 1, name: 'reboot-now', state: 'received' }),
          item({ command_id: 2, name: 'shutdown-now', kind: 'config' }),
        ]}
        heartbeat={heartbeat}
      />,
    )

    expect(screen.queryByRole('button', { name: 'How the result is determined' })).not.toBeInTheDocument()
  })

  it('is not offered without the heartbeat numbers', () => {
    render(<CommandStatusList items={[shutdown()]} />)

    expect(screen.queryByRole('button', { name: 'How the result is determined' })).not.toBeInTheDocument()
  })
})
