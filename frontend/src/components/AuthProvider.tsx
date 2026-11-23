import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { login as apiLogin } from '../api/auth'
import { isTokenExpired } from '../lib/jwt'

interface User {
  id: number
  email: string  // This is treated as username in the UI
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
}

interface AuthContextType {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const TOKEN_KEY = 'auth_token'
export const USER_KEY = 'auth_user'

// Shared by AuthProvider.logout() and the apiClient 401 interceptor (client.ts), which runs
// outside the React tree and can't call logout() directly.
export function clearAuthStorage() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Initialize from localStorage
  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_KEY)
    const storedUser = localStorage.getItem(USER_KEY)
    if (storedToken && storedUser && !isTokenExpired(storedToken)) {
      setToken(storedToken)
      setUser(JSON.parse(storedUser))
    } else if (storedToken || storedUser) {
      clearAuthStorage()
    }
    setIsLoading(false)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const { token: access_token, user: userData } = await apiLogin(email, password)
    setToken(access_token)
    setUser(userData)
    localStorage.setItem(TOKEN_KEY, access_token)
    localStorage.setItem(USER_KEY, JSON.stringify(userData))
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    clearAuthStorage()
  }, [])

  const value = {
    user,
    token,
    isAuthenticated: !!token,
    isLoading,
    login,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
