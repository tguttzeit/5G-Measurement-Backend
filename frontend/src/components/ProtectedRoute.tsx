import { useEffect } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from './AuthProvider'
import { isTokenExpired } from '../lib/jwt'

export function ProtectedRoute({
  children,
  requireSuperuser = false,
}: {
  children: React.ReactNode
  requireSuperuser?: boolean
}) {
  const { user, token, isAuthenticated, isLoading, logout } = useAuth()
  const location = useLocation()
  const { t } = useTranslation()

  // UX-only: avoids rendering a page that's about to fail its API calls with a stale token.
  // Real enforcement is the 401 interceptor in client.ts.
  const expired = !!token && isTokenExpired(token)

  useEffect(() => {
    if (expired) {
      logout()
    }
  }, [expired, logout])

  if (isLoading) {
    return <div>{t('loading')}</div>
  }

  if (!isAuthenticated || expired) {
    // Redirect to login, but save the attempted location
    return <Navigate to="/login" state={{ from: location, sessionExpired: expired }} replace />
  }

  // Backend enforces this too (super-user-only endpoints) -- this is only to avoid showing
  // a dead-end page to a logged-in non-admin.
  if (requireSuperuser && !user?.is_superuser) {
    return <Navigate to="/map" replace />
  }

  return <>{children}</>
}
