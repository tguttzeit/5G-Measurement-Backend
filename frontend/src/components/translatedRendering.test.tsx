import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LanguageProvider } from '../i18n/LanguageProvider'
import { openUploadStream, type UploadStreamHandlers } from '../api/uploadStream'
import type { CommandStatusItem } from '../api/commands'
import i18n from '../i18n'
import { useAuth } from './AuthProvider'
import { buildSteps } from './CommandStatusList'
import { LanguageMenu } from './LanguageMenu'
import { ThemeProvider } from './ThemeProvider'
import { ToastProvider } from './ToastProvider'
import { UploadNotifications } from './UploadNotifications'
import { UserMenu } from './UserMenu'

vi.mock('./AuthProvider', () => ({ useAuth: vi.fn() }))
vi.mock('../api/uploadStream', () => ({ openUploadStream: vi.fn() }))

const mockUseAuth = vi.mocked(useAuth)
const mockOpenUploadStream = vi.mocked(openUploadStream)

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function emitUpload(event: Parameters<UploadStreamHandlers['onUpload']>[0]) {
  let handlers!: UploadStreamHandlers
  mockOpenUploadStream.mockImplementation((h) => {
    handlers = h
    return vi.fn()
  })
  mockUseAuth.mockReturnValue({ user: { is_superuser: true } } as ReturnType<typeof useAuth>)
  render(
    <MemoryRouter>
      <ToastProvider>
        <UploadNotifications />
      </ToastProvider>
    </MemoryRouter>,
  )
  act(() => handlers.onUpload(event))
}

const toastText = () => document.querySelector('.toast__message')?.textContent ?? ''

describe('translated rendering', () => {
  it('renders the upload toast in German with the right plural form', async () => {
    await i18n.changeLanguage('de')

    emitUpload({ device_id: 'dev', run_ids: ['abc'], point_count: 1, received_at: '2026-10-16T10:08:45+00:00' })

    expect(toastText()).toBe('Upload erfolgreich: dev hat 1 Messpunkt gesendet, von Lauf abc.')
    expect(screen.getByRole('link', { name: 'In Messläufen ansehen' })).toBeInTheDocument()
  })

  it('renders interpolated values as plain text, never as markup', () => {
    const hostile = '<script>window.__pwned = true</script><img src=x onerror=alert(1)>'

    emitUpload({ device_id: hostile, run_ids: [null], point_count: 2, received_at: '2026-10-16T10:08:45+00:00' })

    expect(toastText()).toContain(hostile)
    expect(document.querySelector('.toast__message script')).toBeNull()
    expect(document.querySelector('.toast__message img')).toBeNull()
  })

  it('translates the command timeline labels from the shared i18n instance', async () => {
    const queued = {
      kind: 'command',
      name: 'reboot-now',
      state: 'queued',
      complete: false,
      in_queue: true,
      queued_at: '2026-10-16T10:00:00+00:00',
      delivered_at: null,
      received_at: null,
      result_at: null,
    } as unknown as CommandStatusItem

    expect(buildSteps(queued).map((step) => step.label)).toEqual(['Queued', 'Sent', 'Received', 'Result'])
    await i18n.changeLanguage('de')
    expect(buildSteps(queued).map((step) => step.label)).toEqual([
      'In Warteschlange',
      'Gesendet',
      'Empfangen',
      'Ergebnis',
    ])
  })

  it('offers the Settings page to logged-in users', () => {
    mockUseAuth.mockReturnValue({
      user: { email: 'someone', is_superuser: false },
      logout: vi.fn(),
    } as unknown as ReturnType<typeof useAuth>)

    render(
      <MemoryRouter>
        <ThemeProvider>
          <UserMenu />
        </ThemeProvider>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Open user menu' }))

    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings')
  })

  it('lets guests pick the language from the globe menu', async () => {
    render(
      <LanguageProvider>
        <LanguageMenu />
      </LanguageProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Interface language' }))
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByRole('button', { name: 'Deutsch' }))

    expect(await screen.findByRole('button', { name: 'Oberflächensprache' })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('de')
    expect(localStorage.getItem('language_preference')).toBe('de')
    expect(screen.queryByRole('button', { name: 'Deutsch' })).not.toBeInTheDocument()
  })
})
