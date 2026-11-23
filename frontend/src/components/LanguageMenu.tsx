import { useTranslation } from 'react-i18next'
import { SUPPORTED_LANGUAGES } from '../i18n'
import { useLanguage } from '../i18n/LanguageProvider'
import { HeaderDropdown } from './HeaderDropdown'
import './LanguageMenu.css'

function GlobeIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18" />
    </svg>
  )
}

export function LanguageMenu() {
  const { t } = useTranslation('settings')
  const { language, setLanguage } = useLanguage()

  return (
    <HeaderDropdown
      trigger={({ toggle, isOpen }) => (
        <button
          type="button"
          className="language-menu__trigger"
          onClick={toggle}
          aria-expanded={isOpen}
          aria-label={t('language.label')}
        >
          <GlobeIcon />
        </button>
      )}
    >
      {({ close }) => (
        <div className="language-menu__panel" role="group" aria-label={t('language.label')}>
          {SUPPORTED_LANGUAGES.map((code) => (
            <button
              key={code}
              type="button"
              className={code === language ? 'active' : undefined}
              aria-pressed={code === language}
              onClick={() => {
                setLanguage(code)
                close()
              }}
            >
              {t(`language.${code}`)}
            </button>
          ))}
        </div>
      )}
    </HeaderDropdown>
  )
}
