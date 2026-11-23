import '@testing-library/jest-dom/vitest'
import { beforeEach } from 'vitest'
import i18n, { LANGUAGE_KEY } from '../i18n'

// Every test starts in English with no stored language choice, regardless of the test runner's locale.
beforeEach(async () => {
  localStorage.removeItem(LANGUAGE_KEY)
  await i18n.changeLanguage('en')
})
