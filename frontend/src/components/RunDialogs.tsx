import { useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import type { Campaign } from '../api/campaigns'
import { ApiError } from '../api/client'
import {
  deleteRun,
  deleteRunPermanently,
  type Run,
  type TrashedRun,
  type RunChanges,
  runLabel,
  updateRun,
  updateRuns,
} from '../api/runs'
import { Banner, ConfirmDialog, Select, TextInput } from './ui'
import './RunDialogs.css'

const MISSION_TYPES = ['ground', 'drone'] as const
const NAME_MAX_LENGTH = 255

// Campaign select values: '' keeps the current campaign (bulk) / means none (single).
const NO_CHANGE = ''
const NO_CAMPAIGN = 'none'

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}

interface DialogProps {
  onClose: () => void
  onDone: () => void
}

function useSubmit(onDone: () => void, fallbackError: string) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (action: () => Promise<unknown>) => {
    setSubmitting(true)
    setError(null)
    try {
      await action()
      onDone()
    } catch (err) {
      setError(errorMessage(err, fallbackError))
      setSubmitting(false)
    }
  }

  return { submitting, error, submit }
}

function CampaignOptions({ campaigns }: { campaigns: Campaign[] }) {
  return (
    <>
      {campaigns.map((campaign) => (
        <option key={campaign.id} value={campaign.id}>{campaign.name}</option>
      ))}
    </>
  )
}

export function EditRunDialog({
  run,
  campaigns,
  onClose,
  onDone,
}: DialogProps & { run: Run; campaigns: Campaign[] }) {
  const { t } = useTranslation('runDialogs')
  const [name, setName] = useState(run.name ?? '')
  const [missionType, setMissionType] = useState(run.mission_type)
  const [campaignId, setCampaignId] = useState(run.campaign_id == null ? NO_CAMPAIGN : String(run.campaign_id))
  const { submitting, error, submit } = useSubmit(onDone, t('edit.failed'))

  const missionTypes: string[] = [...MISSION_TYPES]
  if (!missionTypes.includes(run.mission_type)) missionTypes.push(run.mission_type)

  const changes: RunChanges = {}
  if (name.trim() !== (run.name ?? '')) changes.name = name.trim() || null
  if (missionType !== run.mission_type) changes.mission_type = missionType as RunChanges['mission_type']
  const newCampaignId = campaignId === NO_CAMPAIGN ? null : Number(campaignId)
  if (newCampaignId !== run.campaign_id) changes.campaign_id = newCampaignId
  const hasChanges = Object.keys(changes).length > 0

  return (
    <ConfirmDialog
      title={t('edit.title')}
      confirmLabel={t('edit.save')}
      submittingLabel={t('edit.saving')}
      submitting={submitting}
      confirmDisabled={!hasChanges}
      onCancel={onClose}
      onConfirm={() => submit(() => updateRun(run.id, changes))}
    >
      <div className="run-dialog__fields">
        {error && <Banner tone="danger">{error}</Banner>}
        <TextInput label={t('edit.deviceId')} value={run.device_id} readOnly />
        <TextInput label={t('edit.runId')} value={run.run_id} readOnly />
        <TextInput
          label={t('edit.name')}
          value={name}
          maxLength={NAME_MAX_LENGTH}
          placeholder={run.run_id}
          onChange={(e) => setName(e.target.value)}
        />
        <Select label={t('edit.missionType')} value={missionType} onChange={(e) => setMissionType(e.target.value)}>
          {missionTypes.map((type) => (
            <option key={type} value={type}>{t(`missionType.${type}`, { ns: 'common', defaultValue: type })}</option>
          ))}
        </Select>
        <Select label={t('edit.campaign')} value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
          <option value={NO_CAMPAIGN}>{t('edit.noCampaign')}</option>
          <CampaignOptions campaigns={campaigns} />
        </Select>
      </div>
    </ConfirmDialog>
  )
}

export function BulkEditRunsDialog({
  runs,
  campaigns,
  onClose,
  onDone,
}: DialogProps & { runs: Run[]; campaigns: Campaign[] }) {
  const { t } = useTranslation('runDialogs')
  const [name, setName] = useState('')
  const [missionType, setMissionType] = useState(NO_CHANGE)
  const [campaignId, setCampaignId] = useState(NO_CHANGE)
  const { submitting, error, submit } = useSubmit(onDone, t('bulk.failed'))

  // Only fields that were explicitly filled in are applied
  const changes: RunChanges = {}
  if (name.trim()) changes.name = name.trim()
  if (missionType !== NO_CHANGE) changes.mission_type = missionType as RunChanges['mission_type']
  if (campaignId !== NO_CHANGE) changes.campaign_id = campaignId === NO_CAMPAIGN ? null : Number(campaignId)
  const hasChanges = Object.keys(changes).length > 0

  return (
    <ConfirmDialog
      title={t('bulk.title', { count: runs.length })}
      confirmLabel={t('bulk.apply')}
      submittingLabel={t('bulk.applying')}
      submitting={submitting}
      confirmDisabled={!hasChanges}
      onCancel={onClose}
      onConfirm={() =>
        submit(() =>
          updateRuns(
            runs.map((run) => run.id),
            changes,
          ),
        )
      }
    >
      <div className="run-dialog__fields">
        <p className="run-dialog__hint">{t('bulk.hint')}</p>
        {error && <Banner tone="danger">{error}</Banner>}
        <TextInput
          label={t('edit.name')}
          value={name}
          maxLength={NAME_MAX_LENGTH}
          placeholder={t('bulk.namePlaceholder')}
          onChange={(e) => setName(e.target.value)}
        />
        <Select label={t('edit.missionType')} value={missionType} onChange={(e) => setMissionType(e.target.value)}>
          <option value={NO_CHANGE}>{t('bulk.keepCurrent')}</option>
          {MISSION_TYPES.map((type) => (
            <option key={type} value={type}>{t(`missionType.${type}`, { ns: 'common' })}</option>
          ))}
        </Select>
        <Select label={t('edit.campaign')} value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
          <option value={NO_CHANGE}>{t('bulk.keepCurrent')}</option>
          <option value={NO_CAMPAIGN}>{t('edit.noCampaign')}</option>
          <CampaignOptions campaigns={campaigns} />
        </Select>
      </div>
    </ConfirmDialog>
  )
}

export function DeleteRunDialog({ run, onClose, onDone }: DialogProps & { run: Run }) {
  const { t } = useTranslation('runDialogs')
  const { submitting, error, submit } = useSubmit(onDone, t('delete.failed'))

  return (
    <ConfirmDialog
      title={t('delete.title')}
      confirmLabel={t('delete.confirm')}
      submittingLabel={t('delete.deleting')}
      confirmVariant="danger"
      submitting={submitting}
      onCancel={onClose}
      onConfirm={() => submit(() => deleteRun(run.id))}
    >
      <div className="run-dialog__fields">
        {error && <Banner tone="danger">{error}</Banner>}
        <p>
          <Trans
            t={t}
            i18nKey="delete.body"
            count={run.point_count}
            values={{ deviceId: run.device_id }}
            shouldUnescape
            components={{ run: <strong>{runLabel(run)}</strong> }}
          />
        </p>
      </div>
    </ConfirmDialog>
  )
}

export function DeleteRunPermanentlyDialog({
  run,
  onClose,
  onDone,
}: DialogProps & { run: TrashedRun }) {
  const { t } = useTranslation('runDialogs')
  const { submitting, error, submit } = useSubmit(onDone, t('deletePermanently.failed'))

  return (
    <ConfirmDialog
      title={t('deletePermanently.title')}
      confirmLabel={t('deletePermanently.confirm')}
      submittingLabel={t('deletePermanently.deleting')}
      confirmVariant="danger"
      focusCancel
      submitting={submitting}
      onCancel={onClose}
      onConfirm={() => submit(() => deleteRunPermanently(run.id))}
    >
      <div className="run-dialog__fields">
        {error && <Banner tone="danger">{error}</Banner>}
        <p>
          <Trans
            t={t}
            i18nKey="deletePermanently.body"
            count={run.point_count}
            values={{ deviceId: run.device_id, latencyResults: run.latency_result_count }}
            shouldUnescape
            components={{ run: <strong>{runLabel(run)}</strong> }}
          />
        </p>
      </div>
    </ConfirmDialog>
  )
}
