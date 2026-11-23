import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppShell } from './layout/AppShell'
import { MissionStatusPage } from './pages/MissionStatusPage'
import { RemoteConfigurationPage } from './pages/RemoteConfigurationPage'
import { MapHeatmapPage } from './pages/MapHeatmapPage'
import { RunsPage } from './pages/RunsPage'
import { RunTrashPage } from './pages/RunTrashPage'
import { LoginPage } from './pages/LoginPage'
import { TestingVisualizationPage } from './pages/TestingVisualizationPage'
import { AdminUsersPage } from './pages/AdminUsersPage'
import { AdminCampaignsPage } from './pages/AdminCampaignsPage'
import { SettingsPage } from './pages/SettingsPage'
import { ChangePasswordPage } from './pages/ChangePasswordPage'
import { ProtectedRoute } from './components/ProtectedRoute'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/map" replace /> },
      { path: 'login', element: <LoginPage /> },
      { path: 'status', element: <ProtectedRoute><MissionStatusPage /></ProtectedRoute> },
      {
        path: 'remote-configuration',
        element: (
          <ProtectedRoute requireSuperuser>
            <RemoteConfigurationPage />
          </ProtectedRoute>
        ),
      },
      { path: 'map', element: <MapHeatmapPage /> },
      { path: 'runs', element: <ProtectedRoute><RunsPage /></ProtectedRoute> },
      {
        path: 'runs/trash',
        element: (
          <ProtectedRoute requireSuperuser>
            <RunTrashPage />
          </ProtectedRoute>
        ),
      },
      { path: 'find-gps-fix', element: <Navigate to="/testing/visualization" replace /> },
      {
        path: 'testing/visualization',
        element: (
          <ProtectedRoute requireSuperuser>
            <TestingVisualizationPage />
          </ProtectedRoute>
        ),
      },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'change-password', element: <ProtectedRoute><ChangePasswordPage /></ProtectedRoute> },
      {
        path: 'admin/users',
        element: (
          <ProtectedRoute requireSuperuser>
            <AdminUsersPage />
          </ProtectedRoute>
        ),
      },
      {
        path: 'admin/campaigns',
        element: (
          <ProtectedRoute requireSuperuser>
            <AdminCampaignsPage />
          </ProtectedRoute>
        ),
      },
    ],
  },
])
