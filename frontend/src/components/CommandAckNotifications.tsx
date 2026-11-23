import { useEffect } from 'react'
import i18n from '../i18n'
import { SELFTEST_COMMAND, selftestResultsAction } from '../api/commands'
import { openCommandAckStream, type CommandAckEvent } from '../api/commandAckStream'
import { commandLabel } from '../lib/commandLabel'
import { useAuth } from './AuthProvider'
import { useToast } from './ToastProvider'

// Only shutdown-now/reboot-now ever send "received" - there's no later
// heartbeat that could report more, so phrase it as the device reacting, not as done. A Map
// (not a plain object) so an unexpected command value can't accidentally look up an inherited
// property instead of missing outright (e.g. "__proto__").
const RECEIVED_MESSAGE_KEYS = new Map([
  ['shutdown-now', 'ack.shuttingDown'],
  ['reboot-now', 'ack.rebooting'],
])

function describeAck(event: CommandAckEvent): string {
  const t = (key: string, options: Record<string, unknown>) => i18n.t(`notifications:${key}`, options)
  const params = { command: commandLabel(event.command), deviceId: event.device_id, error: event.error, reason: event.error }
  if (event.status === 'received') {
    const key = RECEIVED_MESSAGE_KEYS.get(event.command) ?? 'ack.receivedCommand'
    return t(key, params)
  }
  if (event.status === 'failed') {
    return t('ack.failed', params)
  }
  if (event.status === 'not_applicable') {
    return t(event.error ? 'ack.notApplicableWithReason' : 'ack.notApplicable', params)
  }
  return t('ack.succeeded', params)
}

// Mounted once in AppShell, so this fires regardless of which page the user is on when a
// device actually acknowledges a command - distinct from (and later than) the "command queued"
// toast shown immediately after queuing it.
export function CommandAckNotifications() {
  const { user } = useAuth()
  const { showToast } = useToast()

  useEffect(() => {
    if (!user?.is_superuser) return
    return openCommandAckStream({
      onAck: (event) => {
        showToast({
          tone: event.status === 'failed' || event.status === 'not_applicable' ? 'danger' : 'success',
          message: describeAck(event),
          action: event.status === 'success' && event.command === SELFTEST_COMMAND ? selftestResultsAction() : undefined,
        })
      },
    })
  }, [user?.is_superuser, showToast])

  return null
}
