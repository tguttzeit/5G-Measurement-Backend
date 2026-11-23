import { toIsoString } from '../lib/formatDateTime'
import { useFormatters } from '../lib/useFormatters'

interface TimestampProps {
  value: string | null | undefined
  part?: 'dateTime' | 'date' | 'time'
}

export function Timestamp({ value, part = 'dateTime' }: TimestampProps) {
  const formatters = useFormatters()
  const format = { dateTime: formatters.formatDateTime, date: formatters.formatDate, time: formatters.formatTime }[part]
  const iso = toIsoString(value)
  if (!iso) return <>{format(value)}</>

  // A date-only value has no time zone to report; its tooltip is the plain day.
  const title = part === 'date' && value === iso.slice(0, 10) ? iso.slice(0, 10) : `${formatters.timeZoneLabel(iso)} · ${iso}`
  return (
    <time dateTime={iso} title={title}>
      {format(value)}
    </time>
  )
}
