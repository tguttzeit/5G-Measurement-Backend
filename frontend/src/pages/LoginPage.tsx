import { useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { LoginForm } from '../components/LoginForm'
import { Card, Banner } from '../components/ui'
import './LoginPage.css'

export function LoginPage() {
  const navigate = useNavigate()
  const { t } = useTranslation('auth')
  const location = useLocation()
  const [searchParams] = useSearchParams()

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/status'
  // Set by ProtectedRoute (router state, in-app expiry) or the client.ts 401 interceptor
  // (query param, since it redirects with a full page load and has no router state to pass).
  const sessionExpired =
    (location.state as { sessionExpired?: boolean })?.sessionExpired ||
    searchParams.get('sessionExpired') === '1'

  return (
    <Card className="login-page">
      <h1 className="login-page__title">{t('loginTitle')}</h1>
      {sessionExpired && (
        <Banner tone="danger" style={{ marginBottom: '1rem', textAlign: 'center' }}>
          {t('sessionExpired')}
        </Banner>
      )}
      <LoginForm onSuccess={() => navigate(from, { replace: true })} />
    </Card>
  )
}
