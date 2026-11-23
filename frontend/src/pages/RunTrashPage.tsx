import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import i18n from '../i18n'
import { fetchTrashedRuns, restoreRun, runLabel, type TrashedRun } from '../api/runs'
import { DeleteRunPermanentlyDialog } from '../components/RunDialogs'
import { Banner, Button, Card, Table } from '../components/ui'
import { Timestamp } from '../components/Timestamp'
import '../styles/shared.css'
import './RunsPage.css'

const PAGE_SIZE = 25
const COLUMN_COUNT = 10

export function RunTrashPage() {
  const { t } = useTranslation('runTrash')
  const [page, setPage] = useState(1)
  const [runs, setRuns] = useState<TrashedRun[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [restoringId, setRestoringId] = useState<number | null>(null)
  const [deleting, setDeleting] = useState<TrashedRun | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    fetchTrashedRuns(page, PAGE_SIZE, controller.signal)
      .then((response) => {
        setRuns(response.runs)
        setTotal(response.total)
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(i18n.t('runTrash:loadFailed'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [page, reloadKey])

  // Removing the last run of a page leaves it empty, so step back to the previous one
  const reloadAfterRemoving = () => {
    if (runs.length === 1 && page > 1) setPage(page - 1)
    setReloadKey((key) => key + 1)
  }

  const restore = async (run: TrashedRun) => {
    setRestoringId(run.id)
    setError(null)
    try {
      await restoreRun(run.id)
      reloadAfterRemoving()
    } catch {
      setError(t('restoreFailed'))
    } finally {
      setRestoringId(null)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <section>
      <div className="page-header page-header--row">
        <div>
          <h1 className="page-header__title">{t('title')}</h1>
          <p className="page-header__subtitle">{t('subtitle')}</p>
        </div>
        <Link to="/runs" className="ui-button ui-button--secondary ui-button--sm">
          {t('backToRuns')}
        </Link>
      </div>

      {error && <Banner tone="danger" style={{ marginBottom: 'var(--space-4)' }}>{error}</Banner>}

      <Card>
        <Table>
          <thead>
            <tr>
              <th>{t('columns.run')}</th>
              <th>{t('columns.device')}</th>
              <th>{t('columns.mission')}</th>
              <th>{t('columns.start')}</th>
              <th>{t('columns.points')}</th>
              <th>{t('columns.latencyResults')}</th>
              <th>{t('columns.campaign')}</th>
              <th>{t('columns.deletedAt')}</th>
              <th>{t('columns.deletedBy')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td className="runs-table__run-id">
                  {runLabel(run)}
                  {run.name != null && <div className="runs-table__device-run-id">{run.run_id}</div>}
                </td>
                <td>{run.device_id}</td>
                <td>{t(`missionType.${run.mission_type}`, { ns: 'common', defaultValue: run.mission_type })}</td>
                <td>{run.start == null ? '–' : <Timestamp value={run.start} />}</td>
                <td className="runs-table__numeric">{run.point_count}</td>
                <td className="runs-table__numeric">{run.latency_result_count}</td>
                <td>{run.campaign_name ?? '–'}</td>
                <td><Timestamp value={run.deleted_at} /></td>
                <td>{run.deleted_by_email ?? '–'}</td>
                <td className="runs-table__actions">
                  <Button
                    variant="secondary"
                    size="sm"
                    aria-label={t('restoreRun', { run: runLabel(run) })}
                    disabled={restoringId === run.id}
                    onClick={() => restore(run)}
                  >
                    {t('restore')}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    aria-label={t('deleteRunPermanently', { run: runLabel(run) })}
                    onClick={() => setDeleting(run)}
                  >
                    {t('deletePermanently')}
                  </Button>
                </td>
              </tr>
            ))}
            {!loading && runs.length === 0 && (
              <tr>
                <td colSpan={COLUMN_COUNT}>{t('empty')}</td>
              </tr>
            )}
            {loading && (
              <tr>
                <td colSpan={COLUMN_COUNT}>{t('loading', { ns: 'common' })}</td>
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

      {deleting && (
        <DeleteRunPermanentlyDialog
          run={deleting}
          onClose={() => setDeleting(null)}
          onDone={() => {
            setDeleting(null)
            reloadAfterRemoving()
          }}
        />
      )}
    </section>
  )
}
