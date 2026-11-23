import { describe, expect, it } from 'vitest'
import i18n from '../i18n'
import de from '../i18n/de.json'
import en from '../i18n/en.json'
import { ONE_SHOT_COMMAND_NAMES } from '../api/commands'
import { commandLabel } from './commandLabel'

describe('commandLabel', () => {
  it('returns the English display name for a known command', () => {
    expect(commandLabel('reboot-now')).toBe('Reboot')
    expect(commandLabel('run-gps-fix-test-now')).toBe('Start GPS fix test')
  })

  it('returns the German display name after switching language', async () => {
    await i18n.changeLanguage('de')
    expect(commandLabel('reboot-now')).toBe('Neustart')
    expect(commandLabel('promote-overrides-now')).toBe('Overrides übernehmen')
  })

  it('keeps labelling the legacy Waiting Mode command in the history', async () => {
    await i18n.changeLanguage('en')
    expect(commandLabel('mode-waiting-now')).toBe('Manual mode')
    expect(commandLabel('mode-manual-now')).toBe('Manual mode')
  })

  it('falls back to the raw name for an unknown command', () => {
    expect(commandLabel('brand-new-now')).toBe('brand-new-now')
  })

  it.each(['__proto__', 'constructor', 'toString', 'hasOwnProperty'])(
    'does not resolve the inherited property %s',
    (name) => {
      expect(commandLabel(name)).toBe(name)
    },
  )

  it('uses the given translate function', () => {
    expect(commandLabel('reboot-now', (key) => `<${key}>`)).toBe('<commands:reboot-now>')
  })

  it.each([
    ['en', en],
    ['de', de],
  ])('has a %s translation for every one-shot command', (_language, resource) => {
    for (const name of ONE_SHOT_COMMAND_NAMES) {
      expect((resource.commands as Record<string, string>)[name], name).toBeTruthy()
    }
  })
})
