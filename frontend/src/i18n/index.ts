import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './en.json'
import de from './de.json'

export const SUPPORTED_LANGUAGES = ['en', 'de'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]

export const DEFAULT_LANGUAGE: Language = 'en'
export const LANGUAGE_KEY = 'language_preference'

export function isSupportedLanguage(value: unknown): value is Language {
  return typeof value === 'string' && (SUPPORTED_LANGUAGES as readonly string[]).includes(value)
}

function readStoredLanguage(): unknown {
  try {
    return localStorage.getItem(LANGUAGE_KEY)
  } catch {
    return null
  }
}

export function storeLanguage(language: Language) {
  try {
    localStorage.setItem(LANGUAGE_KEY, language)
  } catch {
    // Storage can be unavailable (private mode, blocked site data); the choice then lasts one session.
  }
}

export function detectLanguage(): Language {
  const stored = readStoredLanguage()
  if (isSupportedLanguage(stored)) return stored
  const browserLanguage = typeof navigator === 'undefined' ? '' : (navigator.language ?? '')
  return browserLanguage.toLowerCase().startsWith('de') ? 'de' : DEFAULT_LANGUAGE
}

void i18n.use(initReactI18next).init({
  resources: { en, de },
  lng: detectLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  defaultNS: 'common',
  // React already escapes rendered text; escaping here as well would double-encode it.
  interpolation: { escapeValue: false },
  returnNull: false,
})

export default i18n
