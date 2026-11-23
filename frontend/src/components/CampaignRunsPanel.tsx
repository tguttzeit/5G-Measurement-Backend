import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { ApiError } from '../api/client'
import { assignRuns, type Campaign, type RunReference, unassignRuns } from '../api/campaigns'
import { fetchRuns, type Run } from '../api/runs'
import { Banner, Button, Table } from './ui'
import { Timestamp } from './Timestamp'
import './CampaignRunsPanel.css'

const PAGE_SIZE = 25

function runKey(run: RunReference): string {
  return JSON.stringify([run.device_id, run.run_id])
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
  }
  return i18n.t('campaignRuns:updateFailed')
}

interface RunListFilter {
  campaignId?: number
  unassigned?: boolean
}

// One page of runs plus a selection that survives only as long as the shown page does.
function useRunList(filter: RunListFilter, reloadKey: number) {
  const [runs, setRuns] = useState<Run[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    fetchRuns(
      {
        campaignId: filter.campaignId,
        unassigned: filter.unassigned,
        sort: 'start',
        order: 'desc',
        page,
        pageSize: PAGE_SIZE,
      },
      controller.signal,
    )
      .then((response) => {
        setRuns(response.runs)
        setTotal(response.total)
        setError(null)
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [filter.campaignId, filter.unassigned, page, reloadKey])

  const toggle = (run: Run) =>
    setSelected((prev) => {
      const next = new Set(prev)
      const key = runKey(run)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const selectedRuns = runs.filter((run) => selected.has(runKey(run)))

  return {
    runs,
    total,
    page,
    setPage: (value: number) => {
      setSelected(new Set())
      setPage(value)
    },
    loading,
    error,
    selected,
    selectedRuns,
    toggle,
    clearSelection: () => setSelected(new Set()),
  }
}

type RunList = ReturnType<typeof useRunList>

function RunTable({
  caption,
  list,
  showCampaign,
  hideRunsOfCampaign,
}: {
  caption: string
  list: RunList
  showCampaign: boolean
  hideRunsOfCampaign?: number
}) {
  const { t } = useTranslation('campaignRuns')
  const runs = list.runs.filter((run) => run.campaign_id !== hideRunsOfCampaign)
  const totalPages = Math.max(1, Math.ceil(list.total / PAGE_SIZE))

  return (
    <>
      <Table aria-label={caption}>
        <thead>
          <tr>
            <th />
            <th>{t('columns.run')}</th>
            <th>{t('columns.device')}</th>
            <th>{t('columns.mission')}</th>
            <th>{t('columns.start')}</th>
            {showCampaign && <th>{t('columns.campaign')}</th>}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={runKey(run)}>
              <td>
                <input
                  type="checkbox"
                  aria-label={t('selectRun', { runId: run.run_id, deviceId: run.device_id })}
                  checked={list.selected.has(runKey(run))}
                  onChange={() => list.toggle(run)}
                />
              </td>
              <td className="campaign-runs__run-id">{run.run_id}</td>
              <td>{run.device_id}</td>
              <td>{t('missionType.' + run.mission_type, { ns: 'common', defaultValue: run.mission_type })}</td>
              <td><Timestamp value={run.start} /></td>
              {showCampaign && <td>{run.campaign_name ?? '–'}</td>}
            </tr>
          ))}
          {!list.loading && runs.length === 0 && (
            <tr>
              <td colSpan={showCampaign ? 6 : 5}>{t('noRuns')}</td>
            </tr>
          )}
        </tbody>
      </Table>
      {list.total > PAGE_SIZE && (
        <div className="admin-pagination">
          <span>{t('pagination', { page: list.page, totalPages, count: list.total })}</span>
          <div className="admin-pagination__buttons">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => list.setPage(list.page - 1)}
              disabled={list.page <= 1 || list.loading}
            >
              {t('previous')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => list.setPage(list.page + 1)}
              disabled={list.page >= totalPages || list.loading}
            >
              {t('next')}
            </Button>
          </div>
        </div>
      )}
    </>
  )
}

export function CampaignRunsPanel({
  campaign,
  onChanged,
}: {
  campaign: Campaign
  onChanged: () => void
}) {
  const { t } = useTranslation('campaignRuns')
  const [includeOtherCampaigns, setIncludeOtherCampaigns] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const members = useRunList({ campaignId: campaign.id }, reloadKey)
  const candidates = useRunList(includeOtherCampaigns ? {} : { unassigned: true }, reloadKey)

  const apply = async (
    change: (id: number, runs: RunReference[]) => Promise<Campaign>,
    runs: Run[],
  ) => {
    setBusy(true)
    setError(null)
    try {
      await change(
        campaign.id,
        runs.map(({ device_id, run_id }) => ({ device_id, run_id })),
      )
      members.clearSelection()
      candidates.clearSelection()
      setReloadKey((key) => key + 1)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="campaign-runs" aria-label={t('runsOf', { name: campaign.name })}>
      {error && <Banner tone="danger">{error}</Banner>}
      {members.error && <Banner tone="danger">{members.error}</Banner>}
      {candidates.error && <Banner tone="danger">{candidates.error}</Banner>}

      <h3 className="campaign-runs__title">{t('membersTitle')}</h3>
      <RunTable caption={t('membersTitle')} list={members} showCampaign={false} />
      <div className="campaign-runs__actions">
        <Button
          variant="secondary"
          size="sm"
          disabled={busy || members.selectedRuns.length === 0}
          onClick={() => apply(unassignRuns, members.selectedRuns)}
        >
          {t('removeSelected')}
        </Button>
      </div>

      <h3 className="campaign-runs__title">{t('addTitle')}</h3>
      <label className="campaign-runs__toggle">
        <input
          type="checkbox"
          checked={includeOtherCampaigns}
          onChange={(e) => {
            candidates.setPage(1)
            setIncludeOtherCampaigns(e.target.checked)
          }}
        />
        {t('includeOthers')}
      </label>
      <RunTable
        caption={t('candidatesCaption')}
        list={candidates}
        showCampaign={includeOtherCampaigns}
        hideRunsOfCampaign={campaign.id}
      />
      <div className="campaign-runs__actions">
        <Button
          size="sm"
          disabled={busy || candidates.selectedRuns.length === 0}
          onClick={() => apply(assignRuns, candidates.selectedRuns)}
        >
          {t('addSelected')}
        </Button>
      </div>
    </section>
  )
}
