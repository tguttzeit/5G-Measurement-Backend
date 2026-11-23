import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  getRawRowCap,
  getShutdownConfirmation,
  putRawRowCap,
  putShutdownConfirmation,
  type ShutdownConfirmation,
} from '../api/settings'
import type { ShutdownConfirmMode } from '../api/commands'
import { useAuth } from '../components/AuthProvider'
import { NotificationSettingsSection } from '../components/NotificationSettingsSection'
import { useToast } from '../components/ToastProvider'
import { Banner, Button, Card, Select, TextInput } from '../components/ui'
import { SUPPORTED_LANGUAGES } from '../i18n'
import { useLanguage } from '../i18n/LanguageProvider'
import './SettingsPage.css'

// Mirrors MAX_RAW_ROW_CAP in app/schemas/settings.py; the server validates again.
const MAX_RAW_ROW_CAP = 2_147_483_647

function parseLimit(input: string): number | null {
  if (!/^\d+$/.test(input.trim())) return null
  const value = Number(input.trim())
  return value >= 1 && value <= MAX_RAW_ROW_CAP ? value : null
}

// Mirror the bounds in app/schemas/settings.py; the server validates again.
const MIN_CONFIRM_INTERVALS = 1
const MAX_CONFIRM_INTERVALS = 20
const MIN_CONFIRM_SECONDS = 10
const MAX_CONFIRM_SECONDS = 3600
// A device's heartbeat interval when it reports none. The device list
// does not carry per-device intervals, so this is the interval a time span is compared against.
const DEFAULT_HEARTBEAT_INTERVAL_S = 60

function parseWhole(input: string, min: number, max: number): number | null {
  if (!/^\d+$/.test(input.trim())) return null
  const value = Number(input.trim())
  return value >= min && value <= max ? value : null
}

function parseSeconds(input: string): number | null {
  if (!/^\d+(\.\d+)?$/.test(input.trim())) return null
  const value = Number(input.trim())
  return value >= MIN_CONFIRM_SECONDS && value <= MAX_CONFIRM_SECONDS ? value : null
}

function LanguageSection() {
  const { t } = useTranslation('settings')
  const { language, setLanguage } = useLanguage()

  return (
    <Card role="region" aria-labelledby="settings-language-title">
      <h2 id="settings-language-title" className="settings-section__title">
        {t('language.title')}
      </h2>
      <p className="settings-section__description">{t('language.description')}</p>
      <Select
        label={t('language.label')}
        value={language}
        onChange={(e) => setLanguage(e.target.value as (typeof SUPPORTED_LANGUAGES)[number])}
      >
        {SUPPORTED_LANGUAGES.map((code) => (
          <option key={code} value={code}>
            {t(`language.${code}`)}
          </option>
        ))}
      </Select>
    </Card>
  )
}

function RawRowCapSection() {
  const { t } = useTranslation('settings')
  const { showToast } = useToast()
  const [loadState, setLoadState] = useState<'loading' | 'error' | 'ready'>('loading')
  const [savedValue, setSavedValue] = useState<number | null>(null)
  const [unlimited, setUnlimited] = useState(true)
  const [limitInput, setLimitInput] = useState('')
  const [validationFailed, setValidationFailed] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    getRawRowCap()
      .then((setting) => {
        if (cancelled) return
        setSavedValue(setting.value)
        setUnlimited(setting.value === null)
        setLimitInput(setting.value === null ? '' : String(setting.value))
        setLoadState('ready')
      })
      .catch(() => {
        if (!cancelled) setLoadState('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    const value = unlimited ? null : parseLimit(limitInput)
    if (!unlimited && value === null) {
      setValidationFailed(true)
      return
    }
    setValidationFailed(false)
    setSaving(true)
    try {
      const saved = await putRawRowCap(value)
      setSavedValue(saved.value)
      showToast({ tone: 'success', message: t('rawRowCap.saved') })
    } catch {
      showToast({ tone: 'danger', message: t('rawRowCap.saveFailed') })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card role="region" aria-labelledby="settings-raw-row-cap-title">
      <h2 id="settings-raw-row-cap-title" className="settings-section__title">
        {t('rawRowCap.title')}
      </h2>
      <p className="settings-section__description">{t('rawRowCap.description')}</p>

      {loadState === 'loading' && <p>{t('rawRowCap.loading')}</p>}
      {loadState === 'error' && <Banner tone="danger">{t('rawRowCap.loadFailed')}</Banner>}
      {loadState === 'ready' && (
        <form className="settings-section__form" onSubmit={handleSave} noValidate>
          <p className="settings-section__description">
            {savedValue === null
              ? t('rawRowCap.currentUnlimited')
              : t('rawRowCap.currentLimit', { value: savedValue })}
          </p>
          <label className="settings-section__checkbox">
            <input
              type="checkbox"
              checked={unlimited}
              onChange={(e) => {
                setUnlimited(e.target.checked)
                setValidationFailed(false)
              }}
            />
            {t('rawRowCap.unlimited')}
          </label>
          {!unlimited && (
            <TextInput
              label={t('rawRowCap.limitLabel')}
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={limitInput}
              onChange={(e) => setLimitInput(e.target.value)}
              aria-invalid={validationFailed}
            />
          )}
          {validationFailed && (
            <p className="settings-section__error" role="alert">
              {t('rawRowCap.invalid')}
            </p>
          )}
          <Button type="submit" disabled={saving}>
            {saving ? t('rawRowCap.saving') : t('rawRowCap.save')}
          </Button>
        </form>
      )}
    </Card>
  )
}

function ShutdownConfirmationSection() {
  const { t } = useTranslation('settings')
  const { showToast } = useToast()
  const [loadState, setLoadState] = useState<'loading' | 'error' | 'ready'>('loading')
  const [saved, setSaved] = useState<ShutdownConfirmation | null>(null)
  const [mode, setMode] = useState<ShutdownConfirmMode>('intervals')
  const [intervalsInput, setIntervalsInput] = useState('')
  const [secondsInput, setSecondsInput] = useState('')
  const [validationFailed, setValidationFailed] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    getShutdownConfirmation()
      .then((setting) => {
        if (cancelled) return
        setSaved(setting)
        setMode(setting.mode)
        setIntervalsInput(String(setting.intervals))
        setSecondsInput(String(setting.seconds))
        setLoadState('ready')
      })
      .catch(() => {
        if (!cancelled) setLoadState('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Only the selected mode's field has to be valid; the other keeps its last typed (or stored) value.
  const intervals = parseWhole(intervalsInput, MIN_CONFIRM_INTERVALS, MAX_CONFIRM_INTERVALS)
  const seconds = parseSeconds(secondsInput)
  const selectedValid = mode === 'intervals' ? intervals !== null : seconds !== null
  const shorterThanHeartbeat =
    mode === 'seconds' && seconds !== null && seconds < DEFAULT_HEARTBEAT_INTERVAL_S

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!saved) return
    if (!selectedValid) {
      setValidationFailed(true)
      return
    }
    setValidationFailed(false)
    setSaving(true)
    try {
      const result = await putShutdownConfirmation({
        mode,
        intervals: intervals ?? saved.intervals,
        seconds: seconds ?? saved.seconds,
      })
      setSaved(result)
      showToast({ tone: 'success', message: t('shutdownConfirmation.saved') })
    } catch {
      showToast({ tone: 'danger', message: t('shutdownConfirmation.saveFailed') })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card role="region" aria-labelledby="settings-shutdown-confirmation-title">
      <h2 id="settings-shutdown-confirmation-title" className="settings-section__title">
        {t('shutdownConfirmation.title')}
      </h2>
      <p className="settings-section__description">{t('shutdownConfirmation.description')}</p>

      {loadState === 'loading' && <p>{t('shutdownConfirmation.loading')}</p>}
      {loadState === 'error' && <Banner tone="danger">{t('shutdownConfirmation.loadFailed')}</Banner>}
      {loadState === 'ready' && saved && (
        <form className="settings-section__form" onSubmit={handleSave} noValidate>
          <p className="settings-section__description">
            {saved.mode === 'intervals'
              ? t('shutdownConfirmation.currentIntervals', { count: saved.intervals })
              : t('shutdownConfirmation.currentSeconds', { value: saved.seconds })}
          </p>
          <Select
            label={t('shutdownConfirmation.modeLabel')}
            value={mode}
            onChange={(e) => {
              setMode(e.target.value as ShutdownConfirmMode)
              setValidationFailed(false)
            }}
          >
            <option value="intervals">{t('shutdownConfirmation.modeIntervals')}</option>
            <option value="seconds">{t('shutdownConfirmation.modeSeconds')}</option>
          </Select>
          {mode === 'intervals' ? (
            <TextInput
              label={t('shutdownConfirmation.intervalsLabel')}
              type="number"
              inputMode="numeric"
              min={MIN_CONFIRM_INTERVALS}
              max={MAX_CONFIRM_INTERVALS}
              step={1}
              value={intervalsInput}
              onChange={(e) => setIntervalsInput(e.target.value)}
              aria-invalid={validationFailed}
            />
          ) : (
            <TextInput
              label={t('shutdownConfirmation.secondsLabel')}
              type="number"
              inputMode="decimal"
              min={MIN_CONFIRM_SECONDS}
              max={MAX_CONFIRM_SECONDS}
              step="any"
              value={secondsInput}
              onChange={(e) => setSecondsInput(e.target.value)}
              aria-invalid={validationFailed}
            />
          )}
          {validationFailed && (
            <p className="settings-section__error" role="alert">
              {mode === 'intervals'
                ? t('shutdownConfirmation.invalidIntervals', {
                    min: MIN_CONFIRM_INTERVALS,
                    max: MAX_CONFIRM_INTERVALS,
                  })
                : t('shutdownConfirmation.invalidSeconds', {
                    min: MIN_CONFIRM_SECONDS,
                    max: MAX_CONFIRM_SECONDS,
                  })}
            </p>
          )}
          {shorterThanHeartbeat && (
            <Banner tone="warning" role="status">
              {t('shutdownConfirmation.shorterThanHeartbeat', { interval: DEFAULT_HEARTBEAT_INTERVAL_S })}
            </Banner>
          )}
          <Button type="submit" disabled={saving}>
            {saving ? t('shutdownConfirmation.saving') : t('shutdownConfirmation.save')}
          </Button>
        </form>
      )}
    </Card>
  )
}

export function SettingsPage() {
  const { t } = useTranslation('settings')
  const { user } = useAuth()

  return (
    <div className="settings-page">
      <h1 className="settings-page__title">{t('title')}</h1>
      <LanguageSection />
      {user && <NotificationSettingsSection />}
      {user?.is_superuser && <RawRowCapSection />}
      {user?.is_superuser && <ShutdownConfirmationSection />}
    </div>
  )
}
