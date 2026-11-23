import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import i18n from '../i18n'
import { Timestamp } from './Timestamp'

afterEach(cleanup)

const VALUE = new Date(2026, 9, 23, 14, 5, 9).toISOString()

describe('Timestamp', () => {
  it('renders a <time> element with the ISO value and the time zone in its tooltip', () => {
    render(<Timestamp value={VALUE} />)
    const element = screen.getByText('23/10/2026, 14:05:09')
    expect(element.tagName).toBe('TIME')
    expect(element).toHaveAttribute('datetime', VALUE)
    expect(element.getAttribute('title')).toContain(VALUE)
  })

  it('follows the selected language', async () => {
    render(<Timestamp value={VALUE} />)
    await act(() => i18n.changeLanguage('de'))
    expect(screen.getByText('23.10.2026, 14:05:09')).toBeInTheDocument()
  })

  it('renders only the time or only the date on request', () => {
    render(
      <>
        <Timestamp value={VALUE} part="time" />
        <Timestamp value="2026-10-23" part="date" />
      </>,
    )
    expect(screen.getByText('14:05:09')).toBeInTheDocument()
    expect(screen.getByText('23/10/2026')).toBeInTheDocument()
  })

  it('renders a plain placeholder without attributes for invalid values', () => {
    const { container } = render(<Timestamp value="<script>alert(1)</script>" />)
    expect(container.querySelector('time')).toBeNull()
    expect(container).toHaveTextContent('—')
    expect(container.innerHTML).not.toContain('script')
  })
})
