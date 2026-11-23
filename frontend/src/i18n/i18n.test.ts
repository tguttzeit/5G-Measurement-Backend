import { afterEach, describe, expect, it, vi } from 'vitest'
import de from './de.json'
import en from './en.json'
import { detectLanguage, LANGUAGE_KEY } from './index'

function flattenKeys(value: unknown, prefix = ''): string[] {
  if (value === null || typeof value !== 'object') return [prefix]
  return Object.entries(value).flatMap(([key, child]) =>
    flattenKeys(child, prefix ? `${prefix}.${key}` : key),
  )
}

// i18next resolves plural forms via suffixes whose set depends on the language; en and de both use
// exactly `_one` and `_other`, so their plural keys must match one to one as well.
describe('resource files', () => {
  it('en.json and de.json have identical key sets', () => {
    expect(flattenKeys(de).sort()).toEqual(flattenKeys(en).sort())
  })

  it('has no empty translations', () => {
    for (const resource of [en, de]) {
      for (const key of flattenKeys(resource)) {
        const value = key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], resource)
        expect(value, key).not.toBe('')
      }
    }
  })

  it('uses the same interpolation placeholders in both languages', () => {
    const placeholders = (text: string) => [...text.matchAll(/{{\s*(\w+)\s*}}|<(\w+)\/>/g)].map((m) => m[1] ?? m[2]).sort()
    for (const key of flattenKeys(en)) {
      const lookup = (resource: unknown) =>
        key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], resource) as string
      const enPlaceholders = placeholders(lookup(en))
      const dePlaceholders = placeholders(lookup(de))
      // A plural form may leave out {{count}} (e.g. "one" written out), but nothing else may differ.
      const strip = (list: string[]) => list.filter((name) => name !== 'count')
      expect(strip(dePlaceholders), key).toEqual(strip(enPlaceholders))
    }
  })
})

describe('detectLanguage', () => {
  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('prefers a stored supported language over the browser language', () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('en-US')
    localStorage.setItem(LANGUAGE_KEY, 'de')
    expect(detectLanguage()).toBe('de')
  })

  it('falls back to German for German browser locales', () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('de-AT')
    expect(detectLanguage()).toBe('de')
  })

  it('falls back to English for every other browser locale', () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('fr-FR')
    expect(detectLanguage()).toBe('en')
  })

  it.each(['fr', '<script>', '', 'DE', 'de ', '__proto__'])('ignores the unsupported stored value %j', (stored) => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('en-US')
    localStorage.setItem(LANGUAGE_KEY, stored)
    expect(detectLanguage()).toBe('en')
  })

  it('does not throw when localStorage is unavailable', () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('de-DE')
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(detectLanguage()).toBe('de')
  })
})
