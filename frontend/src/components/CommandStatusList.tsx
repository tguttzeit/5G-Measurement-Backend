import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import type {
  CommandState,
  CommandStatusItem,
  CommandStatusResponse,
  ShutdownConfirmMode,
} from '../api/commands'
import { commandLabel } from '../lib/commandLabel'
import { configFieldLabel, formatConfigDetail } from '../lib/configOverrides'
import { EMPTY_PLACEHOLDER } from '../lib/formatDateTime'
import { formatDuration } from '../lib/formatDuration'
import { useNow } from '../lib/useNow'
import { Timestamp } from './Timestamp'
import { InfoPopover } from './ui'
import './CommandStatusList.css'

type StepTone = 'done' | 'current' | 'upcoming' | 'danger'

interface Step {
  key: string
  label: string
  at: string | null
  tone: StepTone
  // 0..1, only for a step that is being counted up to (a shutdown-now going silent).
  progress?: number
}

// `elapsed` and `required` count heartbeat intervals in `intervals` mode and seconds in `seconds`
// mode.
export interface ShutdownProgress {
  mode: ShutdownConfirmMode
  elapsed: number
  required: number
}

const SHUTDOWN = 'shutdown-now'

// A shutdown-now is never acked as a success - the device is off - so its result is inferred
// from the device going silent, which the backend confirms once it has been quiet long enough.
function isAwaitingShutdown(item: CommandStatusItem): boolean {
  return item.name === SHUTDOWN && item.state === 'received'
}

const stateLabel = (state: CommandState) => i18n.t(`commandStatus:state.${state}`)

const RESULT_STATES: CommandState[] = ['success', 'failed', 'not_applicable']

export function commandStateLabel(item: CommandStatusItem): string {
  return isAwaitingShutdown(item) ? i18n.t('commandStatus:awaitingOffline') : stateLabel(item.state)
}

// queued -> delivered -> received -> result for commands (reboot-now's "received" is not the end),
// queued -> delivered -> applied for a config override, which has no "received" at all - its result
// is the device reporting the new value. A shutdown-now's result step is the device going offline.
export function buildSteps(item: CommandStatusItem, shutdown?: ShutdownProgress): Step[] {
  const isConfig = item.kind === 'config'
  const isShutdown = item.name === SHUTDOWN
  // For a shutdown-now the result is whether the device went offline: success means it did, a
  // failure means it was still sending heartbeats after acknowledging.
  const t = (key: string, options?: Record<string, unknown>) => i18n.t(`commandStatus:${key}`, options)
  const tTime = i18n.getFixedT(null, 'time')
  const resultLabel =
    isShutdown && item.state === 'success'
      ? t('step.offline')
      : isShutdown && item.state === 'failed'
        ? t('step.stillOnline')
        : RESULT_STATES.includes(item.state)
          ? stateLabel(item.state)
          : isConfig
            ? t('step.applied')
            : isShutdown
              ? t('step.offline')
              : t('step.result')
  const planned: Omit<Step, 'tone'>[] = [
    { key: 'queued', label: t('step.queued'), at: item.queued_at },
    { key: 'delivered', label: t('step.sent'), at: item.delivered_at },
  ]
  if (!isConfig) planned.push({ key: 'received', label: t('step.received'), at: item.received_at })
  planned.push({
    key: 'result',
    label: isConfig && item.state === 'success' ? t('step.applied') : resultLabel,
    at: item.result_at,
  })

  const reached = (step: Omit<Step, 'tone'>) =>
    step.key === 'result' ? item.result_at !== null : step.at !== null
  // A step is done if it, or any later one, was reached - a missing timestamp in the middle
  // (e.g. a command queued before delivery was logged) must not leave a gap in the line.
  const lastReached = planned.reduce((last, step, i) => (reached(step) ? i : last), -1)
  const resultIsBad = item.state === 'failed' || item.state === 'not_applicable'

  const steps: Step[] = planned.map((step, i) => ({
    ...step,
    tone:
      step.key === 'result' && resultIsBad && i <= lastReached
        ? 'danger'
        : i <= lastReached
          ? 'done'
          : i === lastReached + 1 && !item.complete
            ? 'current'
            : 'upcoming',
  }))

  if (isAwaitingShutdown(item) && shutdown) {
    const elapsed = Math.min(shutdown.elapsed, shutdown.required)
    steps[steps.length - 1] = {
      key: 'result',
      label:
        shutdown.mode === 'seconds'
          ? t('step.offlineProgressTime', {
              elapsed: formatDuration(elapsed, tTime),
              required: formatDuration(shutdown.required, tTime),
            })
          : t('step.offlineProgress', { missed: elapsed, required: shutdown.required }),
      at: null,
      tone: 'current',
      progress: elapsed / shutdown.required,
    }
  }

  // Promotion makes the override the device's new baseline; the device never reports it back,
  // so this is where such an override's timeline ends rather than at "Applied".
  if (item.state === 'promoted') {
    return [
      ...steps.slice(0, lastReached + 1),
      { key: 'promoted', label: stateLabel('promoted'), at: item.promoted_at, tone: 'done' },
    ]
  }
  if (item.state === 'removed' || item.state === 'expired') {
    const end =
      item.state === 'removed' ? item.removed_at : (item.expired_at ?? item.expires_at)
    return [
      ...steps.slice(0, lastReached + 1),
      { key: item.state, label: stateLabel(item.state), at: end, tone: 'danger' },
    ]
  }
  return steps
}

function isToday(iso: string): boolean {
  return new Date(iso).toDateString() === new Date().toDateString()
}

// Commands and config fields have display names; an unknown name is shown as it is.
function itemLabel(item: CommandStatusItem): string {
  return item.kind === 'command' ? commandLabel(item.name) : configFieldLabel(item.name)
}

// A queued override's detail carries its value as rendered by the server.
function itemDetail(item: CommandStatusItem): string {
  return item.kind === 'config' ? formatConfigDetail(item.detail) : (item.detail ?? '')
}

const count = (value: number) => (Number.isFinite(value) ? String(value) : EMPTY_PLACEHOLDER)

// Explains the inferred result of a shutdown-now with the thresholds the backend actually uses.
function ShutdownResultInfo({
  item,
  rule,
  shutdown,
}: {
  item: CommandStatusItem
  rule: ShutdownRule
  shutdown?: ShutdownProgress
}) {
  const { t } = useTranslation('commandStatus')
  const { t: tTime } = useTranslation('time')
  const inSeconds = rule.shutdown_confirm_mode === 'seconds'
  const total = formatDuration(rule.shutdown_confirm_seconds, tTime)
  const intro =
    item.state === 'success'
      ? t('shutdownInfo.intro.success')
      : item.state === 'failed'
        ? t('shutdownInfo.intro.failed')
        : shutdown && inSeconds
          ? t('shutdownInfo.intro.pendingProgressTime', {
              elapsed: formatDuration(Math.min(shutdown.elapsed, shutdown.required), tTime),
              required: total,
            })
          : shutdown
            ? t('shutdownInfo.intro.pendingProgress', {
                missed: count(Math.min(shutdown.elapsed, shutdown.required)),
                required: count(shutdown.required),
              })
            : t('shutdownInfo.intro.pending')
  const failHeartbeats = count(rule.shutdown_fail_heartbeats)
  return (
    <InfoPopover label={t('shutdownInfo.label')}>
      {intro}{' '}
      {inSeconds
        ? t('shutdownInfo.ruleTime', { total, failHeartbeats })
        : t('shutdownInfo.rule', {
            required: count(rule.shutdown_confirm_intervals),
            interval: formatDuration(rule.heartbeat_interval_s, tTime),
            total,
            failHeartbeats,
          })}
    </InfoPopover>
  )
}

function CommandTimeline({
  item,
  shutdown,
  rule,
}: {
  item: CommandStatusItem
  shutdown?: ShutdownProgress
  rule?: ShutdownRule
}) {
  const { t } = useTranslation('commandStatus')
  const steps = buildSteps(item, shutdown)
  return (
    <ol className="command-timeline" aria-label={t('progressOf', { name: itemLabel(item) })}>
      {steps.map((step, i) => (
        <li
          key={step.key}
          className={[
            'command-timeline__step',
            `command-timeline__step--${step.tone}`,
            step.progress !== undefined && 'command-timeline__step--progress',
            // The connector to the next step is only filled once that step was reached too.
            ['done', 'danger'].includes(steps[i + 1]?.tone) && 'command-timeline__step--linked',
          ]
            .filter(Boolean)
            .join(' ')}
          style={step.progress !== undefined ? ({ '--progress': step.progress } as React.CSSProperties) : undefined}
          aria-current={step.tone === 'current' ? 'step' : undefined}
        >
          <span className="command-timeline__label">
            {step.label}
            {step.key === 'result' && item.name === SHUTDOWN && item.kind === 'command' && rule && (
              <ShutdownResultInfo item={item} rule={rule} shutdown={shutdown} />
            )}
          </span>
          <span className="command-timeline__time">
            {step.at && <Timestamp value={step.at} part={isToday(step.at) ? 'time' : 'dateTime'} />}
          </span>
        </li>
      ))}
    </ol>
  )
}

type ShutdownRule = Pick<
  CommandStatusResponse,
  | 'heartbeat_interval_s'
  | 'shutdown_confirm_mode'
  | 'shutdown_confirm_intervals'
  | 'shutdown_confirm_seconds'
  | 'shutdown_fail_heartbeats'
>

type HeartbeatInfo = ShutdownRule & Pick<CommandStatusResponse, 'last_heartbeat_at'>

export function CommandStatusList({
  items: allItems,
  names,
  heartbeat,
  onShutdownDue,
}: {
  items: CommandStatusItem[]
  // Only show items with one of these command names; a pure display filter.
  names?: string[]
  heartbeat?: HeartbeatInfo
  // Called once the intervals are used up, so the page can fetch the (now confirmed) result.
  onShutdownDue?: () => void
}) {
  const { t } = useTranslation('commandStatus')
  const items = names ? allItems.filter((item) => names.includes(item.name)) : allItems
  const awaiting = items.some(isAwaitingShutdown) && !!heartbeat?.last_heartbeat_at
  const now = useNow(awaiting)

  const silentS =
    awaiting && heartbeat?.last_heartbeat_at
      ? Math.max(0, (now - new Date(heartbeat.last_heartbeat_at).getTime()) / 1000)
      : undefined
  const shutdown: ShutdownProgress | undefined =
    heartbeat && silentS !== undefined
      ? heartbeat.shutdown_confirm_mode === 'seconds'
        ? {
            mode: 'seconds',
            elapsed: Math.floor(silentS),
            required: heartbeat.shutdown_confirm_seconds,
          }
        : {
            mode: 'intervals',
            elapsed: Math.floor(silentS / heartbeat.heartbeat_interval_s),
            required: heartbeat.shutdown_confirm_intervals,
          }
      : undefined
  const due = !!shutdown && shutdown.elapsed >= shutdown.required

  useEffect(() => {
    if (due) onShutdownDue?.()
    // Only on the transition to due; the callback is the page's refresh and changes every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [due])

  return (
    <ul className="command-status-list">
      {items.map((item) => (
        <li key={item.command_id} className="command-status">
          <div className="command-status__header">
            <span className="command-status__name" title={item.name}>
              {itemLabel(item)}
              {itemDetail(item) ? ` ${itemDetail(item)}` : ''}
            </span>
            <span className="command-status__meta">
              {item.kind === 'config' ? t('kind.config') : t('kind.command')} #{item.command_id}
            </span>
            <span className={`command-status__state command-status__state--${item.state}`}>
              {commandStateLabel(item)}
            </span>
          </div>
          <CommandTimeline item={item} shutdown={shutdown} rule={heartbeat} />
          {item.error && <p className="command-status__error">{item.error}</p>}
        </li>
      ))}
    </ul>
  )
}
