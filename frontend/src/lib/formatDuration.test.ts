import { describe, expect, it } from 'vitest'
import i18n from '../i18n'
import { EMPTY_PLACEHOLDER } from './formatDateTime'
import { formatDuration, formatRelativeTime, splitDuration } from './formatDuration'

const MINUTE = 60
const HOUR = 3600
const DAY = 86400
const MONTH = 30 * DAY
const YEAR = 365 * DAY

const t = (key: string, options?: Record<string, unknown>) => i18n.t(key, { ns: 'time', ...options })

describe('splitDuration', () => {
  it.each([
    [0, [{ unit: 'second', value: 0 }]],
    [59, [{ unit: 'second', value: 59 }]],
    [60, [{ unit: 'minute', value: 1 }]],
    [61, [{ unit: 'minute', value: 1 }, { unit: 'second', value: 1 }]],
    [125, [{ unit: 'minute', value: 2 }, { unit: 'second', value: 5 }]],
    [HOUR - 1, [{ unit: 'minute', value: 59 }, { unit: 'second', value: 59 }]],
    [HOUR, [{ unit: 'hour', value: 1 }]],
    [2 * HOUR + 3 * MINUTE + 9, [{ unit: 'hour', value: 2 }, { unit: 'minute', value: 3 }]],
    [DAY - 1, [{ unit: 'hour', value: 23 }, { unit: 'minute', value: 59 }]],
    [DAY, [{ unit: 'day', value: 1 }]],
    [3 * DAY + 4 * HOUR + 5 * MINUTE, [{ unit: 'day', value: 3 }, { unit: 'hour', value: 4 }]],
    [MONTH - 1, [{ unit: 'day', value: 29 }, { unit: 'hour', value: 23 }]],
    [MONTH, [{ unit: 'month', value: 1 }]],
    [2 * MONTH + DAY + HOUR, [{ unit: 'month', value: 2 }, { unit: 'day', value: 1 }]],
    [YEAR - 1, [{ unit: 'month', value: 12 }, { unit: 'day', value: 4 }]],
    [YEAR, [{ unit: 'year', value: 1 }]],
    [YEAR + 2 * MONTH + DAY, [{ unit: 'year', value: 1 }, { unit: 'month', value: 2 }]],
  ])('splits %i s', (seconds, expected) => {
    expect(splitDuration(seconds)).toEqual(expected)
  })

  it('drops the smaller unit instead of rounding up across units', () => {
    expect(splitDuration(MINUTE + 59.9)).toEqual([{ unit: 'minute', value: 1 }, { unit: 'second', value: 59 }])
  })

  it('clamps negative values to zero seconds', () => {
    expect(splitDuration(-5)).toEqual([{ unit: 'second', value: 0 }])
  })

  it.each([Number.NaN, Infinity, -Infinity])('returns nothing for the non-finite value %s', (value) => {
    expect(splitDuration(value)).toEqual([])
  })
})

describe('formatDuration', () => {
  it.each([
    [45, '45 s'],
    [65, '1 min 5 s'],
    [120, '2 min'],
    [2 * HOUR + 3 * MINUTE, '2 h 3 min'],
    [3 * DAY + 4 * HOUR, '3 d 4 h'],
    [2 * MONTH + DAY, '2 mo 1 d'],
    [YEAR + 2 * MONTH, '1 y 2 mo'],
    [-3, '0 s'],
  ])('formats %i s in English as "%s"', (seconds, expected) => {
    expect(formatDuration(seconds, t)).toBe(expected)
  })

  it.each([
    [65, '1 Min. 5 Sek.'],
    [2 * HOUR + 3 * MINUTE, '2 Std. 3 Min.'],
    [3 * DAY + 4 * HOUR, '3 T. 4 Std.'],
    [2 * MONTH + DAY, '2 Mon. 1 T.'],
    [YEAR + 2 * MONTH, '1 J. 2 Mon.'],
  ])('formats %i s in German as "%s"', async (seconds, expected) => {
    await i18n.changeLanguage('de')
    expect(formatDuration(seconds, t)).toBe(expected)
  })

  it.each([Number.NaN, Infinity, null, undefined])('renders the placeholder for %s', (value) => {
    expect(formatDuration(value, t)).toBe(EMPTY_PLACEHOLDER)
  })
})

describe('formatRelativeTime', () => {
  it('formats the time since a past instant', () => {
    expect(formatRelativeTime(1_000_000, 1_065_000, t)).toBe('1 min 5 s ago')
  })

  it('formats in German', async () => {
    await i18n.changeLanguage('de')
    expect(formatRelativeTime(1_000_000, 1_065_000, t)).toBe('vor 1 Min. 5 Sek.')
  })

  it('clamps an instant in the future (clock skew) to 0 s ago', () => {
    expect(formatRelativeTime(2_000_000, 1_000_000, t)).toBe('0 s ago')
  })

  it.each([Number.NaN, Infinity])('renders the placeholder for the invalid instant %s', (value) => {
    expect(formatRelativeTime(value, 1_000_000, t)).toBe(EMPTY_PLACEHOLDER)
    expect(formatRelativeTime(1_000_000, value, t)).toBe(EMPTY_PLACEHOLDER)
  })
})
