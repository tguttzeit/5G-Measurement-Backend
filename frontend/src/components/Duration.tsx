import { useTranslation } from 'react-i18next'
import { formatDuration } from '../lib/formatDuration'

export function Duration({ seconds }: { seconds: number | null | undefined }) {
  const { t } = useTranslation('time')
  return <span>{formatDuration(seconds, t)}</span>
}
