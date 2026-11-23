import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InfoPopover } from './InfoPopover'

afterEach(cleanup)

const renderPopover = () =>
  render(
    <div>
      <button>outside</button>
      <InfoPopover label="More info">Explanation text</InfoPopover>
    </div>,
  )

const infoButton = () => screen.getByRole('button', { name: 'More info' })

describe('InfoPopover', () => {
  it('is closed by default', () => {
    renderPopover()

    expect(infoButton()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Explanation text')).not.toBeInTheDocument()
  })

  it('toggles on click (keyboard and touch)', () => {
    renderPopover()

    fireEvent.click(infoButton())
    expect(infoButton()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('note')).toHaveTextContent('Explanation text')
    expect(infoButton()).toHaveAttribute('aria-controls', screen.getByRole('note').id)

    fireEvent.click(infoButton())
    expect(screen.queryByText('Explanation text')).not.toBeInTheDocument()
  })

  it('opens on mouse hover and closes when the mouse leaves', () => {
    const { container } = renderPopover()
    const wrapper = container.querySelector('.info-popover') as HTMLElement

    fireEvent.pointerEnter(wrapper, { pointerType: 'mouse' })
    expect(screen.getByText('Explanation text')).toBeInTheDocument()

    fireEvent.pointerLeave(wrapper, { pointerType: 'mouse' })
    expect(screen.queryByText('Explanation text')).not.toBeInTheDocument()
  })

  it('ignores the pointer events emulated by a touch tap', () => {
    const { container } = renderPopover()
    const wrapper = container.querySelector('.info-popover') as HTMLElement

    fireEvent.pointerEnter(wrapper, { pointerType: 'touch' })
    expect(screen.queryByText('Explanation text')).not.toBeInTheDocument()
  })

  it('closes on Escape', () => {
    renderPopover()
    fireEvent.click(infoButton())

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByText('Explanation text')).not.toBeInTheDocument()
  })

  it('closes when pressing outside, but not inside, the popover', () => {
    renderPopover()
    fireEvent.click(infoButton())

    fireEvent.pointerDown(screen.getByText('Explanation text'))
    expect(screen.getByText('Explanation text')).toBeInTheDocument()

    fireEvent.pointerDown(screen.getByText('outside'))
    expect(screen.queryByText('Explanation text')).not.toBeInTheDocument()
  })

  it('leaves no document listeners behind once closed or unmounted', () => {
    const add = vi.spyOn(document, 'addEventListener')
    const remove = vi.spyOn(document, 'removeEventListener')
    const { unmount } = renderPopover()
    expect(add).not.toHaveBeenCalledWith('keydown', expect.anything())

    fireEvent.click(infoButton())
    expect(add).toHaveBeenCalledWith('keydown', expect.any(Function))
    unmount()

    for (const type of ['keydown', 'pointerdown']) {
      const added = add.mock.calls.filter(([name]) => name === type)
      const removed = remove.mock.calls.filter(([name]) => name === type)
      expect(removed).toHaveLength(added.length)
    }
    add.mockRestore()
    remove.mockRestore()
  })
})
