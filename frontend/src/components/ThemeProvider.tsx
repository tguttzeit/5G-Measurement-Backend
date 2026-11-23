import { createContext, useContext, useEffect, useState } from 'react'

type ThemePreference = 'system' | 'light' | 'dark'

interface ThemeContextType {
  theme: ThemePreference
  setTheme: (theme: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

export const THEME_KEY = 'theme_preference'

function applyTheme(theme: ThemePreference) {
  const root = document.documentElement
  root.classList.remove('light', 'dark')
  if (theme !== 'system') {
    root.classList.add(theme)
  }
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemePreference>(() => {
    const stored = localStorage.getItem(THEME_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  })

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  const setTheme = (next: ThemePreference) => {
    setThemeState(next)
    if (next === 'system') {
      localStorage.removeItem(THEME_KEY)
    } else {
      localStorage.setItem(THEME_KEY, next)
    }
  }

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}

// Resolves 'system' against the OS preference so consumers (e.g. the Leaflet tile layer) get a
// plain boolean instead of having to re-derive it from matchMedia themselves.
export function useIsDarkMode(): boolean {
  const { theme } = useTheme()
  const [systemPrefersDark, setSystemPrefersDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches,
  )

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const listener = (event: MediaQueryListEvent) => setSystemPrefersDark(event.matches)
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, [])

  return theme === 'dark' || (theme === 'system' && systemPrefersDark)
}
