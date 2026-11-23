import { EMPTY_PLACEHOLDER } from './formatDateTime'

// The display is approximate by design: a month is always 30 days and a year always 365 days, so
// there is no calendar arithmetic and the result does not depend on the current date or time zone.
const UNITS = [
  { unit: 'year', seconds: 365 * 86400 },
  { unit: 'month', seconds: 30 * 86400 },
  { unit: 'day', seconds: 86400 },
  { unit: 'hour', seconds: 3600 },
  { unit: 'minute', seconds: 60 },
  { unit: 'second', seconds: 1 },
] as const

export type DurationUnit = (typeof UNITS)[number]['unit']
export interface DurationPart {
  unit: DurationUnit
  value: number
}

type Translate = (key: string, options?: Record<string, unknown>) => string

// The largest unit that fits plus the next smaller one (left out when zero). The remainder below
// that is dropped, never rounded up. Negative values (clock skew) clamp to 0 s.
export function splitDuration(seconds: number): DurationPart[] {
  if (!Number.isFinite(seconds)) return []

  const total = Math.max(0, Math.floor(seconds))
  const firstFitting = UNITS.findIndex((candidate) => total >= candidate.seconds)
  const leadingIndex = firstFitting === -1 ? UNITS.length - 1 : firstFitting
  const leading = UNITS[leadingIndex]
  const leadingValue = Math.floor(total / leading.seconds)
  const parts: DurationPart[] = [{ unit: leading.unit, value: leadingValue }]

  const next = UNITS[leadingIndex + 1]
  if (next) {
    const nextValue = Math.floor((total % leading.seconds) / next.seconds)
    if (nextValue > 0) parts.push({ unit: next.unit, value: nextValue })
  }
  return parts
}

export function formatDuration(seconds: number | null | undefined, t: Translate): string {
  if (seconds == null) return EMPTY_PLACEHOLDER
  const parts = splitDuration(seconds)
  if (parts.length === 0) return EMPTY_PLACEHOLDER
  return parts.map(({ unit, value }) => `${value} ${t(`unit.${unit}`)}`).join(' ')
}

export function formatRelativeTime(sinceMs: number, nowMs: number, t: Translate): string {
  if (!Number.isFinite(sinceMs) || !Number.isFinite(nowMs)) return EMPTY_PLACEHOLDER
  return t('ago', { duration: formatDuration((nowMs - sinceMs) / 1000, t) })
}
