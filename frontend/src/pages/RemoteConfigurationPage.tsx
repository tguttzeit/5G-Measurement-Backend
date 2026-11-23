import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { apiClient, ApiError } from '../api/client'
import { DEFAULT_DEVICE_ID, listDevices, type DeviceSummary } from '../api/devices'
import {
  clearQueue,
  listCommandLog,
  queueCommand,
  getConfigSchema,
  queueConfigOverrides,
  SELFTEST_COMMAND,
  selftestResultsAction,
  type CommandLogItem,
  type CommandPayload,
  type ConfigOverridePayload,
  type ConfigSchemaGroup,
  type OneShotCommand,
  type CommandStatusItem,
  type CommandStatusResponse,
} from '../api/commands'
import { getFavoriteConfigFields, putFavoriteConfigFields } from '../api/favoriteConfigFields'
import { openCommandAckStream } from '../api/commandAckStream'
import { openHeartbeatStream } from '../api/heartbeatStream'
import { CommandStatusList } from '../components/CommandStatusList'
import { DeleteShownButton } from '../components/DeleteShownButton'
import { useToast } from '../components/ToastProvider'
import { commandLabel } from '../lib/commandLabel'
import {
  buildPayload,
  configFieldLabel,
  fieldInputError,
  formatConfigValue,
  riskyEntries,
  softWarnings,
  type ConfigInputs,
} from '../lib/configOverrides'
import { useCommandStatus } from '../lib/useCommandStatus'
import { ConfigOverridesForm } from '../components/ConfigOverridesForm'
import { DeviceSelector } from '../components/DeviceSelector'
import { Banner, Button, Card, ConfirmDialog, Table } from '../components/ui'
import { Timestamp } from '../components/Timestamp'
import '../styles/shared.css'
import './RemoteConfigurationPage.css'

// Mirrors app/schemas/heartbeat.py's DeviceHeartbeatSummary - only the fields this page uses.
interface DeviceHeartbeatSummary {
  current_config: Record<string, unknown> | null
}

const ONE_SHOT_COMMANDS: OneShotCommand[] = [
  'force-upload-now',
  'shutdown-now',
  'sim-reset-now',
  'mode-manual-now',
  'mode-auto-now',
  'start-measuring-now',
  'run-selftest-now',
  'stop-measuring-now',
  'reboot-now',
  'promote-overrides-now',
]

const COMMS_STATUS_COLOR: Record<string, string> = {
  failed: 'var(--danger)',
  not_applicable: 'var(--danger)',
  queued: 'var(--muted)',
  received: 'var(--muted)',
}

interface QueuedCommand extends CommandPayload {
  key: string
}

interface ValidationIssue {
  loc?: unknown[]
  msg?: unknown
}

// A 422 lists one issue per rejected field: show which field and which constraint it broke.
function validationMessage(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null
  const messages = (detail as ValidationIssue[])
    .filter((issue) => typeof issue?.msg === 'string')
    .map((issue) => {
      const field = Array.isArray(issue.loc) ? issue.loc[issue.loc.length - 1] : undefined
      return typeof field === 'string' ? `${configFieldLabel(field)}: ${issue.msg}` : String(issue.msg)
    })
  return messages.length > 0 ? messages.join('; ') : null
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    return validationMessage(detail) ?? fallback
  }
  return fallback
}

function OneShotCommandsForm({ onAdd }: { onAdd: (command: QueuedCommand) => void }) {
  const { t } = useTranslation('remoteConfiguration')
  return (
    <section className="remote-config__section">
      <h2 className="remote-config__section-title">{t('oneShot.title')}</h2>
      <div className="remote-config__commands" role="group" aria-label={t('oneShot.title')}>
        {ONE_SHOT_COMMANDS.map((command) => (
          <Button
            key={command}
            variant="secondary"
            title={command}
            onClick={() => onAdd({ key: crypto.randomUUID(), command })}
          >
            {commandLabel(command)}
          </Button>
        ))}
      </div>
    </section>
  )
}

function CommandStatusSection({
  deviceId,
  loading,
  error,
  items,
  heartbeat,
  onClearQueue,
  onShutdownDue,
  onDeleted,
}: {
  deviceId: string
  loading: boolean
  error: string | null
  items: CommandStatusItem[]
  heartbeat: CommandStatusResponse | null
  onClearQueue: () => void
  onShutdownDue: () => void
  onDeleted: () => void
}) {
  const { t } = useTranslation('remoteConfiguration')
  const queuedCount = items.filter((item) => item.in_queue).length
  return (
    <section className="remote-config__section">
      <div className="remote-config__section-header">
        <h2 className="remote-config__section-title">{t('status.title')}</h2>
        <div className="remote-config__section-actions">
          <DeleteShownButton deviceId={deviceId} shown={items} onDeleted={onDeleted} />
          <Button variant="secondary" onClick={onClearQueue} disabled={loading || queuedCount === 0}>
            {t('status.removeQueued')}
          </Button>
        </div>
      </div>
      {error && <p className="remote-config__error">{error}</p>}
      {loading && items.length === 0 ? (
        <p style={{ color: 'var(--muted)' }}>{t('status.loading')}</p>
      ) : items.length === 0 ? (
        <p style={{ color: 'var(--muted)' }}>{t('status.empty')}</p>
      ) : (
        <CommandStatusList
          items={items}
          heartbeat={heartbeat ?? undefined}
          onShutdownDue={onShutdownDue}
        />
      )}
    </section>
  )
}

function CommandCommsSection({
  entries,
  error,
  showAllDevices,
  onShowAllDevicesChange,
}: {
  entries: CommandLogItem[]
  error: string | null
  showAllDevices: boolean
  onShowAllDevicesChange: (showAll: boolean) => void
}) {
  const { t } = useTranslation('remoteConfiguration')
  return (
    <Card className="remote-config__card">
      <details>
        <summary className="remote-config__comms-summary">
          {t('comms.title', { count: entries.length })}
        </summary>
        <div className="remote-config__comms-body">
          <p className="remote-config__hint">
            {t('comms.hint')}
          </p>
          <div className="remote-config__comms-toolbar">
            <label>
              <input
                type="checkbox"
                checked={showAllDevices}
                onChange={(e) => onShowAllDevicesChange(e.target.checked)}
              />{' '}
              {t('comms.allDevices')}
            </label>
          </div>
          {error && <p className="remote-config__error">{error}</p>}
          {entries.length === 0 ? (
            <p style={{ color: 'var(--muted)' }}>{t('comms.empty')}</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>{t('comms.columns.time')}</th>
                  <th>{t('comms.columns.device')}</th>
                  <th>{t('comms.columns.direction')}</th>
                  <th>{t('comms.columns.type')}</th>
                  <th>{t('comms.columns.name')}</th>
                  <th>{t('comms.columns.id')}</th>
                  <th>{t('comms.columns.status')}</th>
                  <th>{t('comms.columns.detail')}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id}>
                    <td><Timestamp value={e.occurred_at} /></td>
                    <td>{e.device_id}</td>
                    <td>{e.direction === 'to_device' ? t('comms.toDevice') : t('comms.fromDevice')}</td>
                    <td>{e.kind}</td>
                    <td title={e.name}>{e.kind === 'command' ? commandLabel(e.name) : e.name}</td>
                    <td>{e.command_id ?? '—'}</td>
                    <td style={{ color: COMMS_STATUS_COLOR[e.status] }}>{e.status}</td>
                    <td>{e.detail ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      </details>
    </Card>
  )
}

function ClearQueueConfirmModal({
  deviceId,
  entryCount,
  submitting,
  onCancel,
  onConfirm,
}: {
  deviceId: string
  entryCount: number
  submitting: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation('remoteConfiguration')
  return (
    <ConfirmDialog
      title={t('clearQueue.title', { deviceId })}
      confirmLabel={t('status.removeQueued')}
      submittingLabel={t('clearQueue.removing')}
      confirmVariant="danger"
      submitting={submitting}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <p>{t('clearQueue.body', { count: entryCount })}</p>
    </ConfirmDialog>
  )
}

function configChangeText(
  t: (key: string, options: Record<string, string>) => string,
  field: string,
  value: ConfigOverridePayload[string],
): string {
  return t('preview.config', { field: configFieldLabel(field), value: formatConfigValue(value) })
}

function PreviewSection({
  deviceId,
  configOverrides,
  queuedCommands,
  onRemoveCommand,
  onSend,
  disabled,
  hasInvalidInput,
}: {
  deviceId: string
  configOverrides: ConfigOverridePayload
  queuedCommands: QueuedCommand[]
  onRemoveCommand: (key: string) => void
  onSend: () => void
  disabled: boolean
  hasInvalidInput: boolean
}) {
  const { t } = useTranslation('remoteConfiguration')
  const overrideEntries = Object.entries(configOverrides)
  const hasChanges = overrideEntries.length > 0 || queuedCommands.length > 0

  return (
    <section className="remote-config__section">
      <h2 className="remote-config__section-title">{t('preview.title')}</h2>
      {!hasChanges ? (
        <p style={{ color: 'var(--muted)' }}>{t('preview.empty')}</p>
      ) : (
        <ul className="remote-config__preview-list">
          {overrideEntries.map(([field, value]) => (
            <li key={field}>
              {configChangeText(t, field, value)}
            </li>
          ))}
          {queuedCommands.map((c) => (
            <li key={c.key}>
              {t('preview.command', { command: commandLabel(c.command) })}{' '}
              <button
                type="button"
                onClick={() => onRemoveCommand(c.key)}
                className="remote-config__remove-btn"
              >
                {t('preview.remove')}
              </button>
            </li>
          ))}
        </ul>
      )}
      <Button
        onClick={onSend}
        disabled={!deviceId || !hasChanges || disabled || hasInvalidInput}
        variant="primary"
      >
        {t('preview.send')}
      </Button>
      {!deviceId && hasChanges && <p className="remote-config__error">{t('preview.selectDevice')}</p>}
      {hasInvalidInput && <p className="remote-config__error">{t('overrides.invalid')}</p>}
    </section>
  )
}

function RiskyConfirmModal({
  risky,
  onCancel,
  onConfirm,
}: {
  risky: [string, ConfigOverridePayload[string]][]
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation('remoteConfiguration')
  return (
    <ConfirmDialog
      title={t('riskyConfirm.title')}
      confirmLabel={t('riskyConfirm.confirm')}
      confirmVariant="danger"
      focusCancel
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <p>{t('riskyConfirm.body')}</p>
      <ul className="remote-config__preview-list">
        {risky.map(([field, value]) => (
          <li key={field}>{configChangeText(t, field, value)}</li>
        ))}
      </ul>
    </ConfirmDialog>
  )
}

function ConfirmModal({
  deviceId,
  configOverrides,
  queuedCommands,
  submitting,
  onCancel,
  onConfirm,
}: {
  deviceId: string
  configOverrides: ConfigOverridePayload
  queuedCommands: QueuedCommand[]
  submitting: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation('remoteConfiguration')
  return (
    <ConfirmDialog
      title={t('confirm.title', { deviceId })}
      confirmLabel={t('confirm.confirm')}
      submitting={submitting}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <ul className="remote-config__preview-list">
        {Object.entries(configOverrides).map(([field, value]) => (
          <li key={field}>{configChangeText(t, field, value)}</li>
        ))}
        {queuedCommands.map((c) => (
          <li key={c.key}>{t('preview.command', { command: commandLabel(c.command) })}</li>
        ))}
      </ul>
    </ConfirmDialog>
  )
}

export function RemoteConfigurationPage() {
  const { t } = useTranslation('remoteConfiguration')
  const { showToast } = useToast()
  const [devices, setDevices] = useState<DeviceSummary[]>([])
  const [devicesLoading, setDevicesLoading] = useState(true)
  const [devicesError, setDevicesError] = useState<string | null>(null)

  const [deviceId, setDeviceId] = useState('')
  const [overrideInputs, setOverrideInputs] = useState<ConfigInputs>({})
  const [schemaGroups, setSchemaGroups] = useState<ConfigSchemaGroup[] | null>(null)
  const [schemaError, setSchemaError] = useState<string | null>(null)
  // null until loaded (or when loading failed): the form then offers no stars, see its props.
  const [favorites, setFavorites] = useState<string[] | null>(null)
  const [queuedCommands, setQueuedCommands] = useState<QueuedCommand[]>([])

  const [showRiskyConfirm, setShowRiskyConfirm] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearing, setClearing] = useState(false)

  const commandStatus = useCommandStatus(deviceId, { enabled: true })
  const { items: statusItems, heartbeat: statusHeartbeat, loading: queueLoading } = commandStatus
  const [clearError, setClearError] = useState<string | null>(null)
  const [currentConfig, setCurrentConfig] = useState<Record<string, unknown> | null>(null)

  const [commsLog, setCommsLog] = useState<CommandLogItem[]>([])
  const [commsError, setCommsError] = useState<string | null>(null)
  const [showAllDevices, setShowAllDevices] = useState(false)

  const commsDeviceFilter = showAllDevices ? undefined : deviceId || undefined

  const refreshCommsLog = () => {
    listCommandLog(commsDeviceFilter)
      .then((res) => {
        setCommsLog(res.entries)
        setCommsError(null)
      })
      .catch((err) => setCommsError(errorMessage(err, t('errors.logLoad'))))
  }

  useEffect(() => {
    refreshCommsLog()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commsDeviceFilter])

  // The stream only signals that the log changed; the rows themselves come from the server.
  useEffect(() => {
    const filter = commsDeviceFilter
    return openCommandAckStream({
      onAck: (event) => {
        if (!filter || event.device_id === filter) refreshCommsLog()
        if (event.device_id === deviceId) refreshCurrentConfig(deviceId)
      },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commsDeviceFilter, deviceId])

  useEffect(() => {
    getConfigSchema()
      .then((res) => setSchemaGroups(res.groups))
      .catch((err) => setSchemaError(errorMessage(err, i18n.t('remoteConfiguration:errors.schemaLoad'))))
  }, [])

  useEffect(() => {
    getFavoriteConfigFields()
      .then((res) => setFavorites(res.field_keys))
      .catch(() => setFavorites(null))
  }, [])

  useEffect(() => {
    listDevices()
      .then((res) => {
        setDevices(res.devices)
        if (res.devices.some((d) => d.device_id === DEFAULT_DEVICE_ID)) {
          setDeviceId(DEFAULT_DEVICE_ID)
        }
      })
      .catch((err) => setDevicesError(errorMessage(err, i18n.t('remoteConfiguration:errors.devicesLoad'))))
      .finally(() => setDevicesLoading(false))
  }, [])

  const refreshCurrentConfig = (selectedDeviceId: string) => {
    if (!selectedDeviceId) {
      setCurrentConfig(null)
      return
    }
    apiClient
      .get<DeviceHeartbeatSummary>(`/heartbeat/${encodeURIComponent(selectedDeviceId)}`)
      .then((res) => setCurrentConfig(res.current_config))
      .catch(() => setCurrentConfig(null))
  }

  useEffect(() => {
    setClearError(null)
    refreshCurrentConfig(deviceId)
  }, [deviceId])

  // A heartbeat is what delivers queued items and what reports acks and the current config, so
  // each one may have changed the selected device's command status.
  useEffect(() => {
    if (!deviceId) return
    return openHeartbeatStream(deviceId, {
      onHeartbeat: () => {
        commandStatus.refresh({ silent: true })
        refreshCurrentConfig(deviceId)
        refreshCommsLog()
      },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId, commsDeviceFilter])

  const schemaFields = (schemaGroups ?? []).flatMap((group) => group.fields)
  const configOverrides = buildPayload(schemaFields, overrideInputs)
  const riskyChanges = riskyEntries(schemaFields, configOverrides)
  const hasInvalidInput = schemaFields.some((field) => fieldInputError(field, overrideInputs[field.key]))

  const handleOverrideChange = (field: string, value: string | null) => {
    setOverrideInputs((prev) => ({ ...prev, [field]: value }))
  }

  const handleToggleFavorite = (key: string) => {
    if (!favorites) return
    const next = favorites.includes(key) ? favorites.filter((k) => k !== key) : [...favorites, key]
    setFavorites(next)
    putFavoriteConfigFields(next).catch((err) => {
      showToast({ tone: 'danger', message: errorMessage(err, t('errors.favoriteSave')) })
      // Other toggles may be in flight, so show what the server really holds.
      getFavoriteConfigFields()
        .then((res) => setFavorites(res.field_keys))
        .catch(() => setFavorites(null))
    })
  }

  // Risky settings get their own confirmation first; the regular one follows for every send.
  const handleSend = () => (riskyChanges.length > 0 ? setShowRiskyConfirm(true) : setShowConfirm(true))

  const handleClearQueue = async () => {
    setClearing(true)
    setClearError(null)
    try {
      await clearQueue(deviceId)
      showToast({
        tone: 'success',
        message: t('toast.queueRemoved', { deviceId }),
      })
      setShowClearConfirm(false)
      commandStatus.refresh()
    } catch (err) {
      setClearError(errorMessage(err, t('errors.removeQueued')))
    } finally {
      setClearing(false)
    }
  }

  const handleConfirm = async () => {
    setSubmitting(true)
    try {
      if (Object.keys(configOverrides).length > 0) {
        await queueConfigOverrides(deviceId, configOverrides)
      }
      for (const c of queuedCommands) {
        await queueCommand(deviceId, { command: c.command })
      }
      showToast({
        tone: 'success',
        message: t('toast.changesSent', { deviceId }),
        action: queuedCommands.some((c) => c.command === SELFTEST_COMMAND) ? selftestResultsAction() : undefined,
      })
      setOverrideInputs({})
      setQueuedCommands([])
      setShowConfirm(false)
      commandStatus.refresh({ silent: true })
      refreshCommsLog()
    } catch (err) {
      showToast({ tone: 'danger', message: errorMessage(err, t('errors.sendChanges')) })
      refreshCommsLog() // earlier items of a partially-sent batch were already logged
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section>
      <div className="page-header">
        <h1 className="page-header__title">{t('title')}</h1>
        <p className="page-header__subtitle">{t('subtitle')}</p>
      </div>

      {devicesError && <Banner tone="danger" style={{ marginBottom: 'var(--space-4)' }}>{devicesError}</Banner>}

      {devicesLoading ? (
        <p style={{ color: 'var(--muted)' }}>{t('devices.loading')}</p>
      ) : devices.length === 0 ? (
        !devicesError && <p style={{ color: 'var(--muted)' }}>{t('devices.none')}</p>
      ) : (
        <DeviceSelector devices={devices} selectedId={deviceId || null} onSelect={setDeviceId} />
      )}
      {deviceId ? (
        <>
          <Card className="remote-config__card">
            <CommandStatusSection
              deviceId={deviceId}
              loading={queueLoading}
              error={clearError ?? commandStatus.error}
              items={statusItems}
              heartbeat={statusHeartbeat}
              onClearQueue={() => setShowClearConfirm(true)}
              onShutdownDue={() => commandStatus.refresh({ silent: true })}
              onDeleted={() => commandStatus.refresh({ silent: true })}
            />
            <OneShotCommandsForm onAdd={(c) => setQueuedCommands((prev) => [...prev, c])} />
          </Card>
          <Card className="remote-config__card">
            <ConfigOverridesForm
              groups={schemaGroups}
              loadError={schemaError}
              inputs={overrideInputs}
              currentConfig={currentConfig}
              warnings={softWarnings(configOverrides)}
              favorites={favorites}
              onChange={handleOverrideChange}
              onToggleFavorite={handleToggleFavorite}
            />
          </Card>
          <Card className="remote-config__card">
            <PreviewSection
              deviceId={deviceId}
              configOverrides={configOverrides}
              queuedCommands={queuedCommands}
              onRemoveCommand={(key) => setQueuedCommands((prev) => prev.filter((c) => c.key !== key))}
              onSend={handleSend}
              disabled={submitting}
              hasInvalidInput={hasInvalidInput}
            />
          </Card>
        </>
      ) : (
        !devicesLoading &&
        devices.length > 0 && <p style={{ color: 'var(--muted)' }}>{t('devices.select')}</p>
      )}

      <CommandCommsSection
        entries={commsLog}
        error={commsError}
        showAllDevices={showAllDevices}
        onShowAllDevicesChange={setShowAllDevices}
      />

      {showRiskyConfirm && (
        <RiskyConfirmModal
          risky={riskyChanges}
          onCancel={() => setShowRiskyConfirm(false)}
          onConfirm={() => {
            setShowRiskyConfirm(false)
            setShowConfirm(true)
          }}
        />
      )}

      {showConfirm && (
        <ConfirmModal
          deviceId={deviceId}
          configOverrides={configOverrides}
          queuedCommands={queuedCommands}
          submitting={submitting}
          onCancel={() => setShowConfirm(false)}
          onConfirm={handleConfirm}
        />
      )}

      {showClearConfirm && (
        <ClearQueueConfirmModal
          deviceId={deviceId}
          entryCount={statusItems.filter((item) => item.in_queue).length}
          submitting={clearing}
          onCancel={() => setShowClearConfirm(false)}
          onConfirm={handleClearQueue}
        />
      )}
    </section>
  )
}
