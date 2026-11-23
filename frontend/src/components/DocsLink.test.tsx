import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import i18n from '../i18n'
import { LanguageProvider } from '../i18n/LanguageProvider'
import { DocsLink } from './DocsLink'

afterEach(cleanup)

function renderLink() {
  render(
    <LanguageProvider>
      <DocsLink />
    </LanguageProvider>,
  )
  return screen.getByRole('link')
}

describe('DocsLink', () => {
  it('points to the German documentation when the UI language is German', async () => {
    await act(() => i18n.changeLanguage('de'))
    const link = renderLink()
    expect(link.getAttribute('href')).toBe('/docs/de/')
    expect(link.textContent).toBe('Dokumentation')
  })

  it('points to the English documentation when the UI language is English', async () => {
    await act(() => i18n.changeLanguage('en'))
    const link = renderLink()
    expect(link.getAttribute('href')).toBe('/docs/en/')
    expect(link.textContent).toBe('Documentation')
  })
})
