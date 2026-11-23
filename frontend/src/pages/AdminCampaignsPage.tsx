import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../api/client'
import {
  type Campaign,
  createCampaign,
  deleteCampaign,
  formatCampaignPeriod,
  listAdminCampaigns,
  updateCampaign,
} from '../api/campaigns'
import { CampaignRunsPanel } from '../components/CampaignRunsPanel'
import { Banner, Button, Card, Table, TextInput } from '../components/ui'
import '../styles/shared.css'

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    return fallback
  }
  return fallback
}

function CreateCampaignForm({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation('adminCampaigns')
  const [name, setName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await createCampaign({ name })
      setName('')
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
        label={t('name')}
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={t('namePlaceholder')}
        required
      />
      <div>
        <Button type="submit" disabled={submitting}>
          {submitting ? t('creating') : t('createCampaign')}
        </Button>
      </div>
      {error && <div className="admin-form__error">{error}</div>}
    </form>
  )
}

function CampaignRow({
  campaign,
  onChanged,
}: {
  campaign: Campaign
  onChanged: () => void
}) {
  const { t } = useTranslation('adminCampaigns')
  const [editing, setEditing] = useState(false)
  const [managingRuns, setManagingRuns] = useState(false)
  const [name, setName] = useState(campaign.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSave = async () => {
    setBusy(true)
    setError(null)
    try {
      await updateCampaign(campaign.id, { name })
      setEditing(false)
      onChanged()
    } catch (err) {
      setError(errorMessage(err, t('updateFailed')))
    } finally {
      setBusy(false)
    }
  }

  const handleCancel = () => {
    setName(campaign.name)
    setError(null)
    setEditing(false)
  }

  const handleDelete = async () => {
    if (!window.confirm(t('confirmDelete', { name: campaign.name }))) return
    setBusy(true)
    setError(null)
    try {
      await deleteCampaign(campaign.id)
      onChanged()
    } catch (err) {
      setError(errorMessage(err, t('deleteFailed')))
    } finally {
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <tr>
        <td>
          <TextInput type="text" value={name} onChange={(e) => setName(e.target.value)} />
        </td>
        <td>{formatCampaignPeriod(campaign)}</td>
        <td>
          <div className="admin-row__actions">
            <Button variant="secondary" size="sm" onClick={handleSave} disabled={busy}>
              {busy ? t('saving') : t('save')}
            </Button>
            <Button variant="secondary" size="sm" onClick={handleCancel} disabled={busy}>
              {t('cancel')}
            </Button>
          </div>
          {error && <div className="admin-row__error">{error}</div>}
        </td>
      </tr>
    )
  }

  return (
    <>
      <tr>
        <td style={{ fontWeight: 600 }}>{campaign.name}</td>
        <td>{formatCampaignPeriod(campaign)}</td>
        <td>
          <div className="admin-row__actions">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setManagingRuns((open) => !open)}
              aria-expanded={managingRuns}
            >
              {managingRuns ? t('hideRuns') : t('manageRuns')}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setEditing(true)} disabled={busy}>
              {t('edit')}
            </Button>
            <Button variant="danger" size="sm" onClick={handleDelete} disabled={busy}>
              {t('delete')}
            </Button>
          </div>
          {error && <div className="admin-row__error">{error}</div>}
        </td>
      </tr>
      {managingRuns && (
        <tr>
          <td colSpan={3}>
            <CampaignRunsPanel campaign={campaign} onChanged={onChanged} />
          </td>
        </tr>
      )}
    </>
  )
}

export function AdminCampaignsPage() {
  const { t } = useTranslation('adminCampaigns')
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchCampaigns = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await listAdminCampaigns()
      setCampaigns(response.campaigns)
    } catch (err) {
      setError(errorMessage(err, t('loadFailed')))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCampaigns()
  }, [])

  return (
    <section>
      <div className="page-header">
        <h1 className="page-header__title">{t('title')}</h1>
        <p className="page-header__subtitle">
          {t('subtitle')}
        </p>
      </div>

      <CreateCampaignForm onCreated={fetchCampaigns} />

      {error && <Banner tone="danger" style={{ marginBottom: 'var(--space-4)' }}>{error}</Banner>}

      <Card>
        {loading && campaigns.length === 0 ? (
          <p style={{ color: 'var(--muted)' }}>{t('loading')}</p>
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <th>{t('name')}</th>
                  <th>{t('period')}</th>
                  <th>{t('actions')}</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => (
                  <CampaignRow key={c.id} campaign={c} onChanged={fetchCampaigns} />
                ))}
              </tbody>
            </Table>
            {campaigns.length === 0 && <p style={{ color: 'var(--muted)' }}>{t('noCampaigns')}</p>}
          </>
        )}
      </Card>
    </section>
  )
}
