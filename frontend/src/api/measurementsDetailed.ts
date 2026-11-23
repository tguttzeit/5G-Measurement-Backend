import { apiClient } from './client'

// Authenticated-only: richer /map view modes, alongside the public heatmap/export
// endpoints in api/campaigns.ts. All three response shapes share the same GeoJSON Feature
// envelope so callers only need `geometry.coordinates` + `properties.value` for rendering.

export type ViewMode = 'aggregate' | 'raw'

interface GeoJSONPoint {
  type: 'Point'
  coordinates: [number, number]
}

export interface AggregateFeature {
  type: 'Feature'
  geometry: GeoJSONPoint
  properties: { value: number; count: number }
}

// Carries all three metric columns, not just the one selected via `metric` - the Points display
// style shows every metric on click, not only whichever one colors the markers.
export interface RawFeature {
  type: 'Feature'
  geometry: GeoJSONPoint
  properties: {
    id: number
    device_id: string
    timestamp: string
    rsrp: number | null
    rsrq: number | null
    sinr: number | null
  }
}

export type DetailedFeature = AggregateFeature | RawFeature

export interface DetailedFeatureCollection {
  type: 'FeatureCollection'
  features: DetailedFeature[]
}

export interface DetailedQueryParams {
  bbox: string
  metric: string
  view: ViewMode
  deviceId?: string
  missionType?: string
  campaignId?: number | null
  runId?: string
}

// campaignId omitted/null means "all time" here, unlike the public heatmap's default-campaign
// behavior - authenticated callers are trusted to pick their own range (see
// app/measurements_query.py::resolve_optional_campaign_id).
export function fetchDetailedMeasurements(
  params: DetailedQueryParams,
): Promise<DetailedFeatureCollection> {
  const search = new URLSearchParams({ bbox: params.bbox, metric: params.metric, view: params.view })
  if (params.deviceId) search.set('device_id', params.deviceId)
  if (params.missionType) search.set('mission_type', params.missionType)
  if (params.campaignId != null) search.set('campaign_id', String(params.campaignId))
  if (params.runId) search.set('run_id', params.runId)

  return apiClient.get<DetailedFeatureCollection>(`/measurements/detailed?${search.toString()}`)
}

// Public: the guest counterpart of the raw view. Same position + metric values, but
// the response has no device_id or timestamp at all, and there is no deviceId parameter.
export interface PublicRawFeature {
  type: 'Feature'
  geometry: GeoJSONPoint
  properties: {
    id: number
    rsrp: number | null
    rsrq: number | null
    sinr: number | null
  }
}

export interface PublicRawFeatureCollection {
  type: 'FeatureCollection'
  features: PublicRawFeature[]
}

export interface PublicPointsQueryParams {
  bbox: string
  metric: string
  missionType?: string
  campaignId?: number | null
}

// Unlike the authenticated fetcher, an omitted campaignId means the backend's default campaign
// (current or most recently ended), not "all time".
export function fetchPublicMeasurementPoints(
  params: PublicPointsQueryParams,
): Promise<PublicRawFeatureCollection> {
  const search = new URLSearchParams({ bbox: params.bbox, metric: params.metric })
  if (params.missionType) search.set('mission_type', params.missionType)
  if (params.campaignId != null) search.set('campaign_id', String(params.campaignId))

  return apiClient.get<PublicRawFeatureCollection>(`/measurements/points?${search.toString()}`)
}
