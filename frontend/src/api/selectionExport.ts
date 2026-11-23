import { TOKEN_KEY } from '../components/AuthProvider'

const API_BASE = '/api'

export type SelectionExportFormat = 'csv' | 'geojson'

// Public endpoint: guests can export too, but a logged-in user's token widens what
// the backend resolves (points of runs not assigned to a campaign), so it is sent when present.
export async function downloadSelectionExport(
  ids: number[],
  format: SelectionExportFormat,
): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY)
  const response = await fetch(`${API_BASE}/measurements/export-selection`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ ids, format }),
  })
  if (!response.ok) {
    throw new Error(`Selection export failed with status ${response.status}`)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `measurements-selection.${format}`
  link.click()
  URL.revokeObjectURL(url)
}
