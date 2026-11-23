import { useCallback, useEffect, useRef, useState } from 'react'
import i18n from '../i18n'
import { ApiError } from '../api/client'
import { openCommandAckStream } from '../api/commandAckStream'
import { listCommandStatus, type CommandStatusItem, type CommandStatusResponse } from '../api/commands'

export interface UseCommandStatus {
  items: CommandStatusItem[]
  // The whole response, for the heartbeat info a shutdown-now timeline counts up from.
  heartbeat: CommandStatusResponse | null
  loading: boolean
  error: string | null
  // `silent` skips the loading state, for refreshes the user did not ask for (streams, polling).
  refresh: (options?: { silent?: boolean }) => void
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
  }
  return i18n.t('commandStatus:loadFailed')
}

// The command status of one device, kept current by the command ack stream. Nothing is requested
// or subscribed to while `enabled` is false or no device is selected, so a caller that must not
// reach the (superuser-only) endpoint, or whose view is closed, costs nothing.
export function useCommandStatus(deviceId: string, { enabled }: { enabled: boolean }): UseCommandStatus {
  const [items, setItems] = useState<CommandStatusItem[]>([])
  const [heartbeat, setHeartbeat] = useState<CommandStatusResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const active = enabled && !!deviceId
  // A response only counts for the device it was requested for.
  const requestedDevice = useRef('')

  const refresh = useCallback(
    ({ silent = false }: { silent?: boolean } = {}) => {
      if (!active) return
      requestedDevice.current = deviceId
      if (!silent) setLoading(true)
      setError(null)
      listCommandStatus(deviceId)
        .then((res) => {
          if (requestedDevice.current !== deviceId) return
          setItems(res.items)
          setHeartbeat(res)
        })
        .catch((err) => {
          if (requestedDevice.current === deviceId) setError(errorMessage(err))
        })
        .finally(() => {
          if (requestedDevice.current === deviceId) setLoading(false)
        })
    },
    [active, deviceId],
  )

  useEffect(() => {
    if (!active) {
      requestedDevice.current = ''
      setItems([])
      setHeartbeat(null)
      setLoading(false)
      setError(null)
      return
    }
    setItems([])
    setHeartbeat(null)
    refresh()
    // The stream is global; only the acks of this device can have changed its status.
    return openCommandAckStream({
      onAck: (event) => {
        if (event.device_id === deviceId) refresh({ silent: true })
      },
    })
  }, [active, deviceId, refresh])

  return { items, heartbeat, loading, error, refresh }
}
