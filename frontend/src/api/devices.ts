import { apiClient } from './client'

// Pre-selected in device dropdowns when present in the registered device list - the
// maintainer's primary test unit, so pages don't open on an empty "Select a device..." state.
export const DEFAULT_DEVICE_ID = '5gmu_1'

export interface DeviceSummary {
  device_id: string
  online: boolean
  last_heartbeat_at: string | null
}

export interface DeviceListResponse {
  devices: DeviceSummary[]
}

export function listDevices(): Promise<DeviceListResponse> {
  return apiClient.get<DeviceListResponse>('/devices')
}
