import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../components/AuthProvider'
import { downloadSelectionExport } from './selectionExport'

describe('downloadSelectionExport', () => {
  const clickMock = vi.fn()

  beforeEach(() => {
    localStorage.clear()
    URL.createObjectURL = vi.fn(() => 'blob:selection')
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(clickMock)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['csv']) } as Response),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    clickMock.mockClear()
  })

  it('posts the ids and format and triggers a file download', async () => {
    await downloadSelectionExport([3, 5], 'geojson')

    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/measurements/export-selection')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ ids: [3, 5], format: 'geojson' })
    expect(clickMock).toHaveBeenCalledOnce()
  })

  it('sends the login token only when there is one', async () => {
    await downloadSelectionExport([1], 'csv')
    expect(vi.mocked(fetch).mock.calls[0][1]?.headers).not.toHaveProperty('Authorization')

    localStorage.setItem(TOKEN_KEY, 'jwt')
    await downloadSelectionExport([1], 'csv')
    expect(vi.mocked(fetch).mock.calls[1][1]?.headers).toMatchObject({
      Authorization: 'Bearer jwt',
    })
  })

  it('throws on a failed response', async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 422 } as Response)

    await expect(downloadSelectionExport([1], 'csv')).rejects.toThrow('422')
    expect(clickMock).not.toHaveBeenCalled()
  })
})
