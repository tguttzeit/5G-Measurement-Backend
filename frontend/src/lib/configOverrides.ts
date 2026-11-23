import i18n from '../i18n'
import type {
  ConfigOverridePayload,
  ConfigOverrideValue,
  ConfigSchemaField,
} from '../api/commands'
import { EMPTY_PLACEHOLDER } from './formatDateTime'

// What the user entered per field: absent or blank = unchanged, `null` = explicitly "not set",
// otherwise the raw text (a number as typed, or the chosen enum / bool option).
export type ConfigInputs = Record<string, string | null>

export type FieldInputError =
  | { code: 'notNumber' }
  | { code: 'notInteger' }
  | { code: 'belowMin' | 'aboveMax'; min: number | null; max: number | null }
  | { code: 'notAllowed' }

export type SoftWarning = 'homeIncomplete'

const HOME_LATITUDE = 'movement_gate_home_latitude'
const HOME_LONGITUDE = 'movement_gate_home_longitude'

// Field keys come from the server; only plain snake_case names are used to build translation
// keys, so a key can never address another resource or a different namespace.
const SAFE_FIELD_KEY = /^[a-z0-9_]+$/

export function isUnchanged(input: string | null | undefined): boolean {
  return input === undefined || (input !== null && input.trim() === '')
}

function parseValue(field: ConfigSchemaField, input: string): ConfigOverrideValue | undefined {
  const text = input.trim()
  switch (field.type) {
    case 'float':
    case 'int': {
      if (text === '') return undefined
      const number = Number(text)
      if (!Number.isFinite(number)) return undefined
      if (field.type === 'int' && !Number.isInteger(number)) return undefined
      return number
    }
    case 'enum':
      return field.values?.includes(text) ? text : undefined
    case 'bool':
      return text === 'true' ? true : text === 'false' ? false : undefined
    default:
      return undefined
  }
}

function rangeError(field: ConfigSchemaField, number: number): FieldInputError | null {
  const { min, max } = field
  if (min !== null && number < min) return { code: 'belowMin', min, max }
  if (max !== null && number > max) return { code: 'aboveMax', min, max }
  return null
}

// Convenience validation mirroring the server's specification; the server stays authoritative.
export function fieldInputError(
  field: ConfigSchemaField,
  input: string | null | undefined,
): FieldInputError | null {
  if (input === undefined || isUnchanged(input)) return null
  if (input === null) return field.nullable ? null : { code: 'notAllowed' }
  if (field.type === 'float' || field.type === 'int') {
    const number = Number(input.trim())
    if (!Number.isFinite(number)) return { code: 'notNumber' }
    if (field.type === 'int' && !Number.isInteger(number)) return { code: 'notInteger' }
    return rangeError(field, number)
  }
  return parseValue(field, input) === undefined ? { code: 'notAllowed' } : null
}

// Only changed fields with a valid value make it into the payload.
export function buildPayload(fields: ConfigSchemaField[], inputs: ConfigInputs): ConfigOverridePayload {
  const payload: ConfigOverridePayload = {}
  for (const field of fields) {
    const input = inputs[field.key]
    if (input === undefined || isUnchanged(input) || fieldInputError(field, input) !== null) continue
    payload[field.key] = input === null ? null : (parseValue(field, input) as ConfigOverrideValue)
  }
  return payload
}

export function riskyEntries(
  fields: ConfigSchemaField[],
  payload: ConfigOverridePayload,
): [string, ConfigOverrideValue][] {
  const risky = new Set(fields.filter((f) => f.requires_confirmation).map((f) => f.key))
  return Object.entries(payload).filter(([key]) => risky.has(key))
}

// Non-blocking hints; the device re-validates cross-field rules when it loads the config.
export function softWarnings(payload: ConfigOverridePayload): SoftWarning[] {
  const warnings: SoftWarning[] = []
  const latitudeChanged = HOME_LATITUDE in payload
  const longitudeChanged = HOME_LONGITUDE in payload
  const oneSideOnly = latitudeChanged !== longitudeChanged
  const oneSideNull =
    latitudeChanged && longitudeChanged && (payload[HOME_LATITUDE] === null) !== (payload[HOME_LONGITUDE] === null)
  if (oneSideOnly || oneSideNull) warnings.push('homeIncomplete')
  return warnings
}

export type FieldTextPart = 'label' | 'description' | 'dependency'

export function configFieldText(key: string, part: FieldTextPart): string | null {
  if (!SAFE_FIELD_KEY.test(key)) return null
  const id = `remoteConfiguration:fields.${key}.${part}`
  return i18n.exists(id) ? i18n.t(id) : null
}

// Falls back to the raw key for a field this client has no translation for.
export function configFieldLabel(key: string): string {
  return configFieldText(key, 'label') ?? key
}

export function configGroupLabel(id: string): string {
  if (!SAFE_FIELD_KEY.test(id)) return id
  return i18n.t(`remoteConfiguration:groups.${id}`, { defaultValue: id })
}

// Always text: an API-provided string is never treated as markup.
export function formatConfigValue(value: ConfigOverrideValue | undefined): string {
  if (value === undefined) return EMPTY_PLACEHOLDER
  if (value === null) return i18n.t('remoteConfiguration:values.notSet')
  if (typeof value === 'boolean') return i18n.t(`remoteConfiguration:values.${value}`)
  return String(value)
}

// A queued override's detail is rendered by the server as "= <python value>".
const QUEUED_VALUE_DETAIL = /^= (.*)$/s

export function formatConfigDetail(detail: string | null): string {
  if (!detail) return ''
  const match = QUEUED_VALUE_DETAIL.exec(detail)
  if (!match) return detail
  const raw = match[1]
  if (raw === 'None') return `= ${formatConfigValue(null)}`
  if (raw === 'True') return `= ${formatConfigValue(true)}`
  if (raw === 'False') return `= ${formatConfigValue(false)}`
  return detail
}
