import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from './Button'
import './ConfirmDialog.css'

export interface ConfirmDialogProps {
  title: string
  children?: React.ReactNode
  confirmLabel: string
  submittingLabel?: string
  confirmVariant?: 'primary' | 'danger'
  submitting?: boolean
  confirmDisabled?: boolean
  // Puts the initial focus on Cancel so that Enter does not confirm a risky action.
  focusCancel?: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  submittingLabel,
  confirmVariant = 'primary',
  submitting = false,
  confirmDisabled = false,
  focusCancel = false,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const titleId = useId()
  const { t } = useTranslation()

  return (
    <div className="ui-confirm-dialog__backdrop">
      <div className="ui-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h3 id={titleId} className="ui-confirm-dialog__title">
          {title}
        </h3>
        {children}
        <div className="ui-confirm-dialog__actions">
          <Button variant="secondary" onClick={onCancel} disabled={submitting} autoFocus={focusCancel}>
            {t('cancel')}
          </Button>
          <Button
            variant={confirmVariant}
            onClick={onConfirm}
            disabled={submitting || confirmDisabled}
          >
            {submitting ? (submittingLabel ?? t('sending')) : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
