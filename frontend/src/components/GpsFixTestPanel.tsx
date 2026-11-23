import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { ApiError } from '../api/client'
import { queueCommand } from '../api/commands'
import { DEFAULT_DEVICE_ID, listDevices, type DeviceSummary } from '../api/devices'
import { getGpsFixTestStatus, type GpsFixTestStatus } from '../api/gpsFixTest'
import { commandLabel } from '../lib/commandLabel'
import { useCommandStatus } from '../lib/useCommandStatus'
import { CommandStatusList } from './CommandStatusList'
import { DeleteShownButton } from './DeleteShownButton'
import { DeviceSelector } from './DeviceSelector'
import { Duration } from './Duration'
import { Banner, Button, Card, Tile } from './ui'
import './GpsFixTestPanel.css'

// Matches the device's own push interval (gps_fix_test.report_interval_s, device default 2s),
// so the live count feels continuous without over-polling.
const POLL_INTERVAL_MS = 2000

const GPS_FIX_TEST_COMMANDS = ['run-gps-fix-test-now', 'stop-gps-fix-test-now'] as const
type GpsFixTestCommand = (typeof GPS_FIX_TEST_COMMANDS)[number]

const TIMELINE_ITEM_LIMIT = 5

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}

function StatTile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Tile className="gps-fix__tile">
      <span className="gps-fix__tile-label">{label}</span>
      <span className="gps-fix__tile-value">{children}</span>
    </Tile>
  )
}

// A live GPS-fix-finding diagnostic run, to help find a good antenna mounting position. Superuser
// only (it queues commands), collapsed by default - and only polls the device while open.
export function GpsFixTestPanel() {
  const { t } = useTranslation('gpsFix')
  const [open, setOpen] = useState(false)

  const [devices, setDevices] = useState<DeviceSummary[]>([])
  const [devicesLoading, setDevicesLoading] = useState(true)
  const [devicesError, setDevicesError] = useState<string | null>(null)

  const [deviceId, setDeviceId] = useState('')
  const [status, setStatus] = useState<GpsFixTestStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)

  const [actionPending, setActionPending] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const commandStatus = useCommandStatus(deviceId, { enabled: open })
  const { refresh: refreshCommandStatus } = commandStatus
  const timelineItems = commandStatus.items
    .filter((item) => (GPS_FIX_TEST_COMMANDS as readonly string[]).includes(item.name))
    .slice(0, TIMELINE_ITEM_LIMIT)

  useEffect(() => {
    listDevices()
      .then((res) => {
        setDevices(res.devices)
        if (res.devices.some((d) => d.device_id === DEFAULT_DEVICE_ID)) {
          setDeviceId(DEFAULT_DEVICE_ID)
        }
      })
      .catch((err) => setDevicesError(errorMessage(err, i18n.t('gpsFix:devicesLoadFailed'))))
      .finally(() => setDevicesLoading(false))
  }, [])

  useEffect(() => {
    if (!open || !deviceId) {
      setStatus(null)
      return
    }

    let cancelled = false
    const poll = () => {
      getGpsFixTestStatus(deviceId)
        .then((res) => {
          if (cancelled) return
          setStatus(res)
          setStatusError(null)
          // The device reports through the same heartbeats that advance the command timeline.
          refreshCommandStatus({ silent: true })
        })
        .catch((err) => {
          if (!cancelled) setStatusError(errorMessage(err, i18n.t('gpsFix:statusLoadFailed')))
        })
    }

    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [open, deviceId, refreshCommandStatus])

  useEffect(() => {
    setActionError(null)
  }, [deviceId])

  const sendCommand = async (command: GpsFixTestCommand) => {
    setActionPending(true)
    setActionError(null)
    try {
      await queueCommand(deviceId, { command })
      refreshCommandStatus({ silent: true })
    } catch (err) {
      setActionError(errorMessage(err, t('queueFailed', { command: commandLabel(command) })))
    } finally {
      setActionPending(false)
    }
  }

  return (
    <Card className="gps-fix">
      <details onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary className="gps-fix__summary">{t('title')}</summary>
        <div className="gps-fix__body">
          <p className="gps-fix__hint">
            {t('hint')}
          </p>

          {devicesError && <Banner tone="danger">{devicesError}</Banner>}
          {devicesLoading ? (
            <p style={{ color: 'var(--muted)' }}>{t('loadingDevices')}</p>
          ) : devices.length === 0 ? (
            !devicesError && <p style={{ color: 'var(--muted)' }}>{t('noDevices')}</p>
          ) : (
            <DeviceSelector
              devices={devices}
              selectedId={deviceId || null}
              onSelect={setDeviceId}
            />
          )}

          {deviceId && (
            <>
              <div className="gps-fix__actions" role="group" aria-label={t('runGroup')}>
                <Button
                  variant="primary"
                  onClick={() => sendCommand('run-gps-fix-test-now')}
                  disabled={actionPending}
                  title="run-gps-fix-test-now"
                >
                  {commandLabel('run-gps-fix-test-now')}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => sendCommand('stop-gps-fix-test-now')}
                  disabled={actionPending}
                  title="stop-gps-fix-test-now"
                >
                  {commandLabel('stop-gps-fix-test-now')}
                </Button>
              </div>

              {actionError && <Banner tone="danger">{actionError}</Banner>}
              {commandStatus.error && <Banner tone="danger">{commandStatus.error}</Banner>}
              {timelineItems.length > 0 && (
                <>
                  <div className="gps-fix__timeline-actions">
                    <DeleteShownButton
                      deviceId={deviceId}
                      shown={timelineItems}
                      onDeleted={() => refreshCommandStatus({ silent: true })}
                    />
                  </div>
                  <CommandStatusList
                    items={timelineItems}
                    names={[...GPS_FIX_TEST_COMMANDS]}
                    heartbeat={commandStatus.heartbeat ?? undefined}
                  />
                </>
              )}
              {statusError && <Banner tone="danger">{statusError}</Banner>}

              {!statusError && status && !status.run_active && (
                <p style={{ color: 'var(--muted)' }}>{t('noRunActive')}</p>
              )}
              {!statusError && status?.run_active && (
                <div className="gps-fix__tiles">
                  <StatTile label={t('satellites')}>{status.num_satellites}</StatTile>
                  <StatTile label={t('fix')}>{status.has_fix ? t('yes') : t('no')}</StatTile>
                  <StatTile label={t('elapsed')}><Duration seconds={status.elapsed_s} /></StatTile>
                </div>
              )}
            </>
          )}
        </div>
      </details>
    </Card>
  )
}
