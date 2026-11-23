import { describe, expect, it } from 'vitest'
import type { ConfigSchemaField } from '../api/commands'
import {
  buildPayload,
  fieldInputError,
  formatConfigDetail,
  formatConfigValue,
  riskyEntries,
  softWarnings,
} from './configOverrides'

function field(overrides: Partial<ConfigSchemaField> & { key: string }): ConfigSchemaField {
  return {
    type: 'float',
    min: null,
    max: null,
    values: null,
    nullable: false,
    unit: null,
    requires_confirmation: false,
    no_effect_yet: false,
    ...overrides,
  }
}

const float = field({ key: 'idle_threshold_s', min: 1, max: 86400, unit: 's' })
const int = field({ key: 'gnss_receiver_retries', type: 'int', min: 0, max: 20 })
const enumField = field({ key: 'modem_mode', type: 'enum', values: ['serving_cell', 'sa_scan'] })
const boolField = field({ key: 'display_enabled', type: 'bool' })
const nullable = field({ key: 'movement_gate_home_latitude', min: -90, max: 90, nullable: true })

describe('fieldInputError', () => {
  it('treats an untouched field as unchanged, not as an error', () => {
    expect(fieldInputError(float, undefined)).toBeNull()
    expect(fieldInputError(float, '')).toBeNull()
    expect(fieldInputError(float, '   ')).toBeNull()
  })

  it('checks a float against its range, bounds included', () => {
    expect(fieldInputError(float, '1')).toBeNull()
    expect(fieldInputError(float, '86400')).toBeNull()
    expect(fieldInputError(float, '0.5')).toEqual({ code: 'belowMin', min: 1, max: 86400 })
    expect(fieldInputError(float, '86401')).toEqual({ code: 'aboveMax', min: 1, max: 86400 })
  })

  it('accepts decimals for float but only whole numbers for int', () => {
    expect(fieldInputError(float, '2.5')).toBeNull()
    expect(fieldInputError(int, '2')).toBeNull()
    expect(fieldInputError(int, '2.5')).toEqual({ code: 'notInteger' })
  })

  it('rejects text and non-finite numbers', () => {
    expect(fieldInputError(float, 'abc')).toEqual({ code: 'notNumber' })
    expect(fieldInputError(float, 'Infinity')).toEqual({ code: 'notNumber' })
  })

  it('accepts only the listed enum values', () => {
    expect(fieldInputError(enumField, 'sa_scan')).toBeNull()
    expect(fieldInputError(enumField, 'anything')).toEqual({ code: 'notAllowed' })
  })

  it('accepts only true or false for a bool', () => {
    expect(fieldInputError(boolField, 'true')).toBeNull()
    expect(fieldInputError(boolField, 'false')).toBeNull()
    expect(fieldInputError(boolField, 'yes')).toEqual({ code: 'notAllowed' })
  })

  it('accepts an explicit "not set" only for a nullable field', () => {
    expect(fieldInputError(nullable, null)).toBeNull()
    expect(fieldInputError(float, null)).toEqual({ code: 'notAllowed' })
  })

  it('never accepts a value for a field type it does not know', () => {
    expect(fieldInputError(field({ key: 'x', type: 'matrix' }), '1')).toEqual({ code: 'notAllowed' })
  })
})

describe('buildPayload', () => {
  const fields = [float, int, enumField, boolField, nullable]

  it('sends nothing for untouched fields', () => {
    expect(buildPayload(fields, {})).toEqual({})
    expect(buildPayload(fields, { idle_threshold_s: '' })).toEqual({})
  })

  it('converts each value to its type', () => {
    expect(
      buildPayload(fields, {
        idle_threshold_s: '60',
        gnss_receiver_retries: '3',
        modem_mode: 'sa_scan',
        display_enabled: 'false',
        movement_gate_home_latitude: '48.5',
      }),
    ).toEqual({
      idle_threshold_s: 60,
      gnss_receiver_retries: 3,
      modem_mode: 'sa_scan',
      display_enabled: false,
      movement_gate_home_latitude: 48.5,
    })
  })

  it('sends an explicit null for "not set", which differs from leaving the field out', () => {
    const payload = buildPayload(fields, { movement_gate_home_latitude: null })
    expect(payload).toEqual({ movement_gate_home_latitude: null })
    expect('movement_gate_home_latitude' in payload).toBe(true)
    expect('movement_gate_home_latitude' in buildPayload(fields, {})).toBe(false)
  })

  it('leaves out invalid values and fields the schema does not list', () => {
    expect(buildPayload(fields, { idle_threshold_s: '0', unknown_field: '5', modem_mode: 'x' })).toEqual({})
  })
})

describe('riskyEntries', () => {
  it('returns only the changed fields that require confirmation', () => {
    const risky = field({ key: 'gnss_receiver_retries', type: 'int', min: 0, max: 20, requires_confirmation: true })
    const fields = [float, risky]
    expect(riskyEntries(fields, { idle_threshold_s: 60 })).toEqual([])
    expect(riskyEntries(fields, { idle_threshold_s: 60, gnss_receiver_retries: 5 })).toEqual([
      ['gnss_receiver_retries', 5],
    ])
  })
})

describe('softWarnings', () => {
  it('warns when only one of the home coordinates is changed', () => {
    expect(softWarnings({ movement_gate_home_latitude: 48.1 })).toEqual(['homeIncomplete'])
    expect(softWarnings({ movement_gate_home_longitude: null })).toEqual(['homeIncomplete'])
  })

  it('warns when one home coordinate is null and the other is not', () => {
    expect(softWarnings({ movement_gate_home_latitude: null, movement_gate_home_longitude: 11 })).toEqual([
      'homeIncomplete',
    ])
  })

  it('does not warn when both coordinates are set, or both are null', () => {
    expect(softWarnings({ movement_gate_home_latitude: 48, movement_gate_home_longitude: 11 })).toEqual([])
    expect(softWarnings({ movement_gate_home_latitude: null, movement_gate_home_longitude: null })).toEqual([])
  })

})

describe('formatConfigValue', () => {
  it('renders every value type as text', () => {
    expect(formatConfigValue(15)).toBe('15')
    expect(formatConfigValue('distance')).toBe('distance')
    expect(formatConfigValue(true)).toBe('true')
    expect(formatConfigValue(false)).toBe('false')
    expect(formatConfigValue(null)).toBe('not set')
    expect(formatConfigValue(undefined)).toBe('—')
  })

  it('does not interpret markup in strings', () => {
    expect(formatConfigValue('<b>x</b>')).toBe('<b>x</b>')
  })
})

describe('formatConfigDetail', () => {
  it('translates the server-rendered value of a queued override', () => {
    expect(formatConfigDetail('= 15')).toBe('= 15')
    expect(formatConfigDetail('= None')).toBe('= not set')
    expect(formatConfigDetail('= True')).toBe('= true')
    expect(formatConfigDetail('= False')).toBe('= false')
    expect(formatConfigDetail('= sa_scan')).toBe('= sa_scan')
  })

  it('passes a detail in any other shape through unchanged', () => {
    expect(formatConfigDetail('modem not responding')).toBe('modem not responding')
    expect(formatConfigDetail(null)).toBe('')
  })
})
