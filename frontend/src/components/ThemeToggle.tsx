import { useTranslation } from 'react-i18next'
import { useTheme } from './ThemeProvider'
import './ThemeToggle.css'

const OPTIONS = ['system', 'light', 'dark'] as const

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const { t } = useTranslation()

  return (
    <div className="theme-toggle" role="group" aria-label={t('theme.label')}>
      {OPTIONS.map((option) => (
        <button
          key={option}
          type="button"
          className={theme === option ? 'active' : undefined}
          aria-pressed={theme === option}
          onClick={() => setTheme(option)}
        >
          {t(`theme.${option}`)}
        </button>
      ))}
    </div>
  )
}
