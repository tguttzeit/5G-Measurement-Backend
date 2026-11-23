import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import './ToastProvider.css'

export interface ToastAction {
  label: string
  href: string
}

export interface ToastOptions {
  tone: 'success' | 'danger'
  // ReactNode (not just string) so a message can inline e.g. a run id as <code>.
  message: React.ReactNode
  action?: ToastAction
}

export const TOAST_DURATION_MS = 5000
export const TOAST_FADE_MS = 200

interface Toast extends ToastOptions {
  id: string
}

interface ToastContextType {
  showToast: (options: ToastOptions) => void
}

const ToastContext = createContext<ToastContextType | null>(null)

// Mounted once at the app shell (above the router's <Outlet/>), so a toast raised from any page -
// or from a global stream subscription that isn't tied to the page the user happens to be on -
// stays visible across navigation instead of disappearing with the page that raised it.
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(0)

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const showToast = useCallback(
    (options: ToastOptions) => {
      const id = String(nextId.current++)
      setToasts((prev) => [...prev, { ...options, id }])
    },
    [],
  )

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="toast-stack" role="region" aria-label={t('notifications')}>
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const { t } = useTranslation()
  const [paused, setPaused] = useState(false)
  const [leaving, setLeaving] = useState(false)
  // Part of the progress bar's key, so each reset remounts the bar and its animation restarts at full.
  const [cycle, setCycle] = useState(0)
  const reducedMotion = prefersReducedMotion()

  useEffect(() => {
    if (paused) return
    const timer = setTimeout(() => {
      if (reducedMotion) {
        onDismiss(toast.id)
      } else {
        setLeaving(true)
      }
    }, TOAST_DURATION_MS)
    return () => clearTimeout(timer)
  }, [paused, cycle, reducedMotion, onDismiss, toast.id])

  useEffect(() => {
    if (!leaving) return
    const timer = setTimeout(() => onDismiss(toast.id), TOAST_FADE_MS)
    return () => clearTimeout(timer)
  }, [leaving, onDismiss, toast.id])

  const resetTimer = () => {
    setLeaving(false)
    setCycle((c) => c + 1)
  }

  const pause = () => {
    resetTimer()
    setPaused(true)
  }

  const resume = () => setPaused(false)

  const progressClass = [
    'toast__progress',
    reducedMotion && 'toast__progress--static',
    paused && 'toast__progress--paused',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      className={`toast toast--${toast.tone}${leaving ? ' toast--leaving' : ''}`}
      role="status"
      onMouseEnter={pause}
      onMouseLeave={resume}
      onFocus={pause}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) resume()
      }}
      onTouchStart={resetTimer}
    >
      <span className="toast__message">{toast.message}</span>
      {toast.action && (
        <Link to={toast.action.href} className="toast__action" onClick={() => onDismiss(toast.id)}>
          {toast.action.label}
        </Link>
      )}
      <button
        type="button"
        className="toast__close"
        aria-label={t('dismissNotification')}
        onClick={() => onDismiss(toast.id)}
      >
        ×
      </button>
      <span
        key={cycle}
        className={progressClass}
        style={{ animationDuration: `${TOAST_DURATION_MS}ms` }}
        aria-hidden="true"
      />
    </div>
  )
}

export function useToast(): ToastContextType {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within a ToastProvider')
  return ctx
}
