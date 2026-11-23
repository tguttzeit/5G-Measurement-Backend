import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import './index.css'
import './i18n'
import { router } from './router'
import { AuthProvider } from './components/AuthProvider'
import { ThemeProvider } from './components/ThemeProvider'
import { LanguageProvider } from './i18n/LanguageProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <ThemeProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </ThemeProvider>
    </LanguageProvider>
  </StrictMode>,
)
