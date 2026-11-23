import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { apiClient, ApiError } from '../api/client'
import { useAuth } from '../components/AuthProvider'
import { GpsFixTestPanel } from '../components/GpsFixTestPanel'
import { Banner, Button, Card, Select, Table, TextInput, Tile } from '../components/ui'
import { Timestamp } from '../components/Timestamp'
import { useFormatters } from '../lib/useFormatters'
import '../styles/shared.css'
import './TestingVisualizationPage.css'

// Types for test results
interface TestResultSummary {
  id: number
  device_id: string
  test_type: string
  status: string
  executed_at: string
  is_testing: boolean
  duration_ms: number | null
  error_message: string | null
}

interface TestResultsListResponse {
  results: TestResultSummary[]
  total: number
  page: number
  page_size: number
}

interface FailureBreakdownEntry {
  test_type: string
  error_message: string | null
  count: number
}

interface TestSummaryResponse {
  total_tests: number
  passed: number
  failed: number
  running: number
  skipped: number
  by_test_type: Record<string, Record<string, number>>
  recent_executions: Array<Record<string, string | number | null>>
  failures_by_type_and_message: FailureBreakdownEntry[]
}

// Test types and statuses
const TEST_TYPES = ['modem', 'gps', 'collector', 'uploader', 'heartbeat'] as const
const TEST_STATUSES = ['passed', 'failed', 'running', 'skipped'] as const

type TestType = typeof TEST_TYPES[number]
type TestStatus = typeof TEST_STATUSES[number]

// Helper functions
function formatDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return i18n.t('testing:notAvailable')
  if (ms < 1000) return i18n.t('testing:duration.milliseconds', { ms })
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return i18n.t('testing:duration.seconds', { seconds })
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return i18n.t('testing:duration.minutesSeconds', { minutes, seconds: remainingSeconds })
}

function statusBadgeClass(status: string): string {
  switch (status.toLowerCase()) {
    case 'passed':
      return 'status-badge status-badge--success'
    case 'failed':
      return 'status-badge status-badge--danger'
    case 'running':
      return 'status-badge status-badge--info'
    case 'skipped':
      return 'status-badge status-badge--info'
    default:
      return 'status-badge status-badge--info'
  }
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation('testing')
  return <span className={statusBadgeClass(status)}>{t(`status.${status}`, { defaultValue: status })}</span>
}

function TestTypeBadge({ testType }: { testType: string }) {
  const { t } = useTranslation('testing')
  return <span className="test-type-badge">{t(`testType.${testType}`, { defaultValue: testType })}</span>
}

// Summary Cards
function SummaryCard({ title, value, color }: { title: string; value: number | string; color: string }) {
  return (
    <Card className="summary-card">
      <div className="summary-card__title">{title}</div>
      <div className="summary-card__value" style={{ color }}>
        {value}
      </div>
    </Card>
  )
}

// Filter Controls
function FilterControls({
  filters,
  onFilterChange,
  deviceIdInput,
  onDeviceIdInputChange,
}: {
  filters: {
    test_type: TestType | ''
    status: TestStatus | ''
    device_id: string
    start_date: string
    end_date: string
  }
  onFilterChange: (name: string, value: string | TestType | TestStatus) => void
  deviceIdInput: string
  onDeviceIdInputChange: (value: string) => void
}) {
  const { t } = useTranslation('testing')
  return (
    <div className="filter-grid">
      <Select
        label={t('filters.testType')}
        value={filters.test_type}
        onChange={(e) => onFilterChange('test_type', e.target.value as TestType)}
      >
        <option value="">{t('filters.allTypes')}</option>
        {TEST_TYPES.map((type) => (
          <option key={type} value={type}>{t(`testType.${type}`)}</option>
        ))}
      </Select>

      <Select
        label={t('filters.status')}
        value={filters.status}
        onChange={(e) => onFilterChange('status', e.target.value as TestStatus)}
      >
        <option value="">{t('filters.allStatuses')}</option>
        {TEST_STATUSES.map((status) => (
          <option key={status} value={status}>{t(`status.${status}`)}</option>
        ))}
      </Select>

      <TextInput
        label={t('filters.deviceId')}
        type="text"
        value={deviceIdInput}
        onChange={(e) => onDeviceIdInputChange(e.target.value)}
        placeholder={t('filters.devicePlaceholder')}
      />

      <TextInput
        label={t('filters.startDate')}
        type="datetime-local"
        value={filters.start_date}
        onChange={(e) => onFilterChange('start_date', e.target.value)}
      />

      <TextInput
        label={t('filters.endDate')}
        type="datetime-local"
        value={filters.end_date}
        onChange={(e) => onFilterChange('end_date', e.target.value)}
      />
    </div>
  )
}

// Test Result Row
function TestResultRow({
  result,
  selected,
  onToggleSelected,
}: {
  result: TestResultSummary
  selected: boolean
  onToggleSelected: (id: number) => void
}) {
  const { t } = useTranslation('testing')
  return (
    <tr>
      <td>
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelected(result.id)}
          aria-label={t('selectResult', { id: result.id })}
        />
      </td>
      <td style={{ fontWeight: 600 }}>{result.id}</td>
      <td>
        <TestTypeBadge testType={result.test_type} />
      </td>
      <td>
        <StatusBadge status={result.status} />
      </td>
      <td>{result.device_id}</td>
      <td>{result.executed_at ? <Timestamp value={result.executed_at} /> : t('never')}</td>
      <td>{formatDuration(result.duration_ms)}</td>
      <td>
        <span className={result.is_testing ? 'status-badge status-badge--info' : 'status-badge status-badge--danger'}>
          {result.is_testing ? t('mode.testing') : t('mode.production')}
        </span>
      </td>
      <td className="test-result-row__error">{result.error_message || '—'}</td>
    </tr>
  )
}

// Test Results Table
function TestResultsTable({
  results,
  loading,
  error,
  selectedIds,
  onToggleSelected,
  onToggleSelectAll,
}: {
  results: TestResultSummary[]
  loading: boolean
  error: string | null
  selectedIds: Set<number>
  onToggleSelected: (id: number) => void
  onToggleSelectAll: () => void
}) {
  const { t } = useTranslation('testing')
  if (loading && results.length === 0) {
    return <p style={{ color: 'var(--muted)' }}>{t('loadingResults')}</p>
  }

  if (error) {
    return <Banner tone="danger" style={{ marginBottom: 'var(--space-4)' }}>{error}</Banner>
  }

  if (results.length === 0) {
    return <p style={{ color: 'var(--muted)' }}>{t('noResults')}</p>
  }

  const allOnPageSelected = results.every((result) => selectedIds.has(result.id))

  return (
    <Table>
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              checked={allOnPageSelected}
              onChange={onToggleSelectAll}
              aria-label={t('selectAll')}
            />
          </th>
          <th>{t('columns.id')}</th>
          <th>{t('columns.testType')}</th>
          <th>{t('columns.status')}</th>
          <th>{t('columns.device')}</th>
          <th>{t('columns.executedAt')}</th>
          <th>{t('columns.duration')}</th>
          <th>{t('columns.type')}</th>
          <th>{t('columns.errorMessage')}</th>
        </tr>
      </thead>
      <tbody>
        {results.map((result) => (
          <TestResultRow
            key={result.id}
            result={result}
            selected={selectedIds.has(result.id)}
            onToggleSelected={onToggleSelected}
          />
        ))}
      </tbody>
    </Table>
  )
}

// Summary Statistics Section
function SummaryStatistics({ summary }: { summary: TestSummaryResponse | null }) {
  const { t } = useTranslation('testing')
  const { formatDateTime } = useFormatters()
  if (!summary) {
    return <p style={{ color: 'var(--muted)' }}>{t('loadingSummary')}</p>
  }

  const passRate = summary.total_tests > 0
    ? ((summary.passed / summary.total_tests) * 100).toFixed(1)
    : '0'

  return (
    <div style={{ marginBottom: 'var(--space-5)' }}>
      <h2 className="section-title">{t('summary.title')}</h2>

      <div className="stat-grid">
        <SummaryCard title={t('summary.totalTests')} value={summary.total_tests} color="var(--text-h)" />
        <SummaryCard title={t('summary.passed')} value={summary.passed} color="var(--success-text)" />
        <SummaryCard title={t('summary.failed')} value={summary.failed} color="var(--danger)" />
        <SummaryCard title={t('summary.running')} value={summary.running} color="var(--accent)" />
        <SummaryCard title={t('summary.skipped')} value={summary.skipped} color="var(--muted)" />
        <SummaryCard title={t('summary.passRate')} value={`${passRate}%`} color="var(--success)" />
      </div>

      <div style={{ marginBottom: 'var(--space-5)' }}>
        <h3 className="subsection-title">{t('summary.byTestType')}</h3>
        <div className="filter-grid" style={{ marginBottom: 0 }}>
          {Object.entries(summary.by_test_type).map(([testType, stats]) => (
            <Tile key={testType}>
              <div className="test-type-summary__title">{t(`testType.${testType}`, { defaultValue: testType })}</div>
              <div className="test-type-summary__stats">
                <div>{t('summary.stats.total', { count: stats.total || 0 })}</div>
                <div style={{ color: 'var(--success-text)' }}>{t('summary.stats.passed', { count: stats.passed || 0 })}</div>
                <div style={{ color: 'var(--danger)' }}>{t('summary.stats.failed', { count: stats.failed || 0 })}</div>
                <div style={{ color: 'var(--accent)' }}>{t('summary.stats.running', { count: stats.running || 0 })}</div>
                <div style={{ color: 'var(--muted)' }}>{t('summary.stats.skipped', { count: stats.skipped || 0 })}</div>
              </div>
            </Tile>
          ))}
        </div>
      </div>

      <div style={{ marginBottom: 'var(--space-5)' }}>
        <h3 className="subsection-title">{t('summary.recentFailures')}</h3>
        {summary.failures_by_type_and_message.length > 0 ? (
          <Table>
            <thead>
              <tr>
                <th>{t('columns.testType')}</th>
                <th>{t('columns.errorMessage')}</th>
                <th>{t('summary.count')}</th>
              </tr>
            </thead>
            <tbody>
              {summary.failures_by_type_and_message.map((failure, index) => (
                <tr key={`${failure.test_type}-${index}`}>
                  <td>
                    <TestTypeBadge testType={failure.test_type} />
                  </td>
                  <td>{failure.error_message || '—'}</td>
                  <td>{failure.count}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <p style={{ color: 'var(--muted)' }}>{t('summary.noFailures')}</p>
        )}
      </div>

      <div>
        <h3 className="subsection-title">{t('summary.recentExecutions')}</h3>
        {summary.recent_executions.length > 0 ? (
          <div className="recent-executions-grid">
            {summary.recent_executions.map((exec) => (
              <Card key={exec.id as number} className="recent-execution-card">
                <div className="recent-execution-card__header">
                  <TestTypeBadge testType={exec.test_type as string} />
                  <StatusBadge status={exec.status as string} />
                </div>
                <div className="recent-execution-card__line">{t('summary.exec.device', { value: exec.device_id })}</div>
                <div className="recent-execution-card__line">
                  {t('summary.exec.executed', { value: exec.executed_at ? formatDateTime(exec.executed_at as string) : t('never') })}
                </div>
                <div className="recent-execution-card__line">
                  {t('summary.exec.duration', { value: formatDuration(exec.duration_ms as number | null) })}
                </div>
                {exec.error_message && (
                  <div className="recent-execution-card__line">{t('summary.exec.error', { value: exec.error_message })}</div>
                )}
              </Card>
            ))}
          </div>
        ) : (
          <p style={{ color: 'var(--muted)' }}>{t('summary.noExecutions')}</p>
        )}
      </div>
    </div>
  )
}

const PAGE_SIZE = 50
const DEVICE_ID_DEBOUNCE_MS = 400

// Main Page Component
export function TestingVisualizationPage() {
  const { t } = useTranslation('testing')
  const { user } = useAuth()
  const [results, setResults] = useState<TestResultSummary[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<TestSummaryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({
    test_type: '' as TestType | '',
    status: '' as TestStatus | '',
    device_id: '',
    start_date: '',
    end_date: '',
  })
  // Free-text device ID input is debounced into filters.device_id below,
  // rather than triggering a fetch on every keystroke.
  const [deviceIdInput, setDeviceIdInput] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const resultsAbortRef = useRef<AbortController | null>(null)
  const summaryAbortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const timeout = setTimeout(() => {
      setFilters((prev) => ({ ...prev, device_id: deviceIdInput }))
      setPage(1)
    }, DEVICE_ID_DEBOUNCE_MS)

    return () => clearTimeout(timeout)
  }, [deviceIdInput])

  const buildQueryParams = () => {
    const params: Record<string, string> = {}

    if (filters.test_type) params.test_type = filters.test_type
    if (filters.status) params.status = filters.status
    if (filters.device_id) params.device_id = filters.device_id
    // datetime-local values carry no timezone; convert the browser's local
    // wall-clock time to an absolute instant before sending it, since the
    // backend treats a bare (offset-less) datetime as UTC.
    if (filters.start_date) params.start_date = new Date(filters.start_date).toISOString()
    if (filters.end_date) params.end_date = new Date(filters.end_date).toISOString()
    params.page = String(page)
    params.page_size = String(PAGE_SIZE)

    return '?' + new URLSearchParams(params).toString()
  }

  const fetchResults = async () => {
    resultsAbortRef.current?.abort()
    const controller = new AbortController()
    resultsAbortRef.current = controller

    try {
      setLoading(true)
      setError(null)

      const queryParams = buildQueryParams()
      const response: TestResultsListResponse = await apiClient.get(
        `/testing/results${queryParams}`,
        { signal: controller.signal },
      )
      setResults(response.results)
      setTotal(response.total)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      if (err instanceof ApiError) {
        setError(t('errors.loadWithReason', { reason: err.message }))
      } else {
        setError(t('errors.load'))
      }
    } finally {
      if (resultsAbortRef.current === controller) {
        setLoading(false)
      }
    }
  }

  const fetchSummary = async () => {
    summaryAbortRef.current?.abort()
    const controller = new AbortController()
    summaryAbortRef.current = controller

    try {
      const response: TestSummaryResponse = await apiClient.get(
        '/testing/summary',
        { signal: controller.signal },
      )
      setSummary(response)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      // Summary fetch failed, but we can still show the page
      console.error('Failed to load summary:', err)
    }
  }

  useEffect(() => {
    fetchResults()
    fetchSummary()
  }, [filters, page])

  // Poll for updates every 30 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      fetchResults()
      fetchSummary()
    }, 30000)

    return () => clearInterval(interval)
  }, [filters, page])

  const handleFilterChange = (name: string, value: string | TestType | TestStatus) => {
    setFilters((prev) => ({
      ...prev,
      [name]: value,
    }))
    setPage(1)
  }

  const handleRefresh = async () => {
    await fetchResults()
    await fetchSummary()
  }

  const toggleSelected = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const toggleSelectAllOnPage = () => {
    setSelectedIds((prev) => {
      const allSelected = results.every((result) => prev.has(result.id))
      const next = new Set(prev)
      for (const result of results) {
        if (allSelected) {
          next.delete(result.id)
        } else {
          next.add(result.id)
        }
      }
      return next
    })
  }

  const handleDeleteSelected = async () => {
    if (selectedIds.size === 0) return
    const count = selectedIds.size
    if (!window.confirm(t('confirmDeleteSelected', { count }))) {
      return
    }

    setDeleting(true)
    setDeleteError(null)
    try {
      await Promise.all(Array.from(selectedIds).map((id) => apiClient.delete(`/testing/results/${id}`)))
      setSelectedIds(new Set())
      await fetchResults()
      await fetchSummary()
    } catch (err) {
      if (err instanceof ApiError) {
        setDeleteError(t('errors.deleteSelectedWithReason', { reason: err.message }))
      } else {
        setDeleteError(t('errors.deleteSelected'))
      }
    } finally {
      setDeleting(false)
    }
  }

  const handleDeleteAll = async () => {
    if (!window.confirm(t('confirmDeleteAll', { count: total }))) {
      return
    }

    setDeleting(true)
    setDeleteError(null)
    try {
      await apiClient.delete('/testing/results')
      setSelectedIds(new Set())
      setPage(1)
      await fetchResults()
      await fetchSummary()
    } catch (err) {
      if (err instanceof ApiError) {
        setDeleteError(t('errors.deleteAllWithReason', { reason: err.message }))
      } else {
        setDeleteError(t('errors.deleteAll'))
      }
    } finally {
      setDeleting(false)
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
        <Button onClick={handleRefresh} disabled={loading}>
          {t('refresh')}
        </Button>
      </div>

      {user?.is_superuser && <GpsFixTestPanel />}

      <SummaryStatistics summary={summary} />

      <FilterControls
        filters={filters}
        onFilterChange={handleFilterChange}
        deviceIdInput={deviceIdInput}
        onDeviceIdInputChange={setDeviceIdInput}
      />

      {error && <Banner tone="danger" style={{ marginBottom: 'var(--space-4)' }}>{error}</Banner>}

      <Card>
        <div className="page-header page-header--row" style={{ marginBottom: 'var(--space-3)' }}>
          <h2 className="subsection-title" style={{ marginBottom: 0 }}>{t('results')}</h2>
          <div className="admin-row__actions">
            <Button
              variant="danger"
              size="sm"
              onClick={handleDeleteSelected}
              disabled={deleting || selectedIds.size === 0}
            >
              {t('deleteSelected', { count: selectedIds.size })}
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={handleDeleteAll}
              disabled={deleting || total === 0}
            >
              {t('deleteAll')}
            </Button>
          </div>
        </div>

        {deleteError && <Banner tone="danger" style={{ marginBottom: 'var(--space-4)' }}>{deleteError}</Banner>}

        <TestResultsTable
          results={results}
          loading={loading}
          error={error}
          selectedIds={selectedIds}
          onToggleSelected={toggleSelected}
          onToggleSelectAll={toggleSelectAllOnPage}
        />

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
