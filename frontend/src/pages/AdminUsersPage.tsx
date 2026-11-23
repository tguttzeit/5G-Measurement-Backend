import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../components/AuthProvider'
import { ApiError } from '../api/client'
import {
  type AdminUser,
  createUser,
  deleteUser,
  listUsers,
  updateUser,
} from '../api/adminUsers'
import { Banner, Button, Card, Table, TextInput } from '../components/ui'
import '../styles/shared.css'

const PAGE_SIZE = 50

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'reason' in detail) {
      return String((detail as { reason: unknown }).reason)
    }
    return fallback
  }
  return fallback
}

function CreateUserForm({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation('adminUsers')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSuperuser, setIsSuperuser] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await createUser({ email, password, is_superuser: isSuperuser })
      setEmail('')
      setPassword('')
      setIsSuperuser(false)
      onCreated()
    } catch (err) {
      setError(errorMessage(err, t('createFailed')))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="admin-form">
      <TextInput
        label={t('username')}
        type="text"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />
      <TextInput
        label={t('password')}
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        minLength={8}
      />
      <div className="admin-form__checkbox">
        <input
          id="is-superuser"
          type="checkbox"
          checked={isSuperuser}
          onChange={(e) => setIsSuperuser(e.target.checked)}
        />
        <label htmlFor="is-superuser">{t('superuser')}</label>
      </div>
      <div>
        <Button type="submit" disabled={submitting}>
          {submitting ? t('creating') : t('createUser')}
        </Button>
      </div>
      {error && <div className="admin-form__error">{error}</div>}
    </form>
  )
}

function UserRow({
  user,
  isSelf,
  onChanged,
}: {
  user: AdminUser
  isSelf: boolean
  onChanged: () => void
}) {
  const { t } = useTranslation('adminUsers')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggleSuperuser = async () => {
    setBusy(true)
    setError(null)
    try {
      await updateUser(user.id, { is_superuser: !user.is_superuser })
      onChanged()
    } catch (err) {
      setError(errorMessage(err, t('updateFailed')))
    } finally {
      setBusy(false)
    }
  }

  const toggleActive = async () => {
    setBusy(true)
    setError(null)
    try {
      await updateUser(user.id, { is_active: !user.is_active })
      onChanged()
    } catch (err) {
      setError(errorMessage(err, t('updateFailed')))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(t('confirmDelete', { email: user.email }))) return
    setBusy(true)
    setError(null)
    try {
      await deleteUser(user.id)
      onChanged()
    } catch (err) {
      setError(errorMessage(err, t('deleteFailed')))
    } finally {
      setBusy(false)
    }
  }

  return (
    <tr>
      <td>{user.id}</td>
      <td style={{ fontWeight: 600 }}>
        {user.email}
        {isSelf && <span style={{ color: 'var(--muted)', fontWeight: 400 }}> {t('you')}</span>}
      </td>
      <td>{user.is_superuser ? t('yes') : t('no')}</td>
      <td>{user.is_active ? t('active') : t('inactive')}</td>
      <td>
        <div className="admin-row__actions">
          <Button
            variant="secondary"
            size="sm"
            onClick={toggleSuperuser}
            disabled={busy || isSelf}
            title={isSelf ? t('selfPermissions') : undefined}
          >
            {user.is_superuser ? t('revokeAdmin') : t('makeAdmin')}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={toggleActive}
            disabled={busy || isSelf}
            title={isSelf ? t('selfDeactivate') : undefined}
          >
            {user.is_active ? t('deactivate') : t('activate')}
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={handleDelete}
            disabled={busy || isSelf}
            title={isSelf ? t('selfDelete') : undefined}
          >
            {t('delete')}
          </Button>
        </div>
        {error && <div className="admin-row__error">{error}</div>}
      </td>
    </tr>
  )
}

export function AdminUsersPage() {
  const { t } = useTranslation('adminUsers')
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchUsers = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await listUsers(page, PAGE_SIZE)
      setUsers(response.users)
      setTotal(response.total)
    } catch (err) {
      setError(errorMessage(err, t('loadFailed')))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchUsers()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section>
      <div className="page-header">
        <h1 className="page-header__title">{t('title')}</h1>
        <p className="page-header__subtitle">{t('subtitle')}</p>
      </div>

      <CreateUserForm onCreated={fetchUsers} />

      {error && <Banner tone="danger" style={{ marginBottom: 'var(--space-4)' }}>{error}</Banner>}

      <Card>
        {loading && users.length === 0 ? (
          <p style={{ color: 'var(--muted)' }}>{t('loading')}</p>
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <th>{t('columns.id')}</th>
                  <th>{t('username')}</th>
                  <th>{t('superuser')}</th>
                  <th>{t('columns.status')}</th>
                  <th>{t('columns.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <UserRow key={u.id} user={u} isSelf={u.id === currentUser?.id} onChanged={fetchUsers} />
                ))}
              </tbody>
            </Table>
            {users.length === 0 && <p style={{ color: 'var(--muted)' }}>{t('noUsers')}</p>}
          </>
        )}

        {total > 0 && (
          <div className="admin-pagination">
            <span>{t('pagination', { page, totalPages, count: total })}</span>
            <div className="admin-pagination__buttons">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1 || loading}
              >
                {t('previous')}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || loading}
              >
                {t('next')}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </section>
  )
}
