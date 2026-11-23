import { useEffect, useId, useRef, useState } from 'react'
import './InfoPopover.css'

export interface InfoPopoverProps {
  // Accessible name of the ⓘ button.
  label: string
  children: React.ReactNode
}

const VIEWPORT_MARGIN = 8

// Mouse: hover opens, leaving closes. Keyboard and touch: the button toggles it. Esc and a press
// outside close it. Fixed positioning keeps it from being clipped by scrolling timelines.
export function InfoPopover({ label, children }: InfoPopoverProps) {
  const [hovered, setHovered] = useState(false)
  const [pinned, setPinned] = useState(false)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const wrapperRef = useRef<HTMLSpanElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLSpanElement>(null)
  const id = useId()
  const open = hovered || pinned

  useEffect(() => {
    if (!open) return
    const button = buttonRef.current
    const popover = popoverRef.current
    if (button && popover) {
      const anchor = button.getBoundingClientRect()
      const maxLeft = window.innerWidth - popover.offsetWidth - VIEWPORT_MARGIN
      setPosition({
        top: anchor.bottom + 4,
        left: Math.max(VIEWPORT_MARGIN, Math.min(anchor.left, maxLeft)),
      })
    }

    const close = () => {
      setHovered(false)
      setPinned(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) close()
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open])

  return (
    <span
      ref={wrapperRef}
      className="info-popover"
      onPointerEnter={(event) => event.pointerType === 'mouse' && setHovered(true)}
      onPointerLeave={(event) => event.pointerType === 'mouse' && setHovered(false)}
    >
      <button
        ref={buttonRef}
        type="button"
        className="info-popover__button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setPinned((value) => !value)}
      >
        ⓘ
      </button>
      {open && (
        <span
          ref={popoverRef}
          id={id}
          role="note"
          className="info-popover__content"
          style={position ?? { visibility: 'hidden' }}
        >
          {children}
        </span>
      )}
    </span>
  )
}
