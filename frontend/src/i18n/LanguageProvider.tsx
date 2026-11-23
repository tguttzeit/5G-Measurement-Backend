import { createContext, useCallback, useContext, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { DEFAULT_LANGUAGE, isSupportedLanguage, storeLanguage, type Language } from './index'

interface LanguageContextType {
  language: Language
  setLanguage: (language: Language) => void
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined)

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const { i18n } = useTranslation()
  const language = isSupportedLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE

  useEffect(() => {
    document.documentElement.lang = language
  }, [language])

  const setLanguage = useCallback(
    (next: Language) => {
      if (!isSupportedLanguage(next)) return
      void i18n.changeLanguage(next)
      storeLanguage(next)
    },
    [i18n],
  )

  return <LanguageContext.Provider value={{ language, setLanguage }}>{children}</LanguageContext.Provider>
}

export function useLanguage() {
  const context = useContext(LanguageContext)
  if (!context) throw new Error('useLanguage must be used within a LanguageProvider')
  return context
}
