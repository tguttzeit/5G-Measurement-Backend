import { useTranslation } from 'react-i18next'
import { HeaderDropdown } from './HeaderDropdown'
import { LoginForm } from './LoginForm'
import { ThemeToggle } from './ThemeToggle'
import './LoginMenu.css'

export function LoginMenu() {
  const { t } = useTranslation('shell')

  return (
    <HeaderDropdown
      trigger={({ toggle, isOpen }) => (
        <button
          type="button"
          className="login-menu__trigger"
          onClick={toggle}
          aria-expanded={isOpen}
        >
          {t('login')}
        </button>
      )}
    >
      {({ close }) => (
        <div className="login-menu__panel">
          <LoginForm onSuccess={close} />
          <ThemeToggle />
        </div>
      )}
    </HeaderDropdown>
  )
}
