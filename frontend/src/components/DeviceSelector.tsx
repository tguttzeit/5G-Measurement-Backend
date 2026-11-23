import { useTranslation } from 'react-i18next'
import type { DeviceSummary } from '../api/devices'
import './DeviceSelector.css'

export function DeviceSelector({
  devices,
  selectedId,
  onSelect,
}: {
  devices: DeviceSummary[]
  selectedId: string | null
  onSelect: (deviceId: string) => void
}) {
  const { t } = useTranslation()

  return (
    <div className="device-selector" role="group" aria-label={t('devices')}>
      {devices.map((device) => (
        <button
          key={device.device_id}
          type="button"
          className={
            device.device_id === selectedId ? 'device-selector__button device-selector__button--selected' : 'device-selector__button'
          }
          aria-pressed={device.device_id === selectedId}
          onClick={() => onSelect(device.device_id)}
        >
          <span
            className={device.online ? 'device-selector__dot device-selector__dot--online' : 'device-selector__dot'}
            role="img"
            aria-label={device.online ? t('online') : t('offline')}
          />
          {device.device_id}
        </button>
      ))}
    </div>
  )
}
