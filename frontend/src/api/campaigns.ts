import i18n, { DEFAULT_LANGUAGE, isSupportedLanguage } from '../i18n'
import { formatDate } from '../lib/formatDateTime'
import { apiClient } from './client'

// `start`/`end` are UTC days (YYYY-MM-DD) derived by the backend from the campaign's runs (oldest
// run start, newest run end) and are null while the campaign has no runs.
export interface Campaign {
  id: number
  name: string
  start: string | null
  end: string | null
}

export interface CampaignListResponse {
  campaigns: Campaign[]
}

export interface CampaignPayload {
  name: string
}

// A run is identified by (device_id, run_id), same as in api/runs.ts.
export interface RunReference {
  device_id: string
  run_id: string
}

// Public endpoint - no Authorization header needed, same as the heatmap/export endpoints it
// sits alongside (see MapHeatmapPage.tsx).
export async function fetchPublicCampaigns(): Promise<CampaignListResponse> {
  const response = await fetch('/api/measurements/campaigns')
  if (!response.ok) {
    throw new Error(i18n.t('campaigns:loadFailed', { status: response.status }))
  }
  return response.json()
}

// Superuser CRUD, via the authenticated apiClient (see adminUsers.ts for the same pattern).
export function listAdminCampaigns(): Promise<CampaignListResponse> {
  return apiClient.get<CampaignListResponse>('/admin/campaigns')
}

export function createCampaign(payload: CampaignPayload): Promise<Campaign> {
  return apiClient.post<Campaign>('/admin/campaigns', payload)
}

export function updateCampaign(id: number, payload: Partial<CampaignPayload>): Promise<Campaign> {
  return apiClient.patch<Campaign>(`/admin/campaigns/${id}`, payload)
}

export function deleteCampaign(id: number): Promise<void> {
  return apiClient.delete<void>(`/admin/campaigns/${id}`)
}

// Runs are assigned to a campaign explicitly; both calls return the updated campaign. Assigning
// a run moves it out of any other campaign.
export function assignRuns(id: number, runs: RunReference[]): Promise<Campaign> {
  return apiClient.post<Campaign>(`/admin/campaigns/${id}/runs`, { runs })
}

export function unassignRuns(id: number, runs: RunReference[]): Promise<Campaign> {
  return apiClient.post<Campaign>(`/admin/campaigns/${id}/runs/unassign`, { runs })
}

// Same rule as the backend's default-campaign resolution (app/measurements_query.py's
// resolve_campaign): the campaign with the most recent run end. Only used to preselect the
// dropdown - the backend re-derives its own default independently whenever no campaign_id is
// sent, so this never needs to be authoritative. Days compare as strings; a tie goes to the
// campaign created later, as in the backend.
export function defaultCampaign(campaigns: Campaign[]): Campaign | null {
  let best: Campaign | null = null
  for (const campaign of campaigns) {
    if (campaign.end == null) continue
    if (best?.end == null || campaign.end > best.end || (campaign.end === best.end && campaign.id > best.id)) {
      best = campaign
    }
  }
  return best
}

export function formatCampaignPeriod(campaign: Campaign): string {
  if (campaign.start == null || campaign.end == null) return i18n.t('campaigns:noRuns')
  const language = isSupportedLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE
  return `${formatDate(campaign.start, language)} – ${formatDate(campaign.end, language)}`
}
