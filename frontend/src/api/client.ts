import i18n from '../i18n'
import { TOKEN_KEY, clearAuthStorage } from '../components/AuthProvider'

// Same-origin API base: requests go to /api/* and are proxied to the FastAPI
// backend by Vite in development and by the Caddy reverse proxy in production.
const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly body?: unknown

  constructor(message: string, status: number, body?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY)

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    const body = await response.json().catch(() => undefined)

    if (response.status === 401) {
      // Catches any reason the token stopped working -- expiry, revocation, a password change
      // elsewhere -- not just clock-based expiry (that's ProtectedRoute's job, see AuthProvider).
      clearAuthStorage()
      window.location.href = '/login?sessionExpired=1'
    }

    throw new ApiError(
      i18n.t('common:requestFailed', { path, status: response.status }),
      response.status,
      body,
    )
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export const apiClient = {
  get: <T>(path: string, init?: RequestInit) => request<T>(path, init),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PUT',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
