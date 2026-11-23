import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { apiClient, ApiError } from '../api/client'
import { queueCommand, type CommandStatusItem, type OneShotCommand } from '../api/commands'
import { listDevices, type DeviceSummary } from '../api/devices'
import { openHeartbeatStream } from '../api/heartbeatStream'
import { useAuth } from '../components/AuthProvider'
import { CommandStatusList, commandStateLabel } from '../components/CommandStatusList'
import { DeleteShownButton } from '../components/DeleteShownButton'
import { DeviceSelector } from '../components/DeviceSelector'
import { useToast } from '../components/ToastProvider'
import { Banner, Button, Card, ConfirmDialog, Tile } from '../components/ui'
import { commandLabel } from '../lib/commandLabel'
import { useCommandStatus, type UseCommandStatus } from '../lib/useCommandStatus'
import { RelativeTime } from '../components/RelativeTime'
import { Timestamp } from '../components/Timestamp'
import { useFormatters } from '../lib/useFormatters'
import '../styles/shared.css'
import './MissionStatusPage.css'

interface GpsFixStatus {
  has_fix: boolean
  num_satellites: number | null
  fix_age_s: number | null
}

interface CriticalError {
  fingerprint: string | null
  same_error_count: number
  consecutive_reboots: number
  action: string
}

interface DeviceHeartbeatSummary {
  device_id: string
  received_at: string
  datapoints_total: number
  datapoints_valid: number
  datapoints_invalid: number
  pipeline_broken: boolean
  storage_pending_files: number
  storage_disk_free_bytes: number
  // Absent on older device builds that predate run-phase/GPS-fix reporting, or before a
  // device's first heartbeat under the new contract.
  run_phase?: string | null
  gps_fix?: GpsFixStatus | null
  // Derived server-side from the device's reported config, so it is available to every caller;
  // anything other than manual/auto (including absent) means the mode is unknown.
  system_mode?: string | null
  // Superuser-only (null for everyone else): the fingerprint carries internal function names.
  // Present for the `critical_error` and `recovery_idle` phases.
  critical_error?: CriticalError | null
}

interface HeartbeatListResponse {
  heartbeats: DeviceHeartbeatSummary[]
}

// Declared order of `RunPhase` (app/schemas/heartbeat.py). Rendering from this fixed list,
// rather than echoing `run_phase` verbatim, means an unknown value highlights no node.
const RUN_PHASES = [
  'recovering_pending_data',
  'waiting_for_gps_fix',
  'waiting_for_movement',
  'manual_mode_idle',
  'active_measuring',
  'finalizing',
  'done',
] as const

// Phases that are no pipeline step; they only show in the state tile.
const TRANSITION_PHASES = ['starting_up', 'stopping'] as const

// Device lifecycle states, not a step of the measurement-run pipeline above -
// shown as a banner instead of a pipeline node, since none of RUN_PHASES' nodes apply. A Map
// (not a plain object) so an unrecognized run_phase like "__proto__" can't accidentally look up
// an inherited property instead of missing outright, same as in CommandAckNotifications.
const SHUTDOWN_REBOOT_MESSAGE_KEYS = new Map([
  ['shutting_down', 'shuttingDownBanner'],
  ['rebooting', 'rebootingBanner'],
])

const CRITICAL_ERROR_PHASE = 'critical_error'
const RECOVERY_PHASE = 'recovery_idle'

// Every phase with a `phase.*` translation; a Set for the same prototype-lookup reason as above.
const KNOWN_PHASES = new Set<string>([
  ...RUN_PHASES,
  ...TRANSITION_PHASES,
  ...SHUTDOWN_REBOOT_MESSAGE_KEYS.keys(),
  CRITICAL_ERROR_PHASE,
  RECOVERY_PHASE,
])

const POLL_INTERVAL_MS = 30000

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function GpsFixSummary({ gpsFix, receivedAtMs }: { gpsFix: GpsFixStatus | null | undefined; receivedAtMs: number }) {
  const { t } = useTranslation('missionStatus')
  if (!gpsFix) return <>{t('gps.unknown')}</>

  const summary = [gpsFix.has_fix ? t('gps.fixAcquired') : t('gps.noFix')]
  if (gpsFix.num_satellites != null) summary.push(t('gps.sats', { count: gpsFix.num_satellites }))
  // fix_age_s was measured on the device when it sent the heartbeat, so it keeps ageing
  // from received_at onward.
  const fixedAtMs = gpsFix.fix_age_s != null ? receivedAtMs - gpsFix.fix_age_s * 1000 : null
  return (
    <>
      {summary.join(', ')}
      {fixedAtMs != null && (
        <>
          {', '}
          <RelativeTime since={fixedAtMs} />
        </>
      )}
    </>
  )
}

function CrashDetailsBanner({
  tone,
  message,
  criticalError,
}: {
  tone: 'danger' | 'warning'
  message: string
  criticalError: CriticalError | null | undefined
}) {
  const { t } = useTranslation('missionStatus')
  return (
    <Banner tone={tone} role={tone === 'danger' ? 'alert' : 'status'}>
      <strong>{message}</strong>
      {criticalError && (
        <>
          <span className="mission-critical-error__detail">
            {t('criticalErrorDetails', {
              count: criticalError.same_error_count,
              reboots: criticalError.consecutive_reboots,
              action: criticalError.action,
            })}
          </span>
          {criticalError.fingerprint && (
            <span className="mission-critical-error__detail mission-critical-error__fingerprint">
              {criticalError.fingerprint}
            </span>
          )}
        </>
      )}
    </Banner>
  )
}

function PhasePipeline({ runPhase }: { runPhase: string | null | undefined }) {
  const { t } = useTranslation('missionStatus')
  return (
    <ol className="phase-pipeline" aria-label={t('runPhase')}>
      {RUN_PHASES.map((phase) => {
        const current = phase === runPhase
        return (
          <li
            key={phase}
            className={current ? 'phase-pipeline__node phase-pipeline__node--current' : 'phase-pipeline__node'}
            aria-current={current ? 'step' : undefined}
          >
            {t(`phase.${phase}`)}
          </li>
        )
      })}
    </ol>
  )
}

function ValidityGauge({ valid, invalid }: { valid: number; invalid: number }) {
  const { t } = useTranslation('missionStatus')
  const total = valid + invalid
  const validPct = total === 0 ? 0 : Math.round((valid / total) * 100)
  const label = total === 0 ? t('gauge.empty') : t('gauge.summary', { valid: validPct, invalid: 100 - validPct })

  return (
    <svg className="validity-gauge" viewBox="0 0 100 56" role="img" aria-label={label}>
      <path className="validity-gauge__track" d="M 10 50 A 40 40 0 0 1 90 50" pathLength={100} />
      <path
        className="validity-gauge__valid"
        d="M 10 50 A 40 40 0 0 1 90 50"
        pathLength={100}
        strokeDasharray={`${validPct} 100`}
      />
      <text className="validity-gauge__text" x="50" y="48" textAnchor="middle">
        {total === 0 ? '–' : `${validPct}%`}
      </text>
    </svg>
  )
}

function StatTile({ label, children, tone }: { label: string; children: React.ReactNode; tone?: 'danger' | 'success' | 'critical' }) {
  return (
    <Tile className="mission-tile">
      <span className="mission-tile__label">{label}</span>
      <span className={tone ? `mission-tile__value mission-tile__value--${tone}` : 'mission-tile__value'}>{children}</span>
    </Tile>
  )
}

type DeviceMode = 'manual' | 'auto'

function reportedMode(systemMode: string | null | undefined): DeviceMode | null {
  return systemMode === 'manual' || systemMode === 'auto' ? systemMode : null
}

function StateTile({ runPhase }: { runPhase: string | null | undefined }) {
  const { t } = useTranslation('missionStatus')
  if (!runPhase) return <StatTile label={t('tiles.state')}>{t('tiles.noValue')}</StatTile>
  const label = KNOWN_PHASES.has(runPhase) ? t(`phase.${runPhase}`) : runPhase
  return (
    <StatTile label={t('tiles.state')} tone={runPhase === CRITICAL_ERROR_PHASE ? 'critical' : undefined}>
      {label}
    </StatTile>
  )
}

function ModeTile({ mode }: { mode: DeviceMode | null }) {
  const { t } = useTranslation('missionStatus')
  return <StatTile label={t('tiles.mode')}>{mode ? t(`mode.${mode}`) : t('tiles.noValue')}</StatTile>
}

interface CommandAction {
  // Key under `commands.` in the missionStatus translations (the description).
  key: string
  command: OneShotCommand
  danger?: boolean
  // Only set for the mode switch, whose dialog offers to queue a reboot right after.
  offersReboot?: boolean
}

const START_ACTION: CommandAction = {
  key: 'start',
  command: 'start-measuring-now',
}
const STOP_ACTION: CommandAction = {
  key: 'stop',
  command: 'stop-measuring-now',
}
const FORCE_UPLOAD_ACTION: CommandAction = {
  key: 'forceUpload',
  command: 'force-upload-now',
}
const REBOOT_ACTION: CommandAction = {
  key: 'reboot',
  command: 'reboot-now',
  danger: true,
}
const SHUTDOWN_ACTION: CommandAction = {
  key: 'shutdown',
  command: 'shutdown-now',
  danger: true,
}

function modeSwitchAction(targetMode: DeviceMode): CommandAction {
  return {
    key: targetMode === 'auto' ? 'switchToAuto' : 'switchToManual',
    command: targetMode === 'auto' ? 'mode-auto-now' : 'mode-manual-now',
    offersReboot: true,
  }
}

// Every command a button on this page can queue; the timeline lists exactly these, so a new
// button shows up there without a second list to keep in sync.
const REMOTE_COMMAND_ACTIONS: CommandAction[] = [
  START_ACTION,
  STOP_ACTION,
  FORCE_UPLOAD_ACTION,
  REBOOT_ACTION,
  SHUTDOWN_ACTION,
  modeSwitchAction('auto'),
  modeSwitchAction('manual'),
]
const REMOTE_COMMAND_NAMES: string[] = REMOTE_COMMAND_ACTIONS.map((action) => action.command)

const COMMAND_STATUS_ITEM_LIMIT = 5
const COMMAND_STATUS_OPEN_KEY = 'mission-status.command-status-open'

function readStoredOpen(): boolean {
  try {
    return localStorage.getItem(COMMAND_STATUS_OPEN_KEY) === 'true'
  } catch {
    return false
  }
}

function storeOpen(open: boolean) {
  try {
    localStorage.setItem(COMMAND_STATUS_OPEN_KEY, String(open))
  } catch {
    // The flag is a convenience; without storage the section just starts collapsed next time.
  }
}

function commandStatusSummary(item: CommandStatusItem | undefined): string {
  if (!item) return i18n.t('missionStatus:commandStatus.empty')
  return `${commandLabel(item.name)} - ${commandStateLabel(item)}`
}

function CommandStatusPanel({
  deviceId,
  commandStatus,
  open,
  onToggle,
}: {
  deviceId: string
  commandStatus: UseCommandStatus
  open: boolean
  onToggle: () => void
}) {
  const { t } = useTranslation('missionStatus')
  const items = commandStatus.items
    .filter((item) => REMOTE_COMMAND_NAMES.includes(item.name))
    .slice(0, COMMAND_STATUS_ITEM_LIMIT)

  return (
    <details className="mission-command-status" open={open}>
      <summary
        className="mission-command-status__summary"
        onClick={(event) => {
          // Controlled, so a queued command can also open it without the browser fighting the state.
          event.preventDefault()
          onToggle()
        }}
      >
        {t('commandStatus.title')}
        <span className="mission-command-status__latest"> - {commandStatusSummary(items[0])}</span>
      </summary>
      {commandStatus.error && <Banner tone="danger">{commandStatus.error}</Banner>}
      {items.length > 0 && (
        <>
          <div className="mission-command-status__actions">
            <DeleteShownButton
              deviceId={deviceId}
              shown={items}
              onDeleted={() => commandStatus.refresh({ silent: true })}
            />
          </div>
          <CommandStatusList
            items={items}
            names={REMOTE_COMMAND_NAMES}
            heartbeat={commandStatus.heartbeat ?? undefined}
            onShutdownDue={() => commandStatus.refresh({ silent: true })}
          />
        </>
      )}
    </details>
  )
}

// Gating is only applied once the device reports what it needs: older device builds that omit
// `run_phase` or `mode` keep the buttons enabled rather than locking them out.
function canStartMeasuring(mode: DeviceMode | null, runPhase: string | null | undefined): boolean {
  if (mode === null || runPhase == null) return true
  if (runPhase === RECOVERY_PHASE) return true
  return mode === 'manual' && runPhase === 'manual_mode_idle'
}

function canStopMeasuring(runPhase: string | null | undefined): boolean {
  return runPhase == null || runPhase === 'active_measuring'
}

function describeQueueFailure(err: unknown): string {
  return err instanceof ApiError
    ? i18n.t('missionStatus:queueFailedWithReason', { reason: err.message })
    : i18n.t('missionStatus:queueFailed')
}

function DeviceCommands({ heartbeat, online }: { heartbeat: DeviceHeartbeatSummary; online: boolean }) {
  const { user } = useAuth()
  const { showToast } = useToast()
  const { t } = useTranslation('missionStatus')
  const [pending, setPending] = useState<CommandAction | null>(null)
  const [rebootAfterwards, setRebootAfterwards] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [dialogError, setDialogError] = useState<string | null>(null)
  const [statusOpen, setStatusOpen] = useState(readStoredOpen)

  // Queuing and the status endpoint are superuser-only server-side; this only avoids rendering
  // buttons that would be rejected, and keeps the hook from requesting anything for other users.
  const isSuperuser = !!user?.is_superuser
  const commandStatus = useCommandStatus(heartbeat.device_id, { enabled: isSuperuser })
  if (!isSuperuser) return null

  const mode = reportedMode(heartbeat.system_mode)
  const modeActions = mode === null ? [modeSwitchAction('auto'), modeSwitchAction('manual')] : [modeSwitchAction(mode === 'auto' ? 'manual' : 'auto')]
  const startEnabled = canStartMeasuring(mode, heartbeat.run_phase)
  const stopEnabled = canStopMeasuring(heartbeat.run_phase)

  function openDialog(action: CommandAction) {
    setPending(action)
    setRebootAfterwards(false)
    setDialogError(null)
  }

  async function confirm() {
    if (!pending) return
    const alsoReboot = pending.offersReboot === true && rebootAfterwards
    setSubmitting(true)
    setDialogError(null)
    try {
      await queueCommand(heartbeat.device_id, { command: pending.command })
    } catch (err) {
      setDialogError(describeQueueFailure(err))
      setSubmitting(false)
      return
    }
    setStatusOpen(true)
    commandStatus.refresh({ silent: true })
    // Queued strictly after the mode row, so the heartbeat's created_at/id ordering delivers the
    // reboot second and the device applies the mode switch before rebooting.
    if (alsoReboot) {
      try {
        await queueCommand(heartbeat.device_id, { command: REBOOT_ACTION.command })
      } catch (err) {
        showToast({
          tone: 'danger',
          message: t('modeSwitchRebootFailed', { reason: describeQueueFailure(err) }),
        })
        setPending(null)
        setSubmitting(false)
        return
      }
    }
    commandStatus.refresh({ silent: true })
    showToast({ tone: 'success', message: t('queued') })
    setPending(null)
    setSubmitting(false)
  }

  function toggleStatus() {
    storeOpen(!statusOpen)
    setStatusOpen(!statusOpen)
  }

  const buttons: { action: CommandAction; disabled?: boolean }[] = [
    { action: START_ACTION, disabled: !startEnabled },
    { action: STOP_ACTION, disabled: !stopEnabled },
    { action: FORCE_UPLOAD_ACTION },
    { action: REBOOT_ACTION },
    { action: SHUTDOWN_ACTION },
    ...modeActions.map((action) => ({ action })),
  ]

  return (
    <>
      <h3 className="mission-section-title">{t('remoteCommands')}</h3>
      <div className="mission-commands" role="group" aria-label={t('remoteCommands')}>
        {buttons.map(({ action, disabled }) => (
          <Button
            key={action.command}
            variant="secondary"
            disabled={disabled}
            title={action.command}
            onClick={() => openDialog(action)}
          >
            {commandLabel(action.command)}
          </Button>
        ))}
      </div>
      <CommandStatusPanel deviceId={heartbeat.device_id} commandStatus={commandStatus} open={statusOpen} onToggle={toggleStatus} />
      {pending && (
        <ConfirmDialog
          title={t('confirmTitle', { action: commandLabel(pending.command), deviceId: heartbeat.device_id })}
          confirmLabel={t('confirm')}
          confirmVariant={pending.danger ? 'danger' : 'primary'}
          submitting={submitting}
          onCancel={() => setPending(null)}
          onConfirm={confirm}
        >
          <p>{t(`commands.${pending.key}.description`)}</p>
          {pending.offersReboot && (
            <label className="mission-commands__checkbox">
              <input
                type="checkbox"
                checked={rebootAfterwards}
                disabled={submitting}
                onChange={(event) => setRebootAfterwards(event.target.checked)}
              />
              {t('rebootAfterwards')}
            </label>
          )}
          {!online && (
            <p className="mission-commands__hint">
              {t('offlineHint')}
            </p>
          )}
          {dialogError && <Banner tone="danger">{dialogError}</Banner>}
        </ConfirmDialog>
      )}
    </>
  )
}

function DeviceDetail({ heartbeat, online }: { heartbeat: DeviceHeartbeatSummary; online: boolean }) {
  const { t } = useTranslation('missionStatus')
  const { formatNumber } = useFormatters()
  const receivedAtMs = new Date(heartbeat.received_at).getTime()
  const valid = heartbeat.datapoints_valid
  const invalid = heartbeat.datapoints_invalid

  const shutdownOrRebootMessageKey = heartbeat.run_phase ? SHUTDOWN_REBOOT_MESSAGE_KEYS.get(heartbeat.run_phase) : undefined

  return (
    <Card>
      {heartbeat.run_phase === CRITICAL_ERROR_PHASE ? (
        <CrashDetailsBanner tone="danger" message={t('criticalErrorBanner')} criticalError={heartbeat.critical_error} />
      ) : heartbeat.run_phase === RECOVERY_PHASE ? (
        <CrashDetailsBanner tone="warning" message={t('recoveryBanner')} criticalError={heartbeat.critical_error} />
      ) : shutdownOrRebootMessageKey ? (
        <Banner tone="warning">{t(shutdownOrRebootMessageKey)}</Banner>
      ) : (
        <PhasePipeline runPhase={heartbeat.run_phase} />
      )}

      <div className="mission-grid">
        <StatTile label={t('tiles.latestHeartbeat')}>
          <Timestamp value={heartbeat.received_at} />
          <span className="mission-tile__sub"><RelativeTime since={receivedAtMs} /></span>
        </StatTile>
        <StatTile label={t('tiles.gpsFix')}><GpsFixSummary gpsFix={heartbeat.gps_fix} receivedAtMs={receivedAtMs} /></StatTile>
        <StateTile runPhase={heartbeat.run_phase} />
        <ModeTile mode={reportedMode(heartbeat.system_mode)} />
      </div>

      <h3 className="mission-section-title">{t('datapoints')}</h3>
      <div className="mission-datapoints">
        <ValidityGauge valid={valid} invalid={invalid} />
        <div className="mission-grid">
          <StatTile label={t('tiles.total')}>{formatNumber(heartbeat.datapoints_total)}</StatTile>
          <StatTile label={t('tiles.valid')} tone="success">{formatNumber(valid)}</StatTile>
          <StatTile label={t('tiles.invalid')} tone="danger">{formatNumber(invalid)}</StatTile>
        </div>
      </div>

      <div className="mission-grid">
        <StatTile label={t('tiles.pendingFiles')}>{formatNumber(heartbeat.storage_pending_files)}</StatTile>
        <StatTile label={t('tiles.diskFree')}>{formatBytes(heartbeat.storage_disk_free_bytes)}</StatTile>
      </div>

      <DeviceCommands heartbeat={heartbeat} online={online} />
    </Card>
  )
}

export function MissionStatusPage() {
  const { t } = useTranslation('missionStatus')
  const [devices, setDevices] = useState<DeviceSummary[]>([])
  const [heartbeats, setHeartbeats] = useState<DeviceHeartbeatSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [streamConnected, setStreamConnected] = useState(false)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const [deviceList, heartbeatList] = await Promise.all([
        listDevices(),
        apiClient.get<HeartbeatListResponse>('/heartbeat'),
      ])
      setDevices(deviceList.devices)
      setHeartbeats(heartbeatList.heartbeats)
    } catch (err) {
      setError(err instanceof ApiError ? i18n.t('missionStatus:loadFailedWithReason', { reason: err.message }) : i18n.t('missionStatus:loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Polling is only the fallback: while the heartbeat stream is open, its events trigger the reload.
  useEffect(() => {
    if (streamConnected) return
    const interval = setInterval(load, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [load, streamConnected])

  useEffect(() => {
    if (selectedId === null) return
    const closeStream = openHeartbeatStream(selectedId, {
      onHeartbeat: (event) => {
        if (event.device_id === selectedId) load()
      },
      onConnectionChange: setStreamConnected,
    })
    return () => {
      closeStream()
      setStreamConnected(false)
    }
  }, [selectedId, load])

  const selectedHeartbeat = heartbeats.find((heartbeat) => heartbeat.device_id === selectedId)
  const selectedOnline = devices.find((device) => device.device_id === selectedId)?.online ?? false

  return (
    <section>
      <div className="page-header page-header--row">
        <h1 className="page-header__title">{t('title')}</h1>
        <Button onClick={load} disabled={loading}>
          {t('refresh')}
        </Button>
      </div>

      {error && <div className="ui-banner ui-banner--danger" style={{ marginBottom: 'var(--space-4)' }}>{error}</div>}

      {loading && devices.length === 0 ? (
        <p>{t('loading')}</p>
      ) : devices.length === 0 ? (
        !error && <p style={{ color: 'var(--muted)' }}>{t('noDevices')}</p>
      ) : (
        <>
          <DeviceSelector devices={devices} selectedId={selectedId} onSelect={setSelectedId} />
          {selectedId === null ? (
            <p style={{ color: 'var(--muted)' }}>{t('selectDevice')}</p>
          ) : selectedHeartbeat ? (
            <DeviceDetail heartbeat={selectedHeartbeat} online={selectedOnline} />
          ) : (
            <p style={{ color: 'var(--muted)' }}>{t('noHeartbeat', { deviceId: selectedId })}</p>
          )}
        </>
      )}
    </section>
  )
}
