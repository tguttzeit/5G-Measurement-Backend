import { cleanup, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { router } from './router'
import { useAuth } from './components/AuthProvider'

vi.mock('./components/AuthProvider', () => ({ useAuth: vi.fn() }))
vi.mock('./layout/AppShell', async () => {
  const { Outlet } = await import('react-router-dom')
  return { AppShell: () => <Outlet /> }
})
vi.mock('./pages/TestingVisualizationPage', () => ({
  TestingVisualizationPage: () => <div>testing visualization page</div>,
}))
vi.mock('./pages/MapHeatmapPage', () => ({ MapHeatmapPage: () => <div>map page</div> }))
vi.mock('./pages/LoginPage', () => ({ LoginPage: () => <div>login page</div> }))

const mockUseAuth = vi.mocked(useAuth)

function renderAt(path: string, isSuperuser: boolean) {
  mockUseAuth.mockReturnValue({
    user: { is_superuser: isSuperuser },
    token: null,
    isAuthenticated: true,
    isLoading: false,
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>)
  render(<RouterProvider router={createMemoryRouter(router.routes, { initialEntries: [path] })} />)
}

afterEach(cleanup)

describe('router: test visualization access', () => {
  it('shows the page to superusers', () => {
    renderAt('/testing/visualization', true)

    expect(screen.getByText('testing visualization page')).toBeInTheDocument()
  })

  it('redirects non-superusers to the map', () => {
    renderAt('/testing/visualization', false)

    expect(screen.queryByText('testing visualization page')).not.toBeInTheDocument()
    expect(screen.getByText('map page')).toBeInTheDocument()
  })
})
