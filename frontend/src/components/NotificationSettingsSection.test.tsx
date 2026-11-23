import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import {
  getNotificationSettings,
  putNotificationSettings,
  regenerateNotificationTopic,
  sendTestNotification,
  type NotificationSettings,
} from '../api/notificationSettings'
import { LanguageProvider } from '../i18n/LanguageProvider'
import { NotificationSettingsSection } from './NotificationSettingsSection'
import { ToastProvider } from './ToastProvider'

vi.mock('../api/notificationSettings', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/notificationSettings')>()),
  getNotificationSettings: vi.fn(),
  putNotificationSettings: vi.fn(),
  regenerateNotificationTopic: vi.fn(),
  sendTestNotification: vi.fn(),
}))

const mockGet = vi.mocked(getNotificationSettings)
const mockPut = vi.mocked(putNotificationSettings)
const mockRegenerate = vi.mocked(regenerateNotificationTopic)
const mockTest = vi.mocked(sendTestNotification)

const DISABLED: NotificationSettings = {
  enabled: false,
  events: [],
  topic: 'secret-topic-1',
  server_url: 'https://ntfy.sh',
}

function renderSection() {
  return render(
    <LanguageProvider>
      <ToastProvider>
        <NotificationSettingsSection />
      </ToastProvider>
    </LanguageProvider>,
  )
}

beforeEach(() => {
  mockGet.mockResolvedValue(DISABLED)
  mockPut.mockImplementation(async (value) => ({ ...DISABLED, ...value }))
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe('NotificationSettingsSection', () => {
  it('shows notifications as off with the event list disabled by default', async () => {
    renderSection()

    expect(await screen.findByLabelText('Send me notifications')).not.toBeChecked()
    expect(screen.getByLabelText('Error')).toBeDisabled()
  })

  it('shows the topic and the server it lives on', async () => {
    renderSection()

    expect(await screen.findByText('secret-topic-1')).toBeInTheDocument()
    expect(screen.getByText(/https:\/\/ntfy\.sh/)).toBeInTheDocument()
  })

  it('saves the master switch and the chosen events', async () => {
    renderSection()
    fireEvent.click(await screen.findByLabelText('Send me notifications'))
    fireEvent.click(screen.getByLabelText('Error'))
    fireEvent.click(screen.getByLabelText('New runs uploaded'))
    fireEvent.click(screen.getByLabelText('Error'))

    fireEvent.click(screen.getByRole('button', { name: 'Save notification settings' }))

    await waitFor(() =>
      expect(mockPut).toHaveBeenCalledWith({ enabled: true, events: ['runs_uploaded'] }),
    )
    expect(await screen.findByText('Notification settings saved.')).toBeInTheDocument()
  })

  it('reports a failed load', async () => {
    mockGet.mockRejectedValue(new Error('down'))

    renderSection()

    expect(await screen.findByText('Could not load the notification settings.')).toBeInTheDocument()
  })

  it('reports a failed save', async () => {
    mockPut.mockRejectedValue(new Error('down'))
    renderSection()

    fireEvent.click(await screen.findByRole('button', { name: 'Save notification settings' }))

    expect(await screen.findByText('Could not save the notification settings.')).toBeInTheDocument()
  })

  it('copies the topic to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderSection()

    fireEvent.click(await screen.findByRole('button', { name: 'Copy topic' }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('secret-topic-1'))
  })

  it('sends a test notification', async () => {
    mockTest.mockResolvedValue(undefined)
    renderSection()

    fireEvent.click(await screen.findByRole('button', { name: 'Send test notification' }))

    expect(await screen.findByText('Test notification sent.')).toBeInTheDocument()
  })

  it('tells the user to wait when the test is rate limited', async () => {
    mockTest.mockRejectedValue(new ApiError('too many', 429))
    renderSection()

    fireEvent.click(await screen.findByRole('button', { name: 'Send test notification' }))

    expect(await screen.findByText(/Please wait a few seconds/)).toBeInTheDocument()
  })

  it('regenerates the topic only after confirmation and shows the new one', async () => {
    mockRegenerate.mockResolvedValue({ ...DISABLED, topic: 'secret-topic-2' })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    renderSection()
    const button = await screen.findByRole('button', { name: 'Regenerate topic' })

    fireEvent.click(button)
    expect(mockRegenerate).not.toHaveBeenCalled()
    fireEvent.click(button)

    expect(await screen.findByText('secret-topic-2')).toBeInTheDocument()
    expect(confirm).toHaveBeenCalledTimes(2)
  })
})
