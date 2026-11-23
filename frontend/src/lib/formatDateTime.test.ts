import { describe, expect, it } from 'vitest'
import {
  EMPTY_PLACEHOLDER,
  formatDate,
  formatDateTime,
  formatNumber,
  formatTime,
  toIsoString,
  timeZoneLabel,
} from './formatDateTime'

// Fixed local-time constructor arguments keep the expectations independent of the runner's time zone.
const localIso = (y: number, m: number, d: number, h: number, min: number, s: number) =>
  new Date(y, m, d, h, min, s).toISOString()

describe('formatDateTime', () => {
  it('renders English as day/month/year with a 24-hour clock', () => {
    expect(formatDateTime(localIso(2026, 9, 23, 14, 5, 9), 'en')).toBe('23/10/2026, 14:05:09')
  })

  it('renders German with dots and a 24-hour clock', () => {
    expect(formatDateTime(localIso(2026, 9, 23, 14, 5, 9), 'de')).toBe('23.10.2026, 14:05:09')
  })

  it('shows midnight as 00:00:00, not 24:00:00', () => {
    expect(formatDateTime(localIso(2026, 0, 1, 0, 0, 0), 'en')).toBe('01/01/2026, 00:00:00')
    expect(formatDateTime(localIso(2026, 0, 1, 0, 0, 0), 'de')).toBe('01.01.2026, 00:00:00')
  })

  it('keeps wall-clock time across a daylight-saving change', () => {
    expect(formatDateTime(localIso(2026, 2, 29, 12, 30, 0), 'en')).toBe('29/03/2026, 12:30:00')
    expect(formatDateTime(localIso(2026, 9, 25, 12, 30, 0), 'en')).toBe('25/10/2026, 12:30:00')
  })

  it.each([null, undefined, '', 'not a date', '2026-13-45T99:00:00Z'])('returns the placeholder for %s', (value) => {
    expect(formatDateTime(value, 'en')).toBe(EMPTY_PLACEHOLDER)
    expect(formatDateTime(value, 'de')).toBe(EMPTY_PLACEHOLDER)
  })
})

describe('formatTime', () => {
  it('renders only the 24-hour time in both languages', () => {
    expect(formatTime(localIso(2026, 9, 23, 14, 5, 9), 'en')).toBe('14:05:09')
    expect(formatTime(localIso(2026, 9, 23, 14, 5, 9), 'de')).toBe('14:05:09')
  })

  it('returns the placeholder for invalid input', () => {
    expect(formatTime(null, 'en')).toBe(EMPTY_PLACEHOLDER)
    expect(formatTime('garbage', 'de')).toBe(EMPTY_PLACEHOLDER)
  })
})

describe('formatDate', () => {
  it('renders a calendar day per language', () => {
    expect(formatDate('2026-10-23', 'en')).toBe('23/10/2026')
    expect(formatDate('2026-10-23', 'de')).toBe('23.10.2026')
  })

  it('does not shift a date-only value by the time zone', () => {
    expect(formatDate('2026-01-01', 'en')).toBe('01/01/2026')
    expect(formatDate('2026-12-31', 'de')).toBe('31.12.2026')
  })

  it('formats a timestamp as the local calendar day', () => {
    expect(formatDate(localIso(2026, 9, 23, 23, 59, 59), 'en')).toBe('23/10/2026')
  })

  it('returns the placeholder for invalid input', () => {
    expect(formatDate(null, 'en')).toBe(EMPTY_PLACEHOLDER)
    expect(formatDate('2026-02-31x', 'de')).toBe(EMPTY_PLACEHOLDER)
  })
})

describe('formatNumber', () => {
  it('uses the thousands separator of the selected language', () => {
    expect(formatNumber(1234567, 'en')).toBe('1,234,567')
    expect(formatNumber(1234567, 'de')).toBe('1.234.567')
  })

  it('returns the placeholder for non-finite values', () => {
    expect(formatNumber(Number.NaN, 'en')).toBe(EMPTY_PLACEHOLDER)
    expect(formatNumber(null, 'de')).toBe(EMPTY_PLACEHOLDER)
  })
})

describe('toIsoString', () => {
  it('re-serializes a valid timestamp as UTC ISO 8601', () => {
    expect(toIsoString('2026-10-23T14:05:09+02:00')).toBe('2026-10-23T12:05:09.000Z')
  })

  it('returns null for invalid input so raw API text never reaches an attribute', () => {
    expect(toIsoString('<script>alert(1)</script>')).toBeNull()
    expect(toIsoString(null)).toBeNull()
  })
})

describe('timeZoneLabel', () => {
  it('returns a non-empty time zone abbreviation', () => {
    expect(timeZoneLabel('2026-10-23T12:00:00Z', 'en')).not.toBe('')
  })
})
