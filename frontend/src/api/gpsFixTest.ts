import { apiClient } from './client'

// Mirrors app/schemas/gps_fix_test.py's GpsFixTestStatusResponse.
export interface GpsFixTestStatus {
  run_active: boolean
  num_satellites: number | null
  has_fix: boolean | null
  elapsed_s: number | null
  updated_at: string | null
}

export function getGpsFixTestStatus(deviceId: string): Promise<GpsFixTestStatus> {
  return apiClient.get<GpsFixTestStatus>(
    `/devices/${encodeURIComponent(deviceId)}/gps-fix-test/status`,
  )
}
