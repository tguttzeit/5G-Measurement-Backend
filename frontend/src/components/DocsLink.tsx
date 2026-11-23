import { useTranslation } from 'react-i18next'
import { useLanguage } from '../i18n/LanguageProvider'
import './DocsLink.css'

export function DocsLink() {
  const { t } = useTranslation('shell')
  const { language } = useLanguage()

  return (
    <a className="docs-link" href={`/docs/${language}/`}>
      {t('docs')}
    </a>
  )
}
