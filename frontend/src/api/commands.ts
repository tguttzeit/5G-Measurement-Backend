import i18n from '../i18n'
import type { ToastAction } from '../components/ToastProvider'
import { apiClient } from './client'

// `null` is an explicit "not set" (resets the value on the device); a key that is left out means
// "unchanged". The accepted keys and types are those of GET /config-schema.
export type ConfigOverrideValue = number | boolean | string | null

export type ConfigOverridePayload = Record<string, ConfigOverrideValue>

// Mirrors app/schemas/commands.py's ConfigSchemaField. `type` stays a plain string: the structure
// comes from the server, and a type this client does not know must not break the page.
export interface ConfigSchemaField {
  key: string
  type: string
  min: number | null
  max: number | null
  values: string[] | null
  nullable: boolean
  unit: string | null
  requires_confirmation: boolean
  no_effect_yet: boolean
}

export interface ConfigSchemaGroup {
  id: string
  fields: ConfigSchemaField[]
}

export interface ConfigSchemaResponse {
  groups: ConfigSchemaGroup[]
}

export function getConfigSchema(): Promise<ConfigSchemaResponse> {
  return apiClient.get<ConfigSchemaResponse>('/config-schema')
}

// Mirrors OneShotCommand in app/schemas/commands.py.
export const ONE_SHOT_COMMAND_NAMES = [
  'force-upload-now',
  'shutdown-now',
  'sim-reset-now',
  'mode-manual-now',
  'mode-auto-now',
  'start-measuring-now',
  'run-selftest-now',
  'run-gps-fix-test-now',
  'stop-gps-fix-test-now',
  'stop-measuring-now',
  'reboot-now',
  'promote-overrides-now',
] as const

export type OneShotCommand = (typeof ONE_SHOT_COMMAND_NAMES)[number]

export const SELFTEST_COMMAND: OneShotCommand = 'run-selftest-now'

const SELFTEST_RESULTS_PATH = '/testing/visualization'

export function selftestResultsAction(): ToastAction {
  return { label: i18n.t('notifications:selftest.viewResults'), href: SELFTEST_RESULTS_PATH }
}

export interface CommandPayload {
  command: OneShotCommand
}

export interface ConfigOverrideQueuedResponse {
  status: string
  config_overrides: ConfigOverridePayload
}

export interface CommandQueuedResponse {
  status: string
  command_id: number
}

export interface QueueEntry {
  id: number
  type: string
  field: string | null
  payload: Record<string, unknown>
  created_at: string
  delivered_at: string | null
  expires_at: string | null
}

export interface QueueListResponse {
  queue: QueueEntry[]
}

export function queueConfigOverrides(
  deviceId: string,
  payload: ConfigOverridePayload,
): Promise<ConfigOverrideQueuedResponse> {
  return apiClient.post<ConfigOverrideQueuedResponse>(
    `/devices/${encodeURIComponent(deviceId)}/config-overrides`,
    payload,
  )
}

export function queueCommand(
  deviceId: string,
  payload: CommandPayload,
): Promise<CommandQueuedResponse> {
  return apiClient.post<CommandQueuedResponse>(
    `/devices/${encodeURIComponent(deviceId)}/commands`,
    payload,
  )
}

export function listQueue(deviceId: string): Promise<QueueListResponse> {
  return apiClient.get<QueueListResponse>(`/devices/${encodeURIComponent(deviceId)}/queue`)
}

export function clearQueue(deviceId: string): Promise<void> {
  return apiClient.delete<void>(`/devices/${encodeURIComponent(deviceId)}/queue`)
}

// Mirrors app/schemas/commands.py's CommandLogItem.
export interface CommandLogItem {
  id: number
  occurred_at: string
  device_id: string
  direction: 'to_device' | 'from_device'
  kind: 'config' | 'command'
  name: string
  command_id: number | null
  status: string
  detail: string | null
}

export function listCommandLog(deviceId?: string): Promise<{ entries: CommandLogItem[] }> {
  const query = deviceId ? `?device_id=${encodeURIComponent(deviceId)}` : ''
  return apiClient.get<{ entries: CommandLogItem[] }>(`/command-log${query}`)
}

// Mirrors app/schemas/commands.py's CommandStatusEntry.
export type CommandState =
  | 'queued'
  | 'delivered'
  | 'received'
  | 'success'
  | 'failed'
  | 'not_applicable'
  | 'promoted'
  | 'removed'
  | 'expired'

export interface CommandStatusItem {
  command_id: number
  kind: 'config' | 'command'
  name: string
  detail: string | null
  state: CommandState
  complete: boolean
  in_queue: boolean
  queued_at: string | null
  delivered_at: string | null
  received_at: string | null
  result_at: string | null
  removed_at: string | null
  promoted_at: string | null
  expired_at: string | null
  expires_at: string | null
  error: string | null
}

export type ShutdownConfirmMode = 'intervals' | 'seconds'

export interface CommandStatusResponse {
  items: CommandStatusItem[]
  // What a shutdown-now's success is inferred from: the silence since the last heartbeat. It is
  // counted in heartbeat intervals up to `shutdown_confirm_intervals` (mode `intervals`) or in
  // seconds up to `shutdown_confirm_seconds` (mode `seconds`); the other value is the same span
  // expressed in the other unit.
  last_heartbeat_at: string | null
  heartbeat_interval_s: number
  shutdown_confirm_mode: ShutdownConfirmMode
  shutdown_confirm_intervals: number
  shutdown_confirm_seconds: number
  // Heartbeats still sent after the ack that mean the shutdown did not happen.
  shutdown_fail_heartbeats: number
}

export function listCommandStatus(deviceId: string): Promise<CommandStatusResponse> {
  return apiClient.get<CommandStatusResponse>(
    `/devices/${encodeURIComponent(deviceId)}/command-status`,
  )
}

export interface DismissCommandStatusResponse {
  dismissed: number[]
}

// Hides finished commands from the command status (not from the command log). The server only
// dismisses finished, non-queued commands of this device and ignores any other id.
export function dismissCommandStatus(
  deviceId: string,
  commandIds: number[],
): Promise<DismissCommandStatusResponse> {
  return apiClient.post<DismissCommandStatusResponse>(
    `/devices/${encodeURIComponent(deviceId)}/command-status/dismiss`,
    { command_ids: commandIds },
  )
}
