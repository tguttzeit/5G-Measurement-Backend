import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { SettingsPage } from './SettingsPage'
import {
  getRawRowCap,
  getShutdownConfirmation,
  putRawRowCap,
  putShutdownConfirmation,
} from '../api/settings'
import { useAuth } from '../components/AuthProvider'
import { ToastProvider } from '../components/ToastProvider'
import { LANGUAGE_KEY } from '../i18n'
import { LanguageProvider } from '../i18n/LanguageProvider'

vi.mock('../components/AuthProvider', () => ({ useAuth: vi.fn() }))
vi.mock('../api/notificationSettings', () => ({
  NOTIFICATION_EVENTS: [],
  getNotificationSettings: vi.fn(() => new Promise(() => {})),
}))
vi.mock('../api/settings', () => ({
  getRawRowCap: vi.fn(),
  putRawRowCap: vi.fn(),
  getShutdownConfirmation: vi.fn(),
  putShutdownConfirmation: vi.fn(),
}))

const mockUseAuth = vi.mocked(useAuth)
const mockGet = vi.mocked(getRawRowCap)
const mockPut = vi.mocked(putRawRowCap)
const mockGetShutdown = vi.mocked(getShutdownConfirmation)
const mockPutShutdown = vi.mocked(putShutdownConfirmation)

const DEFAULT_SHUTDOWN = { mode: 'intervals', intervals: 4, seconds: 60, updated_at: null, updated_by: null } as const

function setting(value: number | null) {
  return { value, updated_at: null, updated_by: null }
}

function loginAs(role: 'guest' | 'user' | 'superuser') {
  mockUseAuth.mockReturnValue({
    user: role === 'guest' ? null : { id: 1, email: 'someone', is_superuser: role === 'superuser' },
  } as ReturnType<typeof useAuth>)
}

function renderPage() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <ToastProvider>
          <SettingsPage />
        </ToastProvider>
      </LanguageProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockGet.mockResolvedValue(setting(null))
  mockPut.mockImplementation(async (value) => setting(value))
  mockGetShutdown.mockResolvedValue(DEFAULT_SHUTDOWN)
  mockPutShutdown.mockImplementation(async (value) => ({ ...value, updated_at: null, updated_by: null }))
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  document.documentElement.lang = ''
})

describe('SettingsPage notification section', () => {
  it('is shown to every logged-in user, superuser or not', () => {
    loginAs('user')
    renderPage()

    expect(screen.getByRole('heading', { name: 'Push notifications' })).toBeInTheDocument()
  })

  it('is hidden from guests', () => {
    loginAs('guest')
    renderPage()

    expect(screen.queryByRole('heading', { name: 'Push notifications' })).not.toBeInTheDocument()
  })
})

describe('SettingsPage language section', () => {
  it('is available to guests, who see no superuser controls', () => {
    loginAs('guest')

    renderPage()

    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.getByLabelText('Interface language')).toHaveValue('en')
    expect(screen.queryByText('Raw datapoint limit')).not.toBeInTheDocument()
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('switches the UI to German, persists the choice and sets <html lang>', async () => {
    loginAs('guest')
    renderPage()

    fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'de' } })

    expect(await screen.findByRole('heading', { name: 'Einstellungen' })).toBeInTheDocument()
    expect(localStorage.getItem(LANGUAGE_KEY)).toBe('de')
    expect(document.documentElement.lang).toBe('de')
  })

  it('switches back to English', async () => {
    loginAs('guest')
    renderPage()
    fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'de' } })
    await screen.findByRole('heading', { name: 'Einstellungen' })

    fireEvent.change(screen.getByLabelText('Oberflächensprache'), { target: { value: 'en' } })

    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(localStorage.getItem(LANGUAGE_KEY)).toBe('en')
    expect(document.documentElement.lang).toBe('en')
  })

  it('keeps working when localStorage rejects writes', async () => {
    loginAs('guest')
    renderPage()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })

    fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'de' } })

    expect(await screen.findByRole('heading', { name: 'Einstellungen' })).toBeInTheDocument()
    vi.restoreAllMocks()
  })
})

describe('SettingsPage raw datapoint limit section', () => {
  it('is hidden for logged-in non-superusers', () => {
    loginAs('user')

    renderPage()

    expect(screen.queryByText('Raw datapoint limit')).not.toBeInTheDocument()
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('shows the unlimited default to superusers', async () => {
    loginAs('superuser')

    renderPage()

    expect(await screen.findByText('Currently unlimited.')).toBeInTheDocument()
    expect(screen.getByLabelText('Unlimited')).toBeChecked()
    expect(screen.queryByLabelText('Limit (number of datapoints)')).not.toBeInTheDocument()
  })

  it('shows an error when loading fails', async () => {
    loginAs('superuser')
    mockGet.mockRejectedValue(new Error('boom'))

    renderPage()

    expect(await screen.findByText('Could not load the raw datapoint limit.')).toBeInTheDocument()
  })

  it('saves a numeric limit and confirms with a toast', async () => {
    loginAs('superuser')
    renderPage()
    await screen.findByText('Currently unlimited.')

    fireEvent.click(screen.getByLabelText('Unlimited'))
    fireEvent.change(screen.getByLabelText('Limit (number of datapoints)'), { target: { value: '20000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockPut).toHaveBeenCalledWith(20000))
    expect(await screen.findByText('Raw datapoint limit saved.')).toBeInTheDocument()
    expect(screen.getByText('Currently limited to 20000 datapoints.')).toBeInTheDocument()
  })

  it('saves null when switched back to unlimited', async () => {
    loginAs('superuser')
    mockGet.mockResolvedValue(setting(500))
    renderPage()
    await screen.findByText('Currently limited to 500 datapoints.')

    fireEvent.click(screen.getByLabelText('Unlimited'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockPut).toHaveBeenCalledWith(null))
  })

  it.each(['', '0', '-5', '1.5', '1e3', 'abc', '2147483648'])(
    'rejects the invalid limit %j without calling the API',
    async (input) => {
      loginAs('superuser')
      renderPage()
      await screen.findByText('Currently unlimited.')

      fireEvent.click(screen.getByLabelText('Unlimited'))
      fireEvent.change(screen.getByLabelText('Limit (number of datapoints)'), { target: { value: input } })
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))

      expect(await screen.findByRole('alert')).toHaveTextContent('Enter a whole number of at least 1.')
      expect(mockPut).not.toHaveBeenCalled()
    },
  )

  it('shows an error toast when saving fails', async () => {
    loginAs('superuser')
    mockPut.mockRejectedValue(new Error('boom'))
    renderPage()
    await screen.findByText('Currently unlimited.')

    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Could not save the raw datapoint limit.')).toBeInTheDocument()
  })

  it('is translated when German is active', async () => {
    loginAs('superuser')
    renderPage()
    await screen.findByText('Currently unlimited.')

    fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'de' } })

    expect(await screen.findByText('Limit für Rohdatenpunkte')).toBeInTheDocument()
    expect(screen.getByText('Derzeit unbegrenzt.')).toBeInTheDocument()
  })
})

describe('SettingsPage shutdown confirmation section', () => {
  const section = async () => {
    loginAs('superuser')
    renderPage()
    await screen.findByText('Currently 4 heartbeat intervals.')
  }

  it('is hidden for guests and logged-in non-superusers', () => {
    loginAs('user')

    renderPage()

    expect(screen.queryByText('Shutdown confirmation')).not.toBeInTheDocument()
    expect(mockGetShutdown).not.toHaveBeenCalled()
  })

  it('shows the current rule to superusers', async () => {
    await section()

    expect(screen.getByLabelText('Mode')).toHaveValue('intervals')
    expect(screen.getByLabelText('Heartbeat intervals')).toHaveValue(4)
    expect(screen.queryByLabelText('Time span (seconds)')).not.toBeInTheDocument()
  })

  it('describes a stored fixed time span', async () => {
    loginAs('superuser')
    mockGetShutdown.mockResolvedValue({ ...DEFAULT_SHUTDOWN, mode: 'seconds', seconds: 90 })

    renderPage()

    expect(await screen.findByText('Currently a fixed time span of 90 s.')).toBeInTheDocument()
    expect(screen.getByLabelText('Time span (seconds)')).toHaveValue(90)
  })

  it('shows an error when loading fails', async () => {
    loginAs('superuser')
    mockGetShutdown.mockRejectedValue(new Error('boom'))

    renderPage()

    expect(await screen.findByText('Could not load the shutdown confirmation.')).toBeInTheDocument()
  })

  it('saves a number of intervals and confirms with a toast', async () => {
    await section()

    fireEvent.change(screen.getByLabelText('Heartbeat intervals'), { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save shutdown confirmation' }))

    await waitFor(() =>
      expect(mockPutShutdown).toHaveBeenCalledWith({ mode: 'intervals', intervals: 6, seconds: 60 }),
    )
    expect(await screen.findByText('Shutdown confirmation saved.')).toBeInTheDocument()
    expect(screen.getByText('Currently 6 heartbeat intervals.')).toBeInTheDocument()
  })

  it('saves a fixed time span and keeps the stored interval count', async () => {
    await section()

    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'seconds' } })
    fireEvent.change(screen.getByLabelText('Time span (seconds)'), { target: { value: '120' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save shutdown confirmation' }))

    await waitFor(() =>
      expect(mockPutShutdown).toHaveBeenCalledWith({ mode: 'seconds', intervals: 4, seconds: 120 }),
    )
    expect(await screen.findByText('Currently a fixed time span of 120 s.')).toBeInTheDocument()
  })

  it.each(['', '0', '21', '-1', '2.5', '1e1', 'abc'])(
    'rejects %j as a number of intervals without calling the API',
    async (input) => {
      await section()

      fireEvent.change(screen.getByLabelText('Heartbeat intervals'), { target: { value: input } })
      fireEvent.click(screen.getByRole('button', { name: 'Save shutdown confirmation' }))

      expect(await screen.findByRole('alert')).toHaveTextContent('Enter a whole number from 1 to 20.')
      expect(mockPutShutdown).not.toHaveBeenCalled()
    },
  )

  it.each(['', '9', '3601', '-60', '1e2', 'abc', 'Infinity', 'NaN'])(
    'rejects %j as a time span without calling the API',
    async (input) => {
      await section()
      fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'seconds' } })

      fireEvent.change(screen.getByLabelText('Time span (seconds)'), { target: { value: input } })
      fireEvent.click(screen.getByRole('button', { name: 'Save shutdown confirmation' }))

      expect(await screen.findByRole('alert')).toHaveTextContent('Enter a number from 10 to 3600.')
      expect(mockPutShutdown).not.toHaveBeenCalled()
    },
  )

  it('does not validate the field of the mode that is not selected', async () => {
    await section()
    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'seconds' } })
    fireEvent.change(screen.getByLabelText('Time span (seconds)'), { target: { value: '100' } })
    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'intervals' } })

    fireEvent.click(screen.getByRole('button', { name: 'Save shutdown confirmation' }))

    await waitFor(() =>
      expect(mockPutShutdown).toHaveBeenCalledWith({ mode: 'intervals', intervals: 4, seconds: 100 }),
    )
  })

  it('warns when the time span is shorter than the default heartbeat interval', async () => {
    await section()
    expect(screen.queryByText(/shorter than a heartbeat interval/)).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'seconds' } })
    fireEvent.change(screen.getByLabelText('Time span (seconds)'), { target: { value: '30' } })

    expect(screen.getByText(/shorter than a heartbeat interval/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Time span (seconds)'), { target: { value: '60' } })
    expect(screen.queryByText(/shorter than a heartbeat interval/)).not.toBeInTheDocument()
  })

  it('still lets a short time span be saved', async () => {
    await section()
    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'seconds' } })
    fireEvent.change(screen.getByLabelText('Time span (seconds)'), { target: { value: '30' } })

    fireEvent.click(screen.getByRole('button', { name: 'Save shutdown confirmation' }))

    await waitFor(() => expect(mockPutShutdown).toHaveBeenCalledWith({ mode: 'seconds', intervals: 4, seconds: 30 }))
  })

  it('shows an error toast when saving fails', async () => {
    await section()
    mockPutShutdown.mockRejectedValue(new Error('boom'))

    fireEvent.click(screen.getByRole('button', { name: 'Save shutdown confirmation' }))

    expect(await screen.findByText('Could not save the shutdown confirmation.')).toBeInTheDocument()
  })

  it('is translated when German is active', async () => {
    await section()

    fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'de' } })

    expect(await screen.findByText('Herunterfahren bestätigen')).toBeInTheDocument()
  })
})
