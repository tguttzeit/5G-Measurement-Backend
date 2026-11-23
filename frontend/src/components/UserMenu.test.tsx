import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from './AuthProvider'
import { ThemeProvider } from './ThemeProvider'
import { UserMenu } from './UserMenu'

vi.mock('./AuthProvider', () => ({ useAuth: vi.fn() }))

const mockUseAuth = vi.mocked(useAuth)

function renderMenu(isSuperuser: boolean) {
  mockUseAuth.mockReturnValue({
    user: { email: 'a@b.c', is_superuser: isSuperuser },
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>)
  render(
    <MemoryRouter>
      <ThemeProvider>
        <UserMenu />
      </ThemeProvider>
    </MemoryRouter>,
  )
  fireEvent.click(screen.getByRole('button', { name: /menu/i }))
}

afterEach(cleanup)

describe('UserMenu test visualization entry', () => {
  it('is listed for superusers', () => {
    renderMenu(true)

    expect(document.querySelector('a[href="/testing/visualization"]')).not.toBeNull()
  })

  it('is hidden for non-superusers', () => {
    renderMenu(false)

    expect(document.querySelector('a[href="/status"]')).not.toBeNull()
    expect(document.querySelector('a[href="/testing/visualization"]')).toBeNull()
  })
})
