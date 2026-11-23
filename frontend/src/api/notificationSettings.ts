import { apiClient } from './client'

export const NOTIFICATION_EVENTS = [
  'box_started',
  'measurement_started',
  'measurement_finished',
  'runs_uploaded',
  'error',
] as const

export type NotificationEvent = (typeof NOTIFICATION_EVENTS)[number]

export interface NotificationSettings {
  enabled: boolean
  events: NotificationEvent[]
  topic: string
  server_url: string
}

export function getNotificationSettings(): Promise<NotificationSettings> {
  return apiClient.get<NotificationSettings>('/notification-settings')
}

export function putNotificationSettings(
  value: Pick<NotificationSettings, 'enabled' | 'events'>,
): Promise<NotificationSettings> {
  return apiClient.put<NotificationSettings>('/notification-settings', value)
}

export function regenerateNotificationTopic(): Promise<NotificationSettings> {
  return apiClient.post<NotificationSettings>('/notification-settings/regenerate-topic')
}

export function sendTestNotification(): Promise<void> {
  return apiClient.post<void>('/notification-settings/test')
}
