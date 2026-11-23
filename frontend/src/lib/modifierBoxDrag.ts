import type { GeoBounds } from './selectionGeometry'

// Leaflet's built-in box zoom is hardwired to Shift, so Shift+drag (selection) and Ctrl+drag (zoom)
// are both implemented here instead. Only the slice of L.Map this needs, so it stays unit-testable
// against a plain fake.
export interface BoxDragMap {
  getContainer: () => HTMLElement
  mouseEventToContainerPoint: (e: MouseEvent) => { x: number; y: number }
  containerPointToLatLng: (point: [number, number]) => { lat: number; lng: number }
  dragging: { enabled: () => boolean; enable: () => void; disable: () => void }
}

export interface BoxDragHandlers {
  onZoomBox: (bounds: GeoBounds) => void
  onSelectBox: (bounds: GeoBounds) => void
}

// Below this, a press-and-release is a click (e.g. shift-click toggling a marker), not a drag.
const DRAG_THRESHOLD_PX = 5
const BOX_CLASS = 'map-box-drag'

type Mode = 'zoom' | 'select'

function modeFor(e: MouseEvent): Mode | null {
  if (e.button !== 0) return null
  if (e.shiftKey && !e.ctrlKey) return 'select'
  if (e.ctrlKey && !e.shiftKey) return 'zoom'
  return null
}

export function attachModifierBoxDrag(map: BoxDragMap, handlers: BoxDragHandlers): () => void {
  const container = map.getContainer()
  let gesture: {
    mode: Mode
    start: { x: number; y: number }
    box: HTMLElement | null
    panningWasEnabled: boolean
  } | null = null

  function finish() {
    if (!gesture) return
    gesture.box?.remove()
    if (gesture.panningWasEnabled) map.dragging.enable()
    gesture = null
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.removeEventListener('keydown', onKeyDown)
    // The context menu macOS raises for ctrl+click arrives after mouseup, so keep suppressing it
    // for a moment rather than only while the gesture is active.
    setTimeout(() => container.removeEventListener('contextmenu', suppress), 0)
  }

  function suppress(e: Event) {
    e.preventDefault()
  }

  function onMouseDown(e: MouseEvent) {
    const mode = modeFor(e)
    if (!mode) return
    const start = map.mouseEventToContainerPoint(e)
    gesture = { mode, start, box: null, panningWasEnabled: map.dragging.enabled() }
    map.dragging.disable()
    container.addEventListener('contextmenu', suppress)
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    document.addEventListener('keydown', onKeyDown)
  }

  function exceedsThreshold(point: { x: number; y: number }) {
    if (!gesture) return false
    return Math.hypot(point.x - gesture.start.x, point.y - gesture.start.y) >= DRAG_THRESHOLD_PX
  }

  function onMouseMove(e: MouseEvent) {
    if (!gesture) return
    const point = map.mouseEventToContainerPoint(e)
    if (!gesture.box) {
      if (!exceedsThreshold(point)) return
      gesture.box = document.createElement('div')
      gesture.box.className = BOX_CLASS
      container.appendChild(gesture.box)
    }
    const { start, box } = gesture
    box.style.left = `${Math.min(start.x, point.x)}px`
    box.style.top = `${Math.min(start.y, point.y)}px`
    box.style.width = `${Math.abs(point.x - start.x)}px`
    box.style.height = `${Math.abs(point.y - start.y)}px`
  }

  function onMouseUp(e: MouseEvent) {
    if (!gesture) return
    const { mode, start, box } = gesture
    const end = map.mouseEventToContainerPoint(e)
    const dragged = box !== null || exceedsThreshold(end)
    finish()
    if (!dragged) return

    swallowNextClick()
    const first = map.containerPointToLatLng([start.x, start.y])
    const second = map.containerPointToLatLng([end.x, end.y])
    const bounds: GeoBounds = {
      south: Math.min(first.lat, second.lat),
      west: Math.min(first.lng, second.lng),
      north: Math.max(first.lat, second.lat),
      east: Math.max(first.lng, second.lng),
    }
    if (mode === 'select') handlers.onSelectBox(bounds)
    else handlers.onZoomBox(bounds)
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') finish()
  }

  // The mouseup that ends a drag over a marker would otherwise also fire its click handler and
  // toggle that marker.
  function swallowNextClick() {
    const stop = (e: Event) => e.stopPropagation()
    container.addEventListener('click', stop, true)
    setTimeout(() => container.removeEventListener('click', stop, true), 0)
  }

  container.addEventListener('mousedown', onMouseDown, true)
  return () => {
    container.removeEventListener('mousedown', onMouseDown, true)
    finish()
  }
}
