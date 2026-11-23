import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from './AuthProvider'
import { Button, TextInput, Banner } from './ui'

export function LoginForm({ onSuccess }: { onSuccess?: () => void }) {
  const [email, setEmail] = useState('')  // Treated as username
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const { login } = useAuth()
  const { t } = useTranslation('auth')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      await login(email, password)
      onSuccess?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('loginFailed'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {error && (
        <Banner tone="danger" style={{ marginBottom: '1rem', textAlign: 'center' }}>
          {error}
        </Banner>
      )}

      <div style={{ marginBottom: '1rem' }}>
        <TextInput
          id="email"
          label={t('username')}
          type="text"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
      </div>

      <div style={{ marginBottom: '1.5rem' }}>
        <TextInput
          id="password"
          label={t('password')}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>

      <Button type="submit" disabled={isSubmitting} style={{ width: '100%' }}>
        {isSubmitting ? t('loggingIn') : t('loginButton')}
      </Button>
    </form>
  )
}
