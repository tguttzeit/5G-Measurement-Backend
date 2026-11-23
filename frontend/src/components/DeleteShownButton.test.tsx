import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DeleteShownButton } from './DeleteShownButton'
import { ApiError } from '../api/client'
import { dismissCommandStatus, type CommandStatusItem } from '../api/commands'

vi.mock('../api/commands', () => ({ dismissCommandStatus: vi.fn() }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    body?: unknown
    constructor(message: string, status: number, body?: unknown) {
      super(message)
      this.status = status
      this.body = body
    }
  },
}))

const mockDismiss = vi.mocked(dismissCommandStatus)

function item(overrides: Partial<CommandStatusItem>): CommandStatusItem {
  return {
    command_id: 1,
    kind: 'command',
    name: 'reboot-now',
    detail: null,
    state: 'success',
    complete: true,
    in_queue: false,
    queued_at: null,
    delivered_at: null,
    received_at: null,
    result_at: null,
    removed_at: null,
    promoted_at: null,
    expired_at: null,
    expires_at: null,
    error: null,
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('DeleteShownButton', () => {
  it.each(['success', 'failed', 'not_applicable', 'removed', 'expired', 'promoted'] as const)(
    'sends a %s command that is not queued',
    async (state) => {
      mockDismiss.mockResolvedValue({ dismissed: [1] })
      const onDeleted = vi.fn()
      render(<DeleteShownButton deviceId="device-01" shown={[item({ state })]} onDeleted={onDeleted} />)

      fireEvent.click(screen.getByRole('button', { name: 'Delete shown' }))

      await waitFor(() => expect(onDeleted).toHaveBeenCalled())
      expect(mockDismiss).toHaveBeenCalledWith('device-01', [1])
    },
  )

  it.each([
    ['queued', false, true],
    ['delivered', false, true],
    ['received', false, true],
    ['an applied config override that stays queued', true, true],
  ])('never sends %s', (_label, complete, inQueue) => {
    render(
      <DeleteShownButton
        deviceId="device-01"
        shown={[item({ state: 'delivered', complete, in_queue: inQueue })]}
        onDeleted={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'Delete shown' })).toBeDisabled()
  })

  it('sends the ids of the finished shown items only', async () => {
    mockDismiss.mockResolvedValue({ dismissed: [2, 4] })
    render(
      <DeleteShownButton
        deviceId="device 1"
        shown={[
          item({ command_id: 2 }),
          item({ command_id: 3, state: 'received', complete: false, in_queue: true }),
          item({ command_id: 4, state: 'failed' }),
        ]}
        onDeleted={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Delete shown' }))

    await waitFor(() => expect(mockDismiss).toHaveBeenCalledWith('device 1', [2, 4]))
  })

  it('shows the error and does not report a deletion when the request fails', async () => {
    mockDismiss.mockRejectedValue(new ApiError('Forbidden', 403, { detail: 'Not allowed' }))
    const onDeleted = vi.fn()
    render(<DeleteShownButton deviceId="device-01" shown={[item({})]} onDeleted={onDeleted} />)

    fireEvent.click(screen.getByRole('button', { name: 'Delete shown' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed')
    expect(onDeleted).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Delete shown' })).not.toBeDisabled()
  })

  it('falls back to a generic message for an unexpected error', async () => {
    mockDismiss.mockRejectedValue(new Error('network'))
    render(<DeleteShownButton deviceId="device-01" shown={[item({})]} onDeleted={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Delete shown' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to delete the shown commands')
  })
})
