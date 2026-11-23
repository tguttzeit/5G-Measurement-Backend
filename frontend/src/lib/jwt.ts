interface JwtPayload {
  exp?: number
}

function decodePayload(token: string): JwtPayload | null {
  const parts = token.split('.')
  if (parts.length !== 3) {
    return null
  }
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
    return JSON.parse(atob(padded)) as JwtPayload
  } catch {
    return null
  }
}

// UX-only check so ProtectedRoute can redirect before rendering a page that's going to fail
// anyway -- never a security boundary. The server independently validates the token on every
// request regardless of what this returns (the 401 interceptor in client.ts).
export function isTokenExpired(token: string): boolean {
  const payload = decodePayload(token)
  if (!payload || typeof payload.exp !== 'number') {
    return true
  }
  return Date.now() >= payload.exp * 1000
}
