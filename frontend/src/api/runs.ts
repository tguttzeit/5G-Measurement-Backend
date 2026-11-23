import { apiClient } from './client'

// Authenticated-only: one run is one drive/flight of one device. `run_id` never
// appears in the public map endpoints, so nothing in api/campaigns.ts mirrors this.

export type RunSortKey = 'start' | 'duration' | 'point_count'
export type SortOrder = 'asc' | 'desc'

export interface Run {
  // Internal id used by the edit and delete endpoints; (device_id, run_id) stays the
  // device-supplied identity and is never editable.
  id: number
  name: string | null
  run_id: string
  device_id: string
  mission_type: string
  start: string
  end: string
  point_count: number
  mean_rsrp: number | null
  mean_rsrq: number | null
  mean_sinr: number | null
  campaign_id: number | null
  campaign_name: string | null
  legacy: boolean
}

export interface RunListResponse {
  runs: Run[]
  total: number
  page: number
  page_size: number
}

export interface RunQueryParams {
  deviceId?: string
  missionType?: string
  campaignId?: number | null
  unassigned?: boolean
  from?: string
  to?: string
  sort: RunSortKey
  order: SortOrder
  page: number
  pageSize: number
}

export function fetchRuns(params: RunQueryParams, signal?: AbortSignal): Promise<RunListResponse> {
  const search = new URLSearchParams({
    sort: params.sort,
    order: params.order,
    page: String(params.page),
    page_size: String(params.pageSize),
  })
  if (params.deviceId) search.set('device_id', params.deviceId)
  if (params.missionType) search.set('mission_type', params.missionType)
  if (params.campaignId != null) search.set('campaign_id', String(params.campaignId))
  if (params.unassigned) search.set('unassigned', 'true')
  if (params.from) search.set('from', params.from)
  if (params.to) search.set('to', params.to)

  return apiClient.get<RunListResponse>(`/runs?${search.toString()}`, { signal })
}

// What the map page's `run` filter needs to scope the view to one run: runs are identified by
// (device_id, run_id), `mission` selects the run's mission type (the map always filters by one),
// and `campaign` only hints which campaign's extent to fit the view to.
export function mapLinkForRun(run: Run): string {
  const search = new URLSearchParams({
    run: run.run_id,
    device: run.device_id,
    mission: run.mission_type,
  })
  if (run.campaign_id != null) search.set('campaign', String(run.campaign_id))
  return `/map?${search.toString()}`
}

// What a superuser may change on a run; only the fields present are sent.
// `name: null` clears the name, `campaign_id: null` unassigns the run.
export interface RunChanges {
  name?: string | null
  mission_type?: 'ground' | 'drone'
  campaign_id?: number | null
}

export interface RunAttributes {
  id: number
  device_id: string
  run_id: string
  name: string | null
  mission_type: string
  campaign_id: number | null
  campaign_name: string | null
}

export function runLabel(run: Pick<Run, 'name' | 'run_id'>): string {
  return run.name ?? run.run_id
}

export function updateRun(id: number, changes: RunChanges): Promise<RunAttributes> {
  return apiClient.patch<RunAttributes>(`/runs/${id}`, changes)
}

// All or nothing: the backend applies the changes to every run or to none.
export function updateRuns(ids: number[], changes: RunChanges): Promise<{ updated: number }> {
  return apiClient.patch<{ updated: number }>('/runs', { ids, changes })
}

// Moves the run with all its measurements and latency results to the trash, where a superuser
// can restore it or delete it permanently.
export function deleteRun(id: number): Promise<void> {
  return apiClient.delete<void>(`/runs/${id}`)
}

export interface TrashedRun {
  id: number
  name: string | null
  run_id: string
  device_id: string
  mission_type: string
  // Null for a run without measurements (e.g. one with latency results only)
  start: string | null
  end: string | null
  point_count: number
  latency_result_count: number
  campaign_id: number | null
  campaign_name: string | null
  legacy: boolean
  deleted_at: string
  // Null once the user who trashed the run has been removed
  deleted_by: number | null
  deleted_by_email: string | null
}

export interface TrashedRunListResponse {
  runs: TrashedRun[]
  total: number
  page: number
  page_size: number
}

export function fetchTrashedRuns(
  page: number,
  pageSize: number,
  signal?: AbortSignal,
): Promise<TrashedRunListResponse> {
  const search = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return apiClient.get<TrashedRunListResponse>(`/runs/trash?${search.toString()}`, { signal })
}

export function restoreRun(id: number): Promise<void> {
  return apiClient.post<void>(`/runs/${id}/restore`)
}

// Irreversibly deletes a trashed run with all its measurements and latency results.
export function deleteRunPermanently(id: number): Promise<void> {
  return apiClient.delete<void>(`/runs/trash/${id}`)
}
