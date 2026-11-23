import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../api/client'
import { dismissCommandStatus, type CommandStatusItem } from '../api/commands'
import { Button } from './ui'

// Done and no longer sent to the device. An applied config override is done too, but stays
// queued (it rides along every heartbeat until replaced), so it is not finished.
function isFinished(item: CommandStatusItem): boolean {
  return item.complete && !item.in_queue
}

// Deletes the finished ones among the `shown` items from the command status (the command log
// keeps them). Whatever is still in progress is left alone, and so is anything not shown.
export function DeleteShownButton({
  deviceId,
  shown,
  onDeleted,
}: {
  deviceId: string
  shown: CommandStatusItem[]
  onDeleted: () => void
}) {
  const { t } = useTranslation('commandStatus')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const finishedIds = shown.filter(isFinished).map((item) => item.command_id)

  const deleteShown = async () => {
    setPending(true)
    setError(null)
    try {
      await dismissCommandStatus(deviceId, finishedIds)
      onDeleted()
    } catch (err) {
      const detail = err instanceof ApiError ? (err.body as { detail?: unknown } | undefined)?.detail : undefined
      setError(typeof detail === 'string' ? detail : t('deleteShownFailed'))
    } finally {
      setPending(false)
    }
  }

  return (
    <>
      <Button variant="secondary" onClick={deleteShown} disabled={pending || finishedIds.length === 0}>
        {t('deleteShown')}
      </Button>
      {error && <p role="alert" className="command-status__error">{error}</p>}
    </>
  )
}
