import i18n from '../i18n'
import { apiClient } from './client'

const API_BASE = '/api'

interface LoginResponse {
  access_token: string
  token_type: string
}

interface UserResponse {
  id: number
  email: string  // This is treated as username in the UI
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
}

export async function login(email: string, password: string): Promise<{ token: string; user: UserResponse }> {
  // fastapi-users expects email and password as form data
  const formData = new URLSearchParams()
  formData.append('username', email)  // Send as username to match fastapi-users
  formData.append('password', password)

  const response = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: formData.toString(),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: i18n.t('auth:loginFailed') }))
    throw new Error(error.detail || i18n.t('auth:loginFailed'))
  }

  const { access_token }: LoginResponse = await response.json()

  // Fetch user info with the token
  const userResponse = await fetch(`${API_BASE}/auth/me`, {
    headers: {
      Authorization: `Bearer ${access_token}`,
    },
  })

  if (!userResponse.ok) {
    throw new Error(i18n.t('auth:fetchUserFailed'))
  }

  const user: UserResponse = await userResponse.json()

  return { token: access_token, user }
}

export async function getCurrentUser(token: string): Promise<UserResponse> {
  const response = await fetch(`${API_BASE}/auth/me`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })

  if (!response.ok) {
    throw new Error(i18n.t('auth:fetchUserFailed'))
  }

  return await response.json()
}

export interface ChangePasswordPayload {
  current_password: string
  new_password: string
}

// Deliberately not routed through the generic `login`/`getCurrentUser` raw-fetch helpers above:
// this needs the stored auth token attached, which apiClient already does (see api/client.ts).
export function changePassword(payload: ChangePasswordPayload): Promise<UserResponse> {
  return apiClient.post<UserResponse>('/auth/change-password', payload)
}
