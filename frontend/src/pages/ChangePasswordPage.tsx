import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { changePassword } from '../api/auth'
import { ApiError } from '../api/client'
import { Banner, Button, TextInput } from '../components/ui'

interface ChangePasswordError {
  message: string
  attemptsRemaining?: number
  locked: boolean
}

function parseError(err: unknown, t: TFunction<'auth'>): ChangePasswordError {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail

    if (typeof detail === 'string') {
      return { message: detail, locked: detail.toLowerCase().includes('locked') }
    }

    if (detail && typeof detail === 'object') {
      const d = detail as { detail?: string; reason?: string; attempts_remaining?: number }
      if (typeof d.attempts_remaining === 'number') {
        return {
          message: d.detail ?? t('changePassword.incorrectCurrent'),
          attemptsRemaining: d.attempts_remaining,
          locked: false,
        }
      }
      if (d.reason) {
        return { message: d.reason, locked: false }
      }
    }
  }
  return { message: t('changePassword.failed'), locked: false }
}

export function ChangePasswordPage() {
  const { t } = useTranslation('auth')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<ChangePasswordError | null>(null)
  const [success, setSuccess] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(false)

    if (newPassword !== confirmPassword) {
      setError({ message: t('changePassword.mismatch'), locked: false })
      return
    }

    setSubmitting(true)
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword })
      setSuccess(true)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setError(parseError(err, t))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section style={{ maxWidth: '420px' }}>
      <h1 style={{ margin: '0 0 4px 0', fontSize: '1.5rem', fontWeight: 700 }}>{t('changePassword.title')}</h1>
      <p style={{ color: 'var(--muted)', margin: '0 0 24px 0', fontSize: '0.875rem' }}>
        {t('changePassword.intro')}
      </p>

      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: '1rem' }}>
          <TextInput
            id="current-password"
            label={t('changePassword.currentPassword')}
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
            disabled={error?.locked}
          />
        </div>

        <div style={{ marginBottom: '1rem' }}>
          <TextInput
            id="new-password"
            label={t('changePassword.newPassword')}
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            minLength={8}
            disabled={error?.locked}
          />
        </div>

        <div style={{ marginBottom: '1.5rem' }}>
          <TextInput
            id="confirm-password"
            label={t('changePassword.confirmPassword')}
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            minLength={8}
            disabled={error?.locked}
          />
        </div>

        {error?.locked && (
          <Banner tone="danger" style={{ marginBottom: '1rem' }}>
            {t('changePassword.locked')}
          </Banner>
        )}

        {error && !error.locked && (
          <Banner tone="danger" style={{ marginBottom: '1rem' }}>
            {error.message}
            {typeof error.attemptsRemaining === 'number' && (
              <div>{t('changePassword.attemptsRemaining', { count: error.attemptsRemaining })}</div>
            )}
          </Banner>
        )}

        {success && (
          <Banner tone="success" style={{ marginBottom: '1rem' }}>
            {t('changePassword.success')}
          </Banner>
        )}

        <Button type="submit" disabled={submitting || error?.locked} style={{ width: '100%' }}>
          {submitting ? t('changePassword.submitting') : t('changePassword.submit')}
        </Button>
      </form>
    </section>
  )
}
