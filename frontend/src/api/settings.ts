import { apiClient } from './client'
import type { ShutdownConfirmMode } from './commands'

export interface RawRowCapSetting {
  value: number | null
  updated_at: string | null
  updated_by: number | null
}

export function getRawRowCap(): Promise<RawRowCapSetting> {
  return apiClient.get<RawRowCapSetting>('/settings/raw-row-cap')
}

export function putRawRowCap(value: number | null): Promise<RawRowCapSetting> {
  return apiClient.put<RawRowCapSetting>('/settings/raw-row-cap', { value })
}

export interface ShutdownConfirmation {
  mode: ShutdownConfirmMode
  intervals: number
  seconds: number
}

export interface ShutdownConfirmationSetting extends ShutdownConfirmation {
  updated_at: string | null
  updated_by: number | null
}

export function getShutdownConfirmation(): Promise<ShutdownConfirmationSetting> {
  return apiClient.get<ShutdownConfirmationSetting>('/settings/shutdown-confirmation')
}

export function putShutdownConfirmation(
  value: ShutdownConfirmation,
): Promise<ShutdownConfirmationSetting> {
  return apiClient.put<ShutdownConfirmationSetting>('/settings/shutdown-confirmation', value)
}
