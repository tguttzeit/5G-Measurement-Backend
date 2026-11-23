import { Fragment, useEffect } from 'react'
import { Trans } from 'react-i18next'
import i18n from '../i18n'
import { openUploadStream, type UploadEvent } from '../api/uploadStream'
import { useAuth } from './AuthProvider'
import { useToast } from './ToastProvider'

// run_id is passed through purely so RunsPage can highlight the row that just landed - it's not
// a filter the backend understands (GET /runs has no run_id param).
function runsLinkForDevice(deviceId: string, runIds: UploadEvent['run_ids']): string {
  const params = new URLSearchParams({ device_id: deviceId })
  const known = runIds.filter((id): id is string => id !== null)
  if (known.length > 0) params.set('run_id', known.join(','))
  return `/runs?${params.toString()}`
}

// Almost always exactly one entry; a null one means those datapoints predate the device sending
// an explicit run_id. Each id renders as <code> so it's visually distinct and easy
// to select/copy out of the toast.
function describeRunIds(runIds: UploadEvent['run_ids']): React.ReactNode {
  const t = (key: string) => i18n.t(`notifications:${key}`)
  const known = runIds.filter((id): id is string => id !== null)
  if (known.length === 0) return t('upload.originUnlabeled')
  if (known.length === 1) {
    return (
      <>
        {t('upload.originRun')} <code>{known[0]}</code>
      </>
    )
  }
  return (
    <>
      {t('upload.originRuns')}{' '}
      {known.map((id, i) => (
        <Fragment key={id}>
          {i > 0 && ', '}
          <code>{id}</code>
        </Fragment>
      ))}
    </>
  )
}

// Mounted once in AppShell, so this fires regardless of which page the user is on when a
// device's upload actually lands - distinct from (and later than) the "command queued" toast
// shown immediately after triggering force-upload-now.
export function UploadNotifications() {
  const { user } = useAuth()
  const { showToast } = useToast()

  useEffect(() => {
    if (!user?.is_superuser) return
    return openUploadStream({
      onUpload: (event) => {
        showToast({
          tone: 'success',
          message: (
            <Trans
              ns="notifications"
              i18nKey="upload.success"
              count={event.point_count}
              values={{ deviceId: event.device_id }}
              // React already escapes text nodes; without this Trans would show "&lt;" literally.
              shouldUnescape
              components={{ origin: <>{describeRunIds(event.run_ids)}</> }}
            />
          ),
          action: { label: i18n.t('notifications:upload.viewInRuns'), href: runsLinkForDevice(event.device_id, event.run_ids) },
          // No auto-dismiss: this is the one place the run id/link is shown, give the user time.
        })
      },
    })
  }, [user?.is_superuser, showToast])

  return null
}
