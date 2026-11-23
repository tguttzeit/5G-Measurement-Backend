import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { type Campaign, fetchPublicCampaigns } from '../api/campaigns'
import {
  fetchRuns,
  mapLinkForRun,
  type Run,
  runLabel,
  type RunSortKey,
  type SortOrder,
} from '../api/runs'
import { useAuth } from '../components/AuthProvider'
import { BulkEditRunsDialog, DeleteRunDialog, EditRunDialog } from '../components/RunDialogs'
import { Banner, Button, Card, Select, Table, TextInput } from '../components/ui'
import { Timestamp } from '../components/Timestamp'
import '../styles/shared.css'
import './RunsPage.css'

const PAGE_SIZE = 25
const DEVICE_ID_DEBOUNCE_MS = 400
const MISSION_TYPES = ['ground', 'drone'] as const

interface Filters {
  deviceId: string
  missionType: string
  campaignId: string
  from: string
  to: string
}

// Campaign filter value for runs that belong to no campaign
const UNASSIGNED = 'unassigned'

const EMPTY_FILTERS: Filters = { deviceId: '', missionType: '', campaignId: '', from: '', to: '' }

function formatDuration(start: string, end: string): string {
  const totalSeconds = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return i18n.t('runs:duration.hoursMinutes', { hours, minutes })
  if (minutes > 0) return i18n.t('runs:duration.minutesSeconds', { minutes, seconds })
  return i18n.t('runs:duration.seconds', { seconds })
}

function formatMean(value: number | null): string {
  return value == null ? '–' : value.toFixed(1)
}

function SortHeader({
  column,
  sort,
  order,
  onSort,
}: {
  column: RunSortKey
  sort: RunSortKey
  order: SortOrder
  onSort: (key: RunSortKey) => void
}) {
  const { t } = useTranslation('runs')
  const active = sort === column
  const ariaSort = active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'
  return (
    <th aria-sort={ariaSort}>
      <button type="button" className="runs-table__sort" onClick={() => onSort(column)}>
        {t(`sort.${column}`)}
        {active && (order === 'asc' ? ' ▲' : ' ▼')}
      </button>
    </th>
  )
}

type RunDialog =
  | { kind: 'edit'; run: Run }
  | { kind: 'delete'; run: Run }
  | { kind: 'bulk' }

export function RunsPage() {
  const { t } = useTranslation('runs')
  const navigate = useNavigate()
  const { user } = useAuth()
  const canEdit = user?.is_superuser === true
  const [searchParams] = useSearchParams()
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  // Free-text device ID is debounced into filters.deviceId rather than fetching per keystroke.
  // Pre-filled from ?device_id=, e.g. the link in the "upload successful" toast.
  const [deviceIdInput, setDeviceIdInput] = useState(() => searchParams.get('device_id') ?? '')
  // Run(s) to call out as newly arrived, from that same toast link - a client-side-only hint
  // (GET /runs has no run_id filter), cleared for good once the user notices and hovers one.
  const [highlightRunIds] = useState(() => new Set(searchParams.get('run_id')?.split(',') ?? []))
  const [highlightDismissed, setHighlightDismissed] = useState(false)
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [sort, setSort] = useState<RunSortKey>('start')
  const [order, setOrder] = useState<SortOrder>('desc')
  const [page, setPage] = useState(1)
  const [runs, setRuns] = useState<Run[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [dialog, setDialog] = useState<RunDialog | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    fetchPublicCampaigns()
      .then(({ campaigns }) => setCampaigns(campaigns))
      .catch(() => setError(i18n.t('runs:loadCampaignsFailed')))
  }, [])

  useEffect(() => {
    const timeout = setTimeout(() => {
      setFilters((prev) => ({ ...prev, deviceId: deviceIdInput }))
      setPage(1)
    }, DEVICE_ID_DEBOUNCE_MS)
    return () => clearTimeout(timeout)
  }, [deviceIdInput])

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)
    fetchRuns(
      {
        deviceId: filters.deviceId,
        missionType: filters.missionType,
        campaignId:
          filters.campaignId && filters.campaignId !== UNASSIGNED ? Number(filters.campaignId) : null,
        unassigned: filters.campaignId === UNASSIGNED,
        from: filters.from,
        to: filters.to,
        sort,
        order,
        page,
        pageSize: PAGE_SIZE,
      },
      controller.signal,
    )
      .then((response) => {
        setRuns(response.runs)
        setTotal(response.total)
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(i18n.t('runs:loadFailed'))
      })
      .finally(() => {
        if (abortRef.current === controller) setLoading(false)
      })

    return () => controller.abort()
  }, [filters, sort, order, page, reloadKey])

  // The selection only ever refers to rows that are on screen
  useEffect(() => {
    setSelectedIds(new Set())
  }, [filters, sort, order, page])

  const changeFilter = (patch: Partial<Filters>) => {
    setFilters((prev) => ({ ...prev, ...patch }))
    setPage(1)
  }

  const toggleSelected = (id: number) =>
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const allSelected = runs.length > 0 && runs.every((run) => selectedIds.has(run.id))
  const toggleAll = () => setSelectedIds(allSelected ? new Set() : new Set(runs.map((run) => run.id)))
  const selectedRuns = runs.filter((run) => selectedIds.has(run.id))

  const closeDialog = () => setDialog(null)
  const finishDialog = () => {
    // Deleting the last run of a page leaves it empty, so step back to the previous one
    if (dialog?.kind === 'delete' && runs.length === 1 && page > 1) setPage(page - 1)
    setDialog(null)
    setSelectedIds(new Set())
    setReloadKey((key) => key + 1)
  }

  const changeSort = (key: RunSortKey) => {
    if (key === sort) {
      setOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(key)
      setOrder('desc')
    }
    setPage(1)
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section>
      <div className="page-header page-header--row">
        <div>
          <h1 className="page-header__title">{t('title')}</h1>
          <p className="page-header__subtitle">
            {t('subtitle')}
          </p>
        </div>
        {canEdit && (
          <Link to="/runs/trash" className="ui-button ui-button--secondary ui-button--sm">
            {t('trash')}
          </Link>
        )}
      </div>

      <div className="filter-grid">
        <TextInput
          label={t('filters.deviceId')}
          type="text"
          value={deviceIdInput}
          onChange={(e) => setDeviceIdInput(e.target.value)}
          placeholder={t('filters.devicePlaceholder')}
        />
        <Select
          label={t('filters.missionType')}
          value={filters.missionType}
          onChange={(e) => changeFilter({ missionType: e.target.value })}
        >
          <option value="">{t('filters.all')}</option>
          {MISSION_TYPES.map((type) => (
            <option key={type} value={type}>{t(`missionType.${type}`, { ns: 'common' })}</option>
          ))}
        </Select>
        <Select
          label={t('filters.campaign')}
          value={filters.campaignId}
          onChange={(e) => changeFilter({ campaignId: e.target.value })}
        >
          <option value="">{t('filters.allRuns')}</option>
          <option value={UNASSIGNED}>{t('filters.unassigned')}</option>
          {campaigns.map((campaign) => (
            <option key={campaign.id} value={campaign.id}>{campaign.name}</option>
          ))}
        </Select>
        <TextInput
          label={t('filters.from')}
          type="date"
          value={filters.from}
          onChange={(e) => changeFilter({ from: e.target.value })}
        />
        <TextInput
          label={t('filters.to')}
          type="date"
          value={filters.to}
          onChange={(e) => changeFilter({ to: e.target.value })}
        />
      </div>

      {error && <Banner tone="danger" style={{ marginBottom: 'var(--space-4)' }}>{error}</Banner>}

      {canEdit && selectedRuns.length > 0 && (
        <div className="runs-bulk-bar">
          <span>{t('bulk.selected', { count: selectedRuns.length })}</span>
          <Button size="sm" onClick={() => setDialog({ kind: 'bulk' })}>
            {t('bulk.edit')}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setSelectedIds(new Set())}>
            {t('bulk.clear')}
          </Button>
        </div>
      )}

      <Card>
        <Table>
          <thead>
            <tr>
              {canEdit && (
                <th>
                  <input
                    type="checkbox"
                    aria-label={t('selectAll')}
                    checked={allSelected}
                    onChange={toggleAll}
                  />
                </th>
              )}
              <th>{t('columns.run')}</th>
              <th>{t('columns.device')}</th>
              <th>{t('columns.mission')}</th>
              <SortHeader column="start" sort={sort} order={order} onSort={changeSort} />
              <th>{t('columns.end')}</th>
              <SortHeader column="duration" sort={sort} order={order} onSort={changeSort} />
              <SortHeader column="point_count" sort={sort} order={order} onSort={changeSort} />
              <th>{t('columns.meanRsrp')}</th>
              <th>{t('columns.meanRsrq')}</th>
              <th>{t('columns.meanSinr')}</th>
              <th>{t('columns.campaign')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr
                key={`${run.device_id}/${run.run_id}`}
                className={
                  highlightRunIds.has(run.run_id) && !highlightDismissed ? 'runs-table__row--new' : undefined
                }
                onMouseEnter={() => setHighlightDismissed(true)}
              >
                {canEdit && (
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t('selectRun', { run: runLabel(run), deviceId: run.device_id })}
                      checked={selectedIds.has(run.id)}
                      onChange={() => toggleSelected(run.id)}
                    />
                  </td>
                )}
                <td className="runs-table__run-id">
                  {runLabel(run)}
                  {run.name != null && <div className="runs-table__device-run-id">{run.run_id}</div>}
                  {run.legacy && <span className="test-type-badge" style={{ marginLeft: 8 }}>{t('legacy')}</span>}
                </td>
                <td>{run.device_id}</td>
                <td>{t(`missionType.${run.mission_type}`, { ns: 'common', defaultValue: run.mission_type })}</td>
                <td><Timestamp value={run.start} /></td>
                <td><Timestamp value={run.end} /></td>
                <td className="runs-table__numeric">{formatDuration(run.start, run.end)}</td>
                <td className="runs-table__numeric">{run.point_count}</td>
                <td className="runs-table__numeric">{formatMean(run.mean_rsrp)}</td>
                <td className="runs-table__numeric">{formatMean(run.mean_rsrq)}</td>
                <td className="runs-table__numeric">{formatMean(run.mean_sinr)}</td>
                <td>{run.campaign_name ?? '–'}</td>
                <td className="runs-table__actions">
                  <Button variant="secondary" size="sm" onClick={() => navigate(mapLinkForRun(run))}>
                    {t('showOnMap')}
                  </Button>
                  {canEdit && (
                    <>
                      <Button
                        variant="secondary"
                        size="sm"
                        aria-label={t('editRun', { run: runLabel(run) })}
                        onClick={() => setDialog({ kind: 'edit', run })}
                      >
                        {t('edit')}
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        aria-label={t('deleteRun', { run: runLabel(run) })}
                        onClick={() => setDialog({ kind: 'delete', run })}
                      >
                        {t('delete')}
                      </Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!loading && runs.length === 0 && (
              <tr>
                <td colSpan={canEdit ? 13 : 12}>{t('noRuns')}</td>
              </tr>
            )}
            {loading && (
              <tr>
                <td colSpan={canEdit ? 13 : 12}>{t('loading', { ns: 'common' })}</td>
              </tr>
            )}
          </tbody>
        </Table>

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

      {dialog?.kind === 'edit' && (
        <EditRunDialog run={dialog.run} campaigns={campaigns} onClose={closeDialog} onDone={finishDialog} />
      )}
      {dialog?.kind === 'delete' && (
        <DeleteRunDialog run={dialog.run} onClose={closeDialog} onDone={finishDialog} />
      )}
      {dialog?.kind === 'bulk' && (
        <BulkEditRunsDialog
          runs={selectedRuns}
          campaigns={campaigns}
          onClose={closeDialog}
          onDone={finishDialog}
        />
      )}
    </section>
  )
}
