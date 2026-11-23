import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  getNotificationSettings,
  NOTIFICATION_EVENTS,
  putNotificationSettings,
  regenerateNotificationTopic,
  sendTestNotification,
  type NotificationEvent,
  type NotificationSettings,
} from '../api/notificationSettings'
import { ApiError } from '../api/client'
import { useToast } from './ToastProvider'
import { Banner, Button, Card } from './ui'

export function NotificationSettingsSection() {
  const { t } = useTranslation('settings')
  const { showToast } = useToast()
  const [loadState, setLoadState] = useState<'loading' | 'error' | 'ready'>('loading')
  const [saved, setSaved] = useState<NotificationSettings | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [events, setEvents] = useState<NotificationEvent[]>([])
  const [busy, setBusy] = useState(false)

  const apply = (setting: NotificationSettings) => {
    setSaved(setting)
    setEnabled(setting.enabled)
    setEvents(setting.events)
  }

  useEffect(() => {
    let cancelled = false
    getNotificationSettings()
      .then((setting) => {
        if (cancelled) return
        apply(setting)
        setLoadState('ready')
      })
      .catch(() => {
        if (!cancelled) setLoadState('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const toggleEvent = (event: NotificationEvent, checked: boolean) =>
    setEvents((current) =>
      checked ? [...current, event] : current.filter((selected) => selected !== event),
    )

  const run = async (action: () => Promise<void>, failureMessage: string) => {
    setBusy(true)
    try {
      await action()
    } catch {
      showToast({ tone: 'danger', message: failureMessage })
    } finally {
      setBusy(false)
    }
  }

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    return run(async () => {
      apply(await putNotificationSettings({ enabled, events }))
      showToast({ tone: 'success', message: t('notifications.saved') })
    }, t('notifications.saveFailed'))
  }

  const handleTest = () =>
    run(async () => {
      try {
        await sendTestNotification()
      } catch (error) {
        if (error instanceof ApiError && error.status === 429) {
          showToast({ tone: 'danger', message: t('notifications.testRateLimited') })
          return
        }
        throw error
      }
      showToast({ tone: 'success', message: t('notifications.testSent') })
    }, t('notifications.testFailed'))

  const handleRegenerate = () => {
    if (!window.confirm(t('notifications.regenerateConfirm'))) return
    return run(async () => {
      apply(await regenerateNotificationTopic())
      showToast({ tone: 'success', message: t('notifications.regenerated') })
    }, t('notifications.regenerateFailed'))
  }

  const handleCopy = async () => {
    if (!saved) return
    try {
      await navigator.clipboard.writeText(saved.topic)
      showToast({ tone: 'success', message: t('notifications.copied') })
    } catch {
      showToast({ tone: 'danger', message: t('notifications.copyFailed') })
    }
  }

  return (
    <Card role="region" aria-labelledby="settings-notifications-title">
      <h2 id="settings-notifications-title" className="settings-section__title">
        {t('notifications.title')}
      </h2>
      <p className="settings-section__description">{t('notifications.description')}</p>

      {loadState === 'loading' && <p>{t('notifications.loading')}</p>}
      {loadState === 'error' && <Banner tone="danger">{t('notifications.loadFailed')}</Banner>}
      {loadState === 'ready' && saved && (
        <form className="settings-section__form" onSubmit={handleSave} noValidate>
          <label className="settings-section__checkbox">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            {t('notifications.enabled')}
          </label>
          <fieldset className="settings-section__fieldset" disabled={!enabled}>
            <legend>{t('notifications.eventsLegend')}</legend>
            {NOTIFICATION_EVENTS.map((event) => (
              <label key={event} className="settings-section__checkbox">
                <input
                  type="checkbox"
                  checked={events.includes(event)}
                  onChange={(e) => toggleEvent(event, e.target.checked)}
                />
                {t(`notifications.event.${event}`)}
              </label>
            ))}
          </fieldset>
          <Button type="submit" disabled={busy}>
            {t('notifications.save')}
          </Button>

          <h3 className="settings-section__subtitle">{t('notifications.subscribeTitle')}</h3>
          <p className="settings-section__description">
            {t('notifications.subscribeDescription', { server: saved.server_url })}
          </p>
          <p className="settings-section__description">{t('notifications.topicWarning')}</p>
          <code className="settings-section__secret" aria-label={t('notifications.topicLabel')}>
            {saved.topic}
          </code>
          <div className="settings-section__actions">
            <Button type="button" onClick={handleCopy}>
              {t('notifications.copy')}
            </Button>
            <Button type="button" onClick={handleTest} disabled={busy}>
              {t('notifications.sendTest')}
            </Button>
            <Button type="button" onClick={handleRegenerate} disabled={busy}>
              {t('notifications.regenerate')}
            </Button>
          </div>
        </form>
      )}
    </Card>
  )
}
