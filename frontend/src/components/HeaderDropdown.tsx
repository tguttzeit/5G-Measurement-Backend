import { useEffect, useRef, useState } from 'react'
import './HeaderDropdown.css'

export function HeaderDropdown({
  trigger,
  children,
}: {
  trigger: (props: { toggle: () => void; isOpen: boolean }) => React.ReactNode
  children: (props: { close: () => void }) => React.ReactNode
}) {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const close = () => setIsOpen(false)
  const toggle = () => setIsOpen((open) => !open)

  useEffect(() => {
    if (!isOpen) return

    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        close()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen])

  return (
    <div className="header-dropdown" ref={containerRef}>
      {trigger({ toggle, isOpen })}
      {isOpen && <div className="header-dropdown__panel">{children({ close })}</div>}
    </div>
  )
}
