import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { DEFAULT_LANGUAGE, isSupportedLanguage } from '../i18n'
import { formatDate, formatDateTime, formatNumber, formatTime, timeZoneLabel } from './formatDateTime'

// Re-renders the calling component when the UI language changes, like useTranslation does.
export function useFormatters() {
  const { i18n } = useTranslation()
  const language = isSupportedLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE

  return useMemo(
    () => ({
      language,
      formatDateTime: (value: string | null | undefined) => formatDateTime(value, language),
      formatDate: (value: string | null | undefined) => formatDate(value, language),
      formatTime: (value: string | null | undefined) => formatTime(value, language),
      formatNumber: (value: number | null | undefined) => formatNumber(value, language),
      timeZoneLabel: (value: string | null | undefined) => timeZoneLabel(value, language),
    }),
    [language],
  )
}
