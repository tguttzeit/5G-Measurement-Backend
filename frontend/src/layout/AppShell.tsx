import { Outlet, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import './AppShell.css'
import { useAuth } from '../components/AuthProvider'
import { CommandAckNotifications } from '../components/CommandAckNotifications'
import { ToastProvider } from '../components/ToastProvider'
import { UploadNotifications } from '../components/UploadNotifications'
import { UserMenu } from '../components/UserMenu'
import { LoginMenu } from '../components/LoginMenu'
import { LanguageMenu } from '../components/LanguageMenu'
import { DocsLink } from '../components/DocsLink'

export function AppShell() {
  const { isAuthenticated } = useAuth()
  const { t } = useTranslation('shell')

  return (
    <ToastProvider>
      <UploadNotifications />
      <CommandAckNotifications />
      <div className="app-shell">
        <header className="app-shell__header">
          <Link to="/" className="app-shell__title">
            {t('appTitle')}
          </Link>
          <nav className="app-shell__nav">
            <DocsLink />
            {isAuthenticated ? (
              <UserMenu />
            ) : (
              <>
                <LanguageMenu />
                <LoginMenu />
              </>
            )}
          </nav>
        </header>
        <main className="app-shell__content">
          <Outlet />
        </main>
      </div>
    </ToastProvider>
  )
}
