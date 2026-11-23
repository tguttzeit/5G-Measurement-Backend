import { useTranslation } from 'react-i18next'
import { EMPTY_PLACEHOLDER, toIsoString } from '../lib/formatDateTime'
import { formatRelativeTime } from '../lib/formatDuration'
import { useFormatters } from '../lib/useFormatters'
import { useNow } from '../lib/useNow'

function toIso(since: string | number | null | undefined): string | null {
  if (typeof since !== 'number') return toIsoString(since)
  const date = new Date(since)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

// Live-updating "1 min 5 s ago"; the absolute time is the tooltip. Only this label re-renders on a tick.
export function RelativeTime({ since }: { since: string | number | null | undefined }) {
  const { t } = useTranslation('time')
  const { formatDateTime } = useFormatters()
  const nowMs = useNow()
  const iso = toIso(since)
  if (!iso) return <>{EMPTY_PLACEHOLDER}</>

  return (
    <time dateTime={iso} title={formatDateTime(iso)}>
      {formatRelativeTime(new Date(iso).getTime(), nowMs, t)}
    </time>
  )
}
