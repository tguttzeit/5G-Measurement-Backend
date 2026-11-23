import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { attachModifierBoxDrag, type BoxDragMap } from './modifierBoxDrag'
import type { GeoBounds } from './selectionGeometry'

function makeMap(container: HTMLElement) {
  const draggingEnabled = { value: true }
  const map: BoxDragMap = {
    getContainer: () => container,
    mouseEventToContainerPoint: (e) => ({ x: e.clientX, y: e.clientY }),
    containerPointToLatLng: ([x, y]) => ({ lat: y, lng: x }),
    dragging: {
      enabled: () => draggingEnabled.value,
      enable: () => {
        draggingEnabled.value = true
      },
      disable: () => {
        draggingEnabled.value = false
      },
    },
  }
  return { map, draggingEnabled }
}

function mouse(type: string, init: MouseEventInit) {
  return new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, ...init })
}

describe('attachModifierBoxDrag', () => {
  let container: HTMLElement
  let onZoomBox: ReturnType<typeof vi.fn<(bounds: GeoBounds) => void>>
  let onSelectBox: ReturnType<typeof vi.fn<(bounds: GeoBounds) => void>>
  let detach: () => void
  let draggingEnabled: { value: boolean }

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    onZoomBox = vi.fn()
    onSelectBox = vi.fn()
    const made = makeMap(container)
    draggingEnabled = made.draggingEnabled
    detach = attachModifierBoxDrag(made.map, { onZoomBox, onSelectBox })
  })

  afterEach(() => {
    detach()
    container.remove()
  })

  function drag(modifiers: MouseEventInit, from = [10, 20], to = [110, 90]) {
    container.dispatchEvent(mouse('mousedown', { clientX: from[0], clientY: from[1], ...modifiers }))
    document.dispatchEvent(mouse('mousemove', { clientX: to[0], clientY: to[1], ...modifiers }))
    document.dispatchEvent(mouse('mouseup', { clientX: to[0], clientY: to[1], ...modifiers }))
  }

  it('reports a shift+drag rectangle as a selection box', () => {
    drag({ shiftKey: true })
    expect(onSelectBox).toHaveBeenCalledWith({ south: 20, west: 10, north: 90, east: 110 })
    expect(onZoomBox).not.toHaveBeenCalled()
  })

  it('reports a ctrl+drag rectangle as a zoom box, normalising drag direction', () => {
    drag({ ctrlKey: true }, [110, 90], [10, 20])
    expect(onZoomBox).toHaveBeenCalledWith({ south: 20, west: 10, north: 90, east: 110 })
    expect(onSelectBox).not.toHaveBeenCalled()
  })

  it('ignores drags without a modifier key', () => {
    drag({})
    expect(onSelectBox).not.toHaveBeenCalled()
    expect(onZoomBox).not.toHaveBeenCalled()
  })

  it('ignores drags with both modifiers held', () => {
    drag({ shiftKey: true, ctrlKey: true })
    expect(onSelectBox).not.toHaveBeenCalled()
    expect(onZoomBox).not.toHaveBeenCalled()
  })

  it('treats a movement below the pixel threshold as a click, not a drag', () => {
    drag({ shiftKey: true }, [10, 20], [12, 21])
    expect(onSelectBox).not.toHaveBeenCalled()
  })

  it('disables map panning during the drag and restores it afterwards', () => {
    container.dispatchEvent(mouse('mousedown', { clientX: 0, clientY: 0, shiftKey: true }))
    expect(draggingEnabled.value).toBe(false)
    document.dispatchEvent(mouse('mouseup', { clientX: 50, clientY: 50, shiftKey: true }))
    expect(draggingEnabled.value).toBe(true)
  })

  it('does not re-enable panning that was disabled before the drag', () => {
    draggingEnabled.value = false
    drag({ shiftKey: true })
    expect(draggingEnabled.value).toBe(false)
  })

  it('draws a rectangle while dragging and removes it afterwards', () => {
    container.dispatchEvent(mouse('mousedown', { clientX: 10, clientY: 20, shiftKey: true }))
    document.dispatchEvent(mouse('mousemove', { clientX: 110, clientY: 90, shiftKey: true }))
    expect(container.querySelector('.map-box-drag')).not.toBeNull()
    document.dispatchEvent(mouse('mouseup', { clientX: 110, clientY: 90, shiftKey: true }))
    expect(container.querySelector('.map-box-drag')).toBeNull()
  })

  it('swallows the click that follows a completed drag', () => {
    const clicked = vi.fn()
    const target = document.createElement('span')
    container.appendChild(target)
    target.addEventListener('click', clicked)
    drag({ shiftKey: true })
    target.dispatchEvent(mouse('click', { shiftKey: true }))
    expect(clicked).not.toHaveBeenCalled()
  })

  it('lets a plain shift-click through', () => {
    const clicked = vi.fn()
    const target = document.createElement('span')
    container.appendChild(target)
    target.addEventListener('click', clicked)
    drag({ shiftKey: true }, [10, 20], [11, 20])
    target.dispatchEvent(mouse('click', { shiftKey: true }))
    expect(clicked).toHaveBeenCalled()
  })

  it('suppresses the context menu macOS raises for ctrl+click during a ctrl drag', () => {
    container.dispatchEvent(mouse('mousedown', { clientX: 0, clientY: 0, ctrlKey: true }))
    const contextMenu = mouse('contextmenu', { ctrlKey: true })
    container.dispatchEvent(contextMenu)
    expect(contextMenu.defaultPrevented).toBe(true)
  })

  it('cancels the drag on Escape', () => {
    container.dispatchEvent(mouse('mousedown', { clientX: 0, clientY: 0, shiftKey: true }))
    document.dispatchEvent(mouse('mousemove', { clientX: 50, clientY: 50, shiftKey: true }))
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    document.dispatchEvent(mouse('mouseup', { clientX: 50, clientY: 50, shiftKey: true }))
    expect(onSelectBox).not.toHaveBeenCalled()
    expect(draggingEnabled.value).toBe(true)
  })
})
