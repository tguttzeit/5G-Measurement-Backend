import { apiClient } from './client'

export interface AdminUser {
  id: number
  email: string // username
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
}

export interface UserListResponse {
  users: AdminUser[]
  total: number
  page: number
  page_size: number
}

export interface CreateUserPayload {
  email: string
  password: string
  is_superuser?: boolean
}

export interface UpdateUserPayload {
  is_active?: boolean
  is_superuser?: boolean
}

export function listUsers(page: number, pageSize: number): Promise<UserListResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return apiClient.get<UserListResponse>(`/admin/users?${params.toString()}`)
}

export function createUser(payload: CreateUserPayload): Promise<AdminUser> {
  return apiClient.post<AdminUser>('/admin/users', payload)
}

// fastapi-users mounts its by-id routes under the /auth prefix in this app (see
// app/routers/auth.py + app/main.py), alongside /auth/login and /auth/me.
export function updateUser(id: number, payload: UpdateUserPayload): Promise<AdminUser> {
  return apiClient.patch<AdminUser>(`/auth/${id}`, payload)
}

export function deleteUser(id: number): Promise<void> {
  return apiClient.delete<void>(`/auth/${id}`)
}
