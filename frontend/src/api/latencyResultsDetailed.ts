import { apiClient } from './client'

// Authenticated-only: raw latency test results for the map's Points style, the
// latency counterpart of measurementsDetailed.ts. Each result is a start->end line rather than a
// point, and carries all five metric values (not just the one selected via `metric`).

export interface LatencyRawFeature {
  type: 'Feature'
  geometry: { type: 'LineString'; coordinates: [[number, number], [number, number]] }
  properties: {
    device_id: string
    test_type: string
    start_timestamp: string
    end_timestamp: string
    baseline_rtt_ms: number | null
    rtt_under_load_ms: number | null
    rtt_p99_ms: number | null
    download_mbits_s: number | null
    upload_mbits_s: number | null
  }
}

export interface LatencyRawFeatureCollection {
  type: 'FeatureCollection'
  features: LatencyRawFeature[]
}

export interface LatencyRawQueryParams {
  bbox: string
  metric: string
  deviceId?: string
  missionType?: string
  campaignId?: number | null
  runId?: string
}

// campaignId omitted/null means "all time", same as the measurements detailed endpoint.
export function fetchLatencyRaw(params: LatencyRawQueryParams): Promise<LatencyRawFeatureCollection> {
  const search = new URLSearchParams({ bbox: params.bbox, metric: params.metric })
  if (params.deviceId) search.set('device_id', params.deviceId)
  if (params.missionType) search.set('mission_type', params.missionType)
  if (params.campaignId != null) search.set('campaign_id', String(params.campaignId))
  if (params.runId) search.set('run_id', params.runId)

  return apiClient.get<LatencyRawFeatureCollection>(`/latency-results/raw?${search.toString()}`)
}

// Public: the guest counterpart of the raw view. Same lines and metric values, but
// no device_id, timestamps or test_type, and no deviceId parameter.
export interface PublicLatencyFeature {
  type: 'Feature'
  geometry: LatencyRawFeature['geometry']
  properties: Pick<
    LatencyRawFeature['properties'],
    | 'baseline_rtt_ms'
    | 'rtt_under_load_ms'
    | 'rtt_p99_ms'
    | 'download_mbits_s'
    | 'upload_mbits_s'
  >
}

export interface PublicLatencyFeatureCollection {
  type: 'FeatureCollection'
  features: PublicLatencyFeature[]
}

export interface PublicLatencyQueryParams {
  bbox: string
  metric: string
  missionType?: string
  campaignId?: number | null
}

// An omitted campaignId means the backend's default campaign, not "all time".
export function fetchPublicLatencyPoints(
  params: PublicLatencyQueryParams,
): Promise<PublicLatencyFeatureCollection> {
  const search = new URLSearchParams({ bbox: params.bbox, metric: params.metric })
  if (params.missionType) search.set('mission_type', params.missionType)
  if (params.campaignId != null) search.set('campaign_id', String(params.campaignId))

  return apiClient.get<PublicLatencyFeatureCollection>(`/latency-results/points?${search.toString()}`)
}
