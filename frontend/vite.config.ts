/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Extra hostnames the dev server accepts, comma-separated, set in the untracked frontend/.env
  // (VITE_ALLOWED_HOSTS=dev.example.org).
  const env = loadEnv(mode, process.cwd(), '')
  const extraHosts = (env.VITE_ALLOWED_HOSTS ?? '')
    .split(',')
    .map((host) => host.trim())
    .filter(Boolean)

  return {
    plugins: [react()],
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
    },
    server: {
      allowedHosts: ['localhost', '127.0.0.1', ...extraHosts],
      proxy: {
        // Forwards to the local FastAPI dev server (`uv run uvicorn app.main:app --reload`),
        // mirroring the Caddy same-origin reverse proxy used in production.
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
