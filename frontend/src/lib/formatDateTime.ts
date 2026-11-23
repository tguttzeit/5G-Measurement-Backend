import type { Language } from '../i18n'

export const EMPTY_PLACEHOLDER = '—'

// en-GB rather than en-US: day-first and a 24-hour clock avoid month/day and AM/PM confusion.
const LOCALES: Record<Language, string> = { en: 'en-GB', de: 'de-DE' }

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

const DATE_PARTS: Intl.DateTimeFormatOptions = { day: '2-digit', month: '2-digit', year: 'numeric' }
const TIME_PARTS: Intl.DateTimeFormatOptions = {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
}

type Input = string | null | undefined

function parse(value: Input): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function format(value: Input, language: Language, options: Intl.DateTimeFormatOptions): string {
  const date = parse(value)
  return date ? new Intl.DateTimeFormat(LOCALES[language], options).format(date) : EMPTY_PLACEHOLDER
}

export function formatDateTime(value: Input, language: Language): string {
  return format(value, language, { ...DATE_PARTS, ...TIME_PARTS })
}

export function formatTime(value: Input, language: Language): string {
  return format(value, language, TIME_PARTS)
}

// A date-only value ("2026-10-23") names a calendar day, not an instant, so it is shown as is
// instead of being moved by the browser's time zone.
export function formatDate(value: Input, language: Language): string {
  const options = value && DATE_ONLY.test(value) ? { ...DATE_PARTS, timeZone: 'UTC' } : DATE_PARTS
  return format(value, language, options)
}

export function formatNumber(value: number | null | undefined, language: Language): string {
  if (value == null || !Number.isFinite(value)) return EMPTY_PLACEHOLDER
  return new Intl.NumberFormat(LOCALES[language]).format(value)
}

// Only a successfully parsed value is re-serialized, so raw API text never ends up in an attribute.
export function toIsoString(value: Input): string | null {
  return parse(value)?.toISOString() ?? null
}

export function timeZoneLabel(value: Input, language: Language): string {
  const date = parse(value)
  if (!date) return ''
  const parts = new Intl.DateTimeFormat(LOCALES[language], { timeZoneName: 'short' }).formatToParts(date)
  return parts.find((part) => part.type === 'timeZoneName')?.value ?? ''
}
