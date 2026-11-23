import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MapHeatmapPage } from './MapHeatmapPage'
import { useAuth } from '../components/AuthProvider'
import { fetchDetailedMeasurements, fetchPublicMeasurementPoints } from '../api/measurementsDetailed'
import { fetchLatencyRaw, fetchPublicLatencyPoints } from '../api/latencyResultsDetailed'
import { downloadSelectionExport } from '../api/selectionExport'
import { fetchPublicCampaigns } from '../api/campaigns'
import { colorForMetricValue } from '../lib/metricColor'

vi.mock('../components/AuthProvider', () => ({
  useAuth: vi.fn(),
}))

vi.mock('../components/ThemeProvider', () => ({
  useIsDarkMode: vi.fn().mockReturnValue(false),
}))

const fakeBounds = {
  getSouthWest: () => ({ lng: -1, lat: -1 }),
  getNorthEast: () => ({ lng: 1, lat: 1 }),
}

// A stable fake map (react-leaflet's real useMap returns the same instance every render) whose
// container pixel (x, y) maps to lng = x / 10, lat = y / 10, so drags can be expressed in pixels.
const { fakeMap, fitBoundsMock, heatLayerMock, rectangleSpy } = vi.hoisted(() => {
  const fitBoundsMock = vi.fn()
  const container = document.createElement('div')
  document.body.appendChild(container)
  let panning = true
  return {
    fitBoundsMock,
    fakeMap: {
      invalidateSize: vi.fn(),
      getBounds: () => ({
        getSouthWest: () => ({ lng: -1, lat: -1 }),
        getNorthEast: () => ({ lng: 1, lat: 1 }),
      }),
      removeLayer: vi.fn(),
      addLayer: vi.fn(),
      fitBounds: fitBoundsMock,
      getContainer: () => container,
      mouseEventToContainerPoint: (e: MouseEvent) => ({ x: e.clientX, y: e.clientY }),
      containerPointToLatLng: ([x, y]: [number, number]) => ({ lat: y / 10, lng: x / 10 }),
      dragging: {
        enabled: () => panning,
        enable: () => {
          panning = true
        },
        disable: () => {
          panning = false
        },
      },
    },

  heatLayerMock: vi.fn((_points: unknown[], _opts: unknown) => ({ addTo: vi.fn() })),
  rectangleSpy: vi.fn(),
  }
})

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  TileLayer: () => null,
  useMap: () => fakeMap,
  useMapEvents: () => ({ getBounds: () => fakeBounds }),
  Polyline: ({
    positions,
    pathOptions,
    eventHandlers,
  }: {
    positions: [number, number][]
    pathOptions?: { color?: string; weight?: number }
    eventHandlers?: { click?: (e: { originalEvent: MouseEvent }) => void }
  }) => (
    <div
      data-testid="polyline"
      data-positions={JSON.stringify(positions)}
      data-color={pathOptions?.color}
      onClick={(e) => eventHandlers?.click?.({ originalEvent: e.nativeEvent })}
    />
  ),
  CircleMarker: ({
    center,
    pathOptions,
    eventHandlers,
  }: {
    center: [number, number]
    pathOptions?: { fillColor?: string; weight?: number }
    eventHandlers?: { click?: (e: { originalEvent: MouseEvent }) => void }
  }) => (
    <div
      data-testid="circle-marker"
      data-center={JSON.stringify(center)}
      data-fill-color={pathOptions?.fillColor}
      data-selected={pathOptions?.weight === 3}
      onClick={(e) => eventHandlers?.click?.({ originalEvent: e.nativeEvent })}
    />
  ),
}))

vi.mock('../api/measurementsDetailed', () => ({
  fetchDetailedMeasurements: vi.fn(),
  fetchPublicMeasurementPoints: vi.fn(),
}))

vi.mock('../api/selectionExport', () => ({
  downloadSelectionExport: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('../api/latencyResultsDetailed', () => ({
  fetchLatencyRaw: vi.fn(),
  fetchPublicLatencyPoints: vi.fn(),
}))

// Real latLngBounds/rectangle/layerGroup (pure geometry, no DOM needed) so InitialViewFitter's
// fitted bounds and AggregateGridLayer's rendered rectangles can be inspected directly - only
// heatLayer (which touches the actual map canvas) is stubbed. rectangle is wrapped in a spy
// (while keeping its real behavior) so tests can assert on what AggregateGridLayer draws.
vi.mock('leaflet', async () => {
  const actual = (await vi.importActual('leaflet')) as { default: Record<string, unknown> }
  rectangleSpy.mockImplementation((...args: unknown[]) =>
    (actual.default.rectangle as (...a: unknown[]) => unknown)(...args),
  )
  return {
    ...actual,
    default: { ...actual.default, heatLayer: heatLayerMock, rectangle: rectangleSpy },
  }
})

vi.mock('leaflet.heat', () => ({}))
vi.mock('leaflet/dist/leaflet.css', () => ({}))
vi.mock('html2canvas', () => ({ default: vi.fn() }))

vi.mock('../api/campaigns', async () => {
  const actual = await vi.importActual<typeof import('../api/campaigns')>('../api/campaigns')
  return {
    fetchPublicCampaigns: vi.fn().mockResolvedValue({ campaigns: [] }),
    defaultCampaign: actual.defaultCampaign,
  }
})

const mockUseAuth = vi.mocked(useAuth)

function renderMapPage(initialEntry = '/map') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <MapHeatmapPage />
    </MemoryRouter>,
  )
}

function dragOnMap(from: [number, number], to: [number, number], modifiers: MouseEventInit) {
  const container = fakeMap.getContainer()
  const init = { bubbles: true, cancelable: true, button: 0, ...modifiers }
  act(() => {
    container.dispatchEvent(new MouseEvent('mousedown', { ...init, clientX: from[0], clientY: from[1] }))
    document.dispatchEvent(new MouseEvent('mousemove', { ...init, clientX: to[0], clientY: to[1] }))
    document.dispatchEvent(new MouseEvent('mouseup', { ...init, clientX: to[0], clientY: to[1] }))
  })
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('MapHeatmapPage', () => {
  it('hides the Device ID filter for anonymous visitors', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false } as ReturnType<typeof useAuth>)

    renderMapPage()

    await waitFor(() => expect(screen.queryByLabelText(/Device ID/i)).not.toBeInTheDocument())
  })

  it('shows the Device ID filter for authenticated users', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)

    renderMapPage()

    await waitFor(() => expect(screen.getByLabelText(/Device ID/i)).toBeInTheDocument())
  })
})

describe('MapHeatmapPage initial view fit', () => {
  // An asymmetric cluster deliberately not centered in any particular grid cell - the real
  // extent returned by the backend, not a cell-center approximation of it.
  const EXTENT_BBOX: [number, number, number, number] = [10.869938, 48.349285, 10.878011, 48.359996]

  function mockFetchResponse(input: RequestInfo | URL) {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/measurements/extent')) {
      return { ok: true, json: async () => ({ bbox: EXTENT_BBOX }) } as Response
    }
    return {
      ok: true,
      json: async () => ({ type: 'FeatureCollection', features: [], cell_width: 0.01, cell_height: 0.01 }),
    } as Response
  }

  beforeEach(() => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false } as ReturnType<typeof useAuth>)
    vi.stubGlobal('fetch', vi.fn(mockFetchResponse))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fits the map to the extent endpoint bounds, not a grid cell center', async () => {
    renderMapPage()

    await waitFor(() => expect(fitBoundsMock).toHaveBeenCalled())

    const [bounds] = fitBoundsMock.mock.calls[0]
    expect(bounds.getSouthWest().lng).toBeCloseTo(EXTENT_BBOX[0])
    expect(bounds.getSouthWest().lat).toBeCloseTo(EXTENT_BBOX[1])
    expect(bounds.getNorthEast().lng).toBeCloseTo(EXTENT_BBOX[2])
    expect(bounds.getNorthEast().lat).toBeCloseTo(EXTENT_BBOX[3])
  })

  it('fetches the extent endpoint exactly once for the initial fit, with no world-spanning grid pass', async () => {
    renderMapPage()

    await waitFor(() => expect(fitBoundsMock).toHaveBeenCalled())

    const fetchMock = vi.mocked(fetch)
    const extentCalls = fetchMock.mock.calls.filter(([input]) =>
      (typeof input === 'string' ? input : input.toString()).includes('/measurements/extent'),
    )
    expect(extentCalls).toHaveLength(1)
  })
})

describe('MapHeatmapPage aggregate view rendering', () => {
  function mockFetchResponse(input: RequestInfo | URL) {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/measurements/heatmap')) {
      return {
        ok: true,
        json: async () => ({
          type: 'FeatureCollection',
          features: [
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [10, 48] },
              properties: { value: -80, count: 1 },
            },
          ],
        }),
      } as Response
    }
    if (url.includes('/measurements/extent')) {
      return { ok: true, json: async () => ({ bbox: null }) } as Response
    }
    return { ok: true, json: async () => ({ campaigns: [] }) } as Response
  }

  beforeEach(() => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false } as ReturnType<typeof useAuth>)
    vi.stubGlobal('fetch', vi.fn(mockFetchResponse))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders aggregate points through the heat layer, same as every other view mode', async () => {
    renderMapPage()

    // Bucketed by value into a flat (same color both ends) gradient, so a lone point's own blur
    // falloff can't sweep through any other hue on its way to fully transparent - -80 is the top
    // of the rsrp range, landing in the extreme "best" bucket either way.
    const color = colorForMetricValue('rsrp', -80)
    await waitFor(() =>
      expect(heatLayerMock).toHaveBeenCalledWith(
        [[48, 10, 1]],
        expect.objectContaining({ gradient: { 0: color, 1: color } }),
      ),
    )
    expect(rectangleSpy).not.toHaveBeenCalled()
  })

  it('weights a merged point by its count - repeated, square-rooted, and capped - so dedup/clustering does not visually undercount it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/measurements/heatmap')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              type: 'FeatureCollection',
              features: [
                {
                  type: 'Feature',
                  geometry: { type: 'Point', coordinates: [9, 47] },
                  // The single most common merge in dedup mode - must still weight higher than
                  // count=1, not round down to no boost at all (ceil(sqrt(2)) = 2).
                  properties: { value: -80, count: 2 },
                },
                {
                  type: 'Feature',
                  geometry: { type: 'Point', coordinates: [10, 48] },
                  properties: { value: -80, count: 9 }, // ceil(sqrt(9)) = 3, under the cap of 5
                },
                {
                  type: 'Feature',
                  geometry: { type: 'Point', coordinates: [11, 49] },
                  properties: { value: -80, count: 100 }, // ceil(sqrt(100)) = 10, clamped to the cap
                },
              ],
            }),
          } as Response)
        }
        return Promise.resolve(mockFetchResponse(input))
      }),
    )

    renderMapPage()

    const color = colorForMetricValue('rsrp', -80)
    const callForRadius = (radius: number) =>
      heatLayerMock.mock.calls.find(([, opts]) => (opts as { radius: number }).radius === radius)

    // leaflet.heat has no per-point radius, so each count tier renders as its own
    // heatLayer call with a bigger radius/blur - a heavily-fused point visibly covers more map
    // area, not just a brighter dot.
    await waitFor(() => expect(callForRadius(55)).toBeTruthy())

    // Uniform intensity=1 regardless of value - the value only drives which flat-color
    // bucket/gradient the call uses, not a per-point intensity.
    // count=2 -> weight 2 (ceil(sqrt(2))), radius tier 24 (maxCount: 4)
    expect(callForRadius(24)?.[0]).toEqual(Array(2).fill([47, 9, 1]))
    expect(callForRadius(24)?.[1]).toMatchObject({ gradient: { 0: color, 1: color } })
    // count=9 -> weight 3 (ceil(sqrt(9))), radius tier 32 (maxCount: 19)
    expect(callForRadius(32)?.[0]).toEqual(Array(3).fill([48, 10, 1]))
    expect(callForRadius(32)?.[1]).toMatchObject({ gradient: { 0: color, 1: color } })
    // count=100 -> weight capped at 5, radius tier 55 (maxCount: Infinity, 100 > 99)
    expect(callForRadius(55)?.[0]).toEqual(Array(5).fill([49, 11, 1]))
    expect(callForRadius(55)?.[1]).toMatchObject({ gradient: { 0: color, 1: color } })
  })
})

describe('MapHeatmapPage fullscreen toggle', () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false } as ReturnType<typeof useAuth>)
    // jsdom doesn't implement the Fullscreen API - stub the pieces the toggle drives.
    HTMLElement.prototype.requestFullscreen = vi.fn().mockResolvedValue(undefined)
    document.exitFullscreen = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      value: null,
    })
  })

  it('requests fullscreen on the map wrapper when the toggle is clicked', async () => {
    renderMapPage()

    const toggle = await screen.findByRole('button', { name: /^fullscreen$/i })
    fireEvent.click(toggle)

    expect(HTMLElement.prototype.requestFullscreen).toHaveBeenCalledTimes(1)
  })

  it('exits fullscreen via the toggle once the map wrapper is the fullscreen element', async () => {
    renderMapPage()

    const mapWrapper = document.querySelector('.map-wrapper') as HTMLElement
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      value: mapWrapper,
    })
    fireEvent(document, new Event('fullscreenchange'))

    const toggle = await screen.findByRole('button', { name: /^exit fullscreen$/i })
    fireEvent.click(toggle)

    expect(document.exitFullscreen).toHaveBeenCalledTimes(1)
  })

  it('relabels back to Fullscreen once the browser reports leaving fullscreen', async () => {
    renderMapPage()

    const mapWrapper = document.querySelector('.map-wrapper') as HTMLElement
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      value: mapWrapper,
    })
    fireEvent(document, new Event('fullscreenchange'))
    await screen.findByRole('button', { name: /^exit fullscreen$/i })

    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      value: null,
    })
    fireEvent(document, new Event('fullscreenchange'))

    expect(await screen.findByRole('button', { name: /^fullscreen$/i })).toBeInTheDocument()
  })
})

describe('MapHeatmapPage display style toggle', () => {
  function mockFetchResponse(input: RequestInfo | URL) {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/measurements/heatmap')) {
      return {
        ok: true,
        json: async () => ({
          type: 'FeatureCollection',
          features: [
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [10, 48] },
              properties: { value: -80, count: 1 },
            },
          ],
        }),
      } as Response
    }
    if (url.includes('/measurements/extent')) {
      return { ok: true, json: async () => ({ bbox: null }) } as Response
    }
    return { ok: true, json: async () => ({ campaigns: [] }) } as Response
  }

  beforeEach(() => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false } as ReturnType<typeof useAuth>)
    vi.stubGlobal('fetch', vi.fn(mockFetchResponse))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('defaults to the heatmap and also offers Points to anonymous visitors', async () => {
    renderMapPage()

    const select = await screen.findByLabelText(/display style/i)
    expect((select as HTMLSelectElement).value).toBe('heatmap')
    expect(screen.getByRole('option', { name: 'Heatmap' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Points' })).toBeInTheDocument()
  })

  it('is available for the public aggregate view', async () => {
    renderMapPage()

    expect(await screen.findByLabelText(/display style/i)).toBeInTheDocument()
  })
})

describe('MapHeatmapPage Points style and point detail selection', () => {
  const mockedFetchDetailedMeasurements = vi.mocked(fetchDetailedMeasurements)

  beforeEach(() => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/measurements/extent')) {
          return Promise.resolve({ ok: true, json: async () => ({ bbox: null }) } as Response)
        }
        if (url.includes('/measurements/heatmap')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ type: 'FeatureCollection', features: [] }),
          } as Response)
        }
        return Promise.resolve({ ok: true, json: async () => ({ campaigns: [] }) } as Response)
      }),
    )
    mockedFetchDetailedMeasurements.mockResolvedValue({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [10, 48] },
          properties: { id: 101, device_id: 'dev-1', timestamp: '2026-01-01T12:00:00Z', rsrp: -80, rsrq: -9, sinr: 11 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [11, 49] },
          properties: { id: 102, device_id: 'dev-2', timestamp: '2026-01-01T13:00:00Z', rsrp: -70, rsrq: -8, sinr: 14 },
        },
      ],
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('offers Points for authenticated users and renders raw-view markers, not the heat layer', async () => {
    renderMapPage()

    expect(screen.getByRole('option', { name: 'Points' })).toBeInTheDocument()

    const select = await screen.findByLabelText(/display style/i)
    fireEvent.change(select, { target: { value: 'points' } })

    const markers = await screen.findAllByTestId('circle-marker')
    expect(markers).toHaveLength(2)
    expect(markers[0].dataset.fillColor).toBe(colorForMetricValue('rsrp', -80))
    expect(heatLayerMock).not.toHaveBeenCalled()
  })

  it('shows all three metrics for a clicked point in a details table, not just the active metric', async () => {
    renderMapPage()

    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    const markers = await screen.findAllByTestId('circle-marker')
    fireEvent.click(markers[0])

    expect(await screen.findByText('dev-1')).toBeInTheDocument()
    const row = screen.getByText('dev-1').closest('tr') as HTMLElement
    expect(row).toHaveTextContent('-80')
    expect(row).toHaveTextContent('-9')
    expect(row).toHaveTextContent('11')
  })

  it('plain click replaces the selection; shift-click adds a second row for comparison', async () => {
    renderMapPage()

    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    const markers = await screen.findAllByTestId('circle-marker')

    fireEvent.click(markers[0])
    await screen.findByText('dev-1')
    expect(screen.queryByText('dev-2')).not.toBeInTheDocument()

    fireEvent.click(markers[1], { shiftKey: true })
    expect(await screen.findByText('dev-2')).toBeInTheDocument()
    expect(screen.getByText('dev-1')).toBeInTheDocument()

    // A plain click (no shift) afterwards collapses back down to just that one point.
    fireEvent.click(markers[1])
    expect(screen.queryByText('dev-1')).not.toBeInTheDocument()
    expect(screen.getByText('dev-2')).toBeInTheDocument()
  })

  // dev-1 sits at (lng 10, lat 48), dev-2 at (lng 11, lat 49); one pixel is 0.1 degree.
  it('shift+drag selects the points inside the rectangle and adds to the existing selection', async () => {
    renderMapPage()
    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    const markers = await screen.findAllByTestId('circle-marker')

    fireEvent.click(markers[1])
    await screen.findByText('dev-2')

    dragOnMap([90, 470], [105, 485], { shiftKey: true })

    expect(await screen.findByText('dev-1')).toBeInTheDocument()
    expect(screen.getByText('dev-2')).toBeInTheDocument()
    expect(screen.getByText('Selected points (2) - RSRP')).toBeInTheDocument()
  })

  describe('selection export', () => {
    async function openPoints() {
      renderMapPage()
      fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
      return screen.findAllByTestId('circle-marker')
    }

    it('offers selection export only once points are selected', async () => {
      const markers = await openPoints()

      expect(screen.queryByRole('button', { name: /Export selection/ })).not.toBeInTheDocument()

      fireEvent.click(markers[0])

      expect(await screen.findByRole('button', { name: 'Export selection CSV' })).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Export selection GeoJSON' })).toBeEnabled()
      expect(screen.queryByRole('button', { name: /Export selection PNG/ })).not.toBeInTheDocument()
    })

    it('requests the export of exactly the selected measurement ids in the chosen format', async () => {
      const markers = await openPoints()
      fireEvent.click(markers[1])
      fireEvent.click(markers[0], { shiftKey: true })

      fireEvent.click(await screen.findByRole('button', { name: 'Export selection GeoJSON' }))

      await waitFor(() =>
        expect(vi.mocked(downloadSelectionExport)).toHaveBeenCalledWith([102, 101], 'geojson'),
      )
    })

    it('shows an error when the export fails', async () => {
      vi.mocked(downloadSelectionExport).mockRejectedValueOnce(new Error('boom'))
      const markers = await openPoints()
      fireEvent.click(markers[0])

      fireEvent.click(await screen.findByRole('button', { name: 'Export selection CSV' }))

      expect(await screen.findByText('Failed to export the selection as CSV.')).toBeInTheDocument()
    })
  })

  it('shift+drag does not select anything when the rectangle contains no loaded point', async () => {
    renderMapPage()
    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    await screen.findAllByTestId('circle-marker')

    dragOnMap([0, 0], [20, 20], { shiftKey: true })

    expect(screen.queryByText(/Selected points/)).not.toBeInTheDocument()
  })

  it('shows count, min, max, mean, median and std dev of the active metric for the selection', async () => {
    renderMapPage()
    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    await screen.findAllByTestId('circle-marker')

    dragOnMap([0, 0], [200, 600], { shiftKey: true })

    const stats = await screen.findByLabelText('Selection statistics')
    // rsrp values are -80 and -70.
    expect(stats).toHaveTextContent('Count2')
    expect(stats).toHaveTextContent('Min-80.00')
    expect(stats).toHaveTextContent('Max-70.00')
    expect(stats).toHaveTextContent('Mean-75.00')
    expect(stats).toHaveTextContent('Median-75.00')
    expect(stats).toHaveTextContent('Std dev5.00')
  })

  it('recomputes the statistics for the newly active metric', async () => {
    renderMapPage()
    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    await screen.findAllByTestId('circle-marker')
    dragOnMap([0, 0], [200, 600], { shiftKey: true })
    await screen.findByLabelText('Selection statistics')

    fireEvent.change(screen.getByLabelText('Metric'), { target: { value: 'sinr' } })

    await waitFor(() =>
      expect(screen.getByLabelText('Selection statistics')).toHaveTextContent('Mean12.50'),
    )
  })

  it('ctrl+drag zooms the map to the rectangle without changing the selection', async () => {
    renderMapPage()
    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    await screen.findAllByTestId('circle-marker')
    fitBoundsMock.mockClear()

    dragOnMap([90, 470], [105, 485], { ctrlKey: true })

    expect(fitBoundsMock).toHaveBeenCalledWith([
      [47, 9],
      [48.5, 10.5],
    ])
    expect(screen.queryByText(/Selected points/)).not.toBeInTheDocument()
  })

  it('shift+drag does nothing in heatmap style, while ctrl+drag still zooms', async () => {
    renderMapPage()
    await screen.findByLabelText(/display style/i)
    fitBoundsMock.mockClear()

    dragOnMap([0, 0], [200, 600], { shiftKey: true })
    expect(fitBoundsMock).not.toHaveBeenCalled()

    dragOnMap([0, 0], [200, 600], { ctrlKey: true })
    expect(fitBoundsMock).toHaveBeenCalledTimes(1)
  })

  it('describes the drag gestures in a hint under the map', async () => {
    renderMapPage()
    expect(await screen.findByText(/Drag with Ctrl held to zoom/)).toBeInTheDocument()
    expect(screen.queryByText(/Drag with Shift held/)).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/display style/i), { target: { value: 'points' } })
    expect(await screen.findByText(/Drag with Shift held to select/)).toBeInTheDocument()
  })
})

describe('MapHeatmapPage guest Points style', () => {
  const mockedPublicMeasurementPoints = vi.mocked(fetchPublicMeasurementPoints)
  const mockedPublicLatencyPoints = vi.mocked(fetchPublicLatencyPoints)
  const mockedFetchDetailedMeasurements = vi.mocked(fetchDetailedMeasurements)
  const mockedFetchLatencyRaw = vi.mocked(fetchLatencyRaw)

  beforeEach(() => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false } as ReturnType<typeof useAuth>)
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/extent')) {
          return Promise.resolve({ ok: true, json: async () => ({ bbox: null }) } as Response)
        }
        if (url.includes('/heatmap')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ type: 'FeatureCollection', features: [] }),
          } as Response)
        }
        return Promise.resolve({ ok: true, json: async () => ({ campaigns: [] }) } as Response)
      }),
    )
    mockedPublicMeasurementPoints.mockResolvedValue({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [10, 48] },
          properties: { id: 201, rsrp: -80, rsrq: -9, sinr: 11 },
        },
      ],
    })
    mockedPublicLatencyPoints.mockResolvedValue({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: [[10, 48], [10.1, 48.1]] },
          properties: {
            baseline_rtt_ms: 25,
            rtt_under_load_ms: 120,
            rtt_p99_ms: 300,
            download_mbits_s: 80,
            upload_mbits_s: 20,
          },
        },
      ],
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('renders markers from the public endpoint and never calls the authenticated one', async () => {
    renderMapPage()

    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })

    expect(await screen.findAllByTestId('circle-marker')).toHaveLength(1)
    expect(mockedPublicMeasurementPoints).toHaveBeenCalled()
    expect(mockedFetchDetailedMeasurements).not.toHaveBeenCalled()
    expect(mockedPublicMeasurementPoints.mock.calls[0][0]).not.toHaveProperty('deviceId')
  })

  it('shows the selected-points table without Device and Time columns', async () => {
    renderMapPage()

    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    fireEvent.click(await screen.findByTestId('circle-marker'))

    const row = (await screen.findByText('-80')).closest('tr') as HTMLElement
    expect(row).toHaveTextContent('-9')
    expect(row).toHaveTextContent('11')
    expect(screen.queryByRole('columnheader', { name: 'Device' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Time' })).not.toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'RSRP' })).toBeInTheDocument()
  })

  it('uses the public latency endpoint for latency metrics and omits identifying columns', async () => {
    renderMapPage()

    fireEvent.change(await screen.findByLabelText('Metric'), {
      target: { value: 'baseline_rtt_ms' },
    })
    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    fireEvent.click(await screen.findByTestId('polyline'))

    expect(mockedPublicLatencyPoints).toHaveBeenCalled()
    expect(mockedFetchLatencyRaw).not.toHaveBeenCalled()
    expect(await screen.findByText('300')).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Device' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Started' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Test' })).not.toBeInTheDocument()
  })

  it('keeps the Device ID filter hidden for guests', async () => {
    renderMapPage()

    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })

    expect(screen.queryByLabelText(/device id/i)).not.toBeInTheDocument()
  })
})

describe('MapHeatmapPage latency metrics', () => {
  const mockedFetchLatencyRaw = vi.mocked(fetchLatencyRaw)
  let fetchMock: ReturnType<typeof vi.fn>

  const urls = () =>
    fetchMock.mock.calls.map(([input]) => (typeof input === 'string' ? input : input.toString()))

  beforeEach(() => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)
    fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/extent')) {
        return Promise.resolve({ ok: true, json: async () => ({ bbox: null }) } as Response)
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ type: 'FeatureCollection', features: [] }),
      } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    mockedFetchLatencyRaw.mockResolvedValue({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: [[10, 48], [10.1, 48.1]] },
          properties: {
            device_id: 'dev-1',
            test_type: 'under_load',
            start_timestamp: '2026-01-01T12:00:00Z',
            end_timestamp: '2026-01-01T12:01:00Z',
            baseline_rtt_ms: 25,
            rtt_under_load_ms: 120,
            rtt_p99_ms: 300,
            download_mbits_s: 80,
            upload_mbits_s: 20,
          },
        },
      ],
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('offers all five latency/throughput metrics in the Metric dropdown', async () => {
    renderMapPage()

    for (const name of [
      'Baseline RTT (ms)',
      'RTT under load (ms)',
      'RTT p99 (ms)',
      'Download (Mbit/s)',
      'Upload (Mbit/s)',
    ]) {
      expect(await screen.findByRole('option', { name })).toBeInTheDocument()
    }
  })

  it('fetches the latency heatmap and extent endpoints, not the measurement ones, for a latency metric', async () => {
    renderMapPage()
    fireEvent.change(await screen.findByLabelText('Metric'), {
      target: { value: 'baseline_rtt_ms' },
    })

    await waitFor(() =>
      expect(urls().some((u) => u.includes('/api/latency-results/heatmap?metric=baseline_rtt_ms'))).toBe(true),
    )
    expect(urls().filter((u) => u.includes('/measurements/heatmap')).every((u) => u.includes('metric=rsrp'))).toBe(true)
  })

  it('uses the measurement endpoints for RSRP', async () => {
    renderMapPage()

    await waitFor(() => expect(urls().some((u) => u.includes('/api/measurements/heatmap'))).toBe(true))
    expect(urls().some((u) => u.includes('/latency-results/'))).toBe(false)
  })

  it('renders latency results as start-to-end lines colored by the selected metric in Points style', async () => {
    renderMapPage()
    fireEvent.change(await screen.findByLabelText('Metric'), {
      target: { value: 'baseline_rtt_ms' },
    })
    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })

    const line = await screen.findByTestId('polyline')
    expect(JSON.parse(line.dataset.positions!)).toEqual([[48, 10], [48.1, 10.1]])
    expect(line.dataset.color).toBe(colorForMetricValue('baseline_rtt_ms', 25))
    expect(screen.queryByTestId('circle-marker')).not.toBeInTheDocument()
    expect(mockedFetchLatencyRaw).toHaveBeenCalledWith(
      expect.objectContaining({ metric: 'baseline_rtt_ms' }),
    )
  })

  it('shows all five metric values for a clicked line, not just the active one', async () => {
    renderMapPage()
    fireEvent.change(await screen.findByLabelText('Metric'), {
      target: { value: 'download_mbits_s' },
    })
    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    fireEvent.click(await screen.findByTestId('polyline'))

    const row = (await screen.findByText('dev-1')).closest('tr') as HTMLElement
    for (const value of ['25', '120', '300', '80', '20']) {
      expect(row).toHaveTextContent(value)
    }
  })

  it('shift+drag selects a latency line when its start or end fix is inside the rectangle', async () => {
    renderMapPage()
    fireEvent.change(await screen.findByLabelText('Metric'), { target: { value: 'baseline_rtt_ms' } })
    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })
    await screen.findByTestId('polyline')

    // Covers only the end fix (lng 10.1, lat 48.1), not the start fix (lng 10, lat 48).
    dragOnMap([101, 481], [110, 490], { shiftKey: true })

    expect(await screen.findByText('dev-1')).toBeInTheDocument()
    expect(screen.getByLabelText('Selection statistics')).toHaveTextContent('Mean25.00')
  })

  it('disables export for latency metrics', async () => {
    renderMapPage()
    expect(await screen.findByRole('button', { name: 'Export CSV' })).toBeEnabled()

    fireEvent.change(screen.getByLabelText('Metric'), { target: { value: 'rtt_p99_ms' } })

    await waitFor(() => expect(screen.getByRole('button', { name: 'Export CSV' })).toBeDisabled())
  })
})

describe('MapHeatmapPage run filter', () => {
  const mockedFetchDetailedMeasurements = vi.mocked(fetchDetailedMeasurements)
  const mockedFetchLatencyRaw = vi.mocked(fetchLatencyRaw)
  const RUN_URL = '/map?run=run-abc&device=device-1&campaign=3'
  let fetchMock: ReturnType<typeof vi.fn>

  const urls = () =>
    fetchMock.mock.calls.map(([input]) => (typeof input === 'string' ? input : input.toString()))

  beforeEach(() => {
    fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/extent')) {
        return Promise.resolve({ ok: true, json: async () => ({ bbox: null }) } as Response)
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ type: 'FeatureCollection', features: [] }),
      } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    mockedFetchDetailedMeasurements.mockResolvedValue({ type: 'FeatureCollection', features: [] })
    mockedFetchLatencyRaw.mockResolvedValue({ type: 'FeatureCollection', features: [] })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads only the run, for its device and across all time, in the Points style', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)

    renderMapPage(RUN_URL)

    await waitFor(() => expect(mockedFetchDetailedMeasurements).toHaveBeenCalled())
    expect(mockedFetchDetailedMeasurements).toHaveBeenLastCalledWith(
      expect.objectContaining({
        view: 'raw',
        runId: 'run-abc',
        deviceId: 'device-1',
        campaignId: null,
      }),
    )
    expect(screen.getByText('run-abc', { exact: false })).toBeInTheDocument()
    expect((screen.getByLabelText(/display style/i) as HTMLSelectElement).value).toBe('points')
    expect(screen.getByLabelText(/display style/i)).toBeDisabled()
    expect(urls().some((u) => u.includes('/measurements/heatmap'))).toBe(false)
  })

  it('applies the run to latency metrics too', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)
    renderMapPage(RUN_URL)

    fireEvent.change(await screen.findByLabelText('Metric'), {
      target: { value: 'baseline_rtt_ms' },
    })

    await waitFor(() =>
      expect(mockedFetchLatencyRaw).toHaveBeenCalledWith(
        expect.objectContaining({ runId: 'run-abc', deviceId: 'device-1' }),
      ),
    )
  })

  it('fits the initial view to the extent of the run\'s campaign', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)

    renderMapPage(RUN_URL)

    await waitFor(() =>
      expect(urls().some((u) => u.includes('/measurements/extent') && u.includes('campaign_id=3'))).toBe(true),
    )
  })

  it('ignores the run parameter for anonymous visitors', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false } as ReturnType<typeof useAuth>)

    renderMapPage(RUN_URL)

    await waitFor(() => expect(urls().some((u) => u.includes('/measurements/heatmap'))).toBe(true))
    expect(urls().some((u) => u.includes('run'))).toBe(false)
    expect(mockedFetchDetailedMeasurements).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /clear run/i })).not.toBeInTheDocument()
  })

  it('goes back to the normal view when the run filter is cleared', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)
    renderMapPage(RUN_URL)

    fireEvent.click(await screen.findByRole('button', { name: /clear run/i }))

    await waitFor(() => expect(screen.getByLabelText(/display style/i)).not.toBeDisabled())
    expect(screen.queryByRole('button', { name: /clear run/i })).not.toBeInTheDocument()
    await waitFor(() => expect(urls().some((u) => u.includes('/measurements/heatmap'))).toBe(true))
  })
})

describe('MapHeatmapPage mission type filter', () => {
  const mockedFetchDetailedMeasurements = vi.mocked(fetchDetailedMeasurements)
  let fetchMock: ReturnType<typeof vi.fn>

  const urls = () =>
    fetchMock.mock.calls.map(([input]) => (typeof input === 'string' ? input : input.toString()))

  beforeEach(() => {
    fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/extent')) {
        return Promise.resolve({ ok: true, json: async () => ({ bbox: null }) } as Response)
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ type: 'FeatureCollection', features: [] }),
      } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    mockedFetchDetailedMeasurements.mockResolvedValue({ type: 'FeatureCollection', features: [] })
    mockUseAuth.mockReturnValue({ isAuthenticated: false } as ReturnType<typeof useAuth>)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('offers only ground and drone, without an "All" option', async () => {
    renderMapPage()

    const select = await screen.findByLabelText('Mission Type')

    expect(within(select).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)).toEqual([
      'ground',
      'drone',
    ])
    expect(within(select).queryByRole('option', { name: 'All' })).not.toBeInTheDocument()
  })

  it('starts on ground and always sends the mission type to the public endpoints', async () => {
    renderMapPage()

    expect((await screen.findByLabelText('Mission Type') as HTMLSelectElement).value).toBe('ground')
    await waitFor(() => expect(urls().some((u) => u.includes('/measurements/heatmap'))).toBe(true))
    expect(urls().filter((u) => u.includes('/measurements/')).every((u) => u.includes('mission_type=ground'))).toBe(true)
  })

  it('sends the selected mission type when it is changed to drone', async () => {
    renderMapPage()

    fireEvent.change(await screen.findByLabelText('Mission Type'), { target: { value: 'drone' } })

    await waitFor(() =>
      expect(urls().some((u) => u.includes('/measurements/heatmap') && u.includes('mission_type=drone'))).toBe(true),
    )
  })

  it('sends the mission type to the authenticated endpoints too', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)
    renderMapPage()

    fireEvent.change(await screen.findByLabelText(/display style/i), { target: { value: 'points' } })

    await waitFor(() =>
      expect(mockedFetchDetailedMeasurements).toHaveBeenCalledWith(
        expect.objectContaining({ missionType: 'ground' }),
      ),
    )
  })

  it('starts on the mission type of the run it was opened for, so a drone run is not hidden', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)

    renderMapPage('/map?run=run-abc&device=device-1&mission=drone')

    expect((await screen.findByLabelText('Mission Type') as HTMLSelectElement).value).toBe('drone')
    await waitFor(() => expect(mockedFetchDetailedMeasurements).toHaveBeenCalled())
    expect(mockedFetchDetailedMeasurements).toHaveBeenLastCalledWith(
      expect.objectContaining({ runId: 'run-abc', missionType: 'drone' }),
    )
  })

  it.each(['', 'unknown', 'ALL'])('falls back to ground for a run link with mission "%s"', async (mission) => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)

    renderMapPage(`/map?run=run-abc&device=device-1&mission=${mission}`)

    expect((await screen.findByLabelText('Mission Type') as HTMLSelectElement).value).toBe('ground')
  })

  it('ignores the mission parameter when no run is shown', async () => {
    renderMapPage('/map?mission=drone')

    expect((await screen.findByLabelText('Mission Type') as HTMLSelectElement).value).toBe('ground')
  })
})

describe('MapHeatmapPage heatmap scope (all time)', () => {
  const mockedFetchDetailedMeasurements = vi.mocked(fetchDetailedMeasurements)
  const CAMPAIGNS = [
    { id: 1, name: 'Spring', start: '2026-01-01', end: '2026-01-31' },
    { id: 2, name: 'Summer', start: '2026-02-01', end: '2026-02-28' },
  ]
  let fetchMock: ReturnType<typeof vi.fn>

  const heatmapUrls = () =>
    fetchMock.mock.calls
      .map(([input]) => (typeof input === 'string' ? input : input.toString()))
      .filter((url) => url.includes('/measurements/heatmap'))

  const campaignSelect = () => screen.getByLabelText(/campaign/i) as HTMLSelectElement
  const hasAllTime = () => screen.queryByRole('option', { name: 'All time' }) !== null

  beforeEach(() => {
    mockUseAuth.mockReturnValue({ isAuthenticated: true } as ReturnType<typeof useAuth>)
    fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/measurements/campaigns')) {
        return Promise.resolve({ ok: true, json: async () => ({ campaigns: CAMPAIGNS }) } as Response)
      }
      if (url.includes('/extent')) {
        return Promise.resolve({ ok: true, json: async () => ({ bbox: null }) } as Response)
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ type: 'FeatureCollection', features: [] }),
      } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.mocked(fetchPublicCampaigns).mockResolvedValue({ campaigns: CAMPAIGNS })
    mockedFetchDetailedMeasurements.mockResolvedValue({ type: 'FeatureCollection', features: [] })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.mocked(fetchPublicCampaigns).mockResolvedValue({ campaigns: [] })
  })

  it('does not offer "All time" in the heatmap style', async () => {
    renderMapPage()

    await waitFor(() => expect(campaignSelect().value).toBe('2'))
    expect(hasAllTime()).toBe(false)
  })

  it('offers "All time" in the Points style', async () => {
    renderMapPage()
    await waitFor(() => expect(campaignSelect().value).toBe('2'))

    fireEvent.change(screen.getByLabelText(/display style/i), { target: { value: 'points' } })

    expect(hasAllTime()).toBe(true)
  })

  it('selects the campaign with the most recent run when switching to the heatmap from "All time"', async () => {
    renderMapPage()
    await waitFor(() => expect(campaignSelect().value).toBe('2'))
    fireEvent.change(screen.getByLabelText(/display style/i), { target: { value: 'points' } })
    fireEvent.change(campaignSelect(), { target: { value: '' } })
    expect(campaignSelect().value).toBe('')

    fireEvent.change(screen.getByLabelText(/display style/i), { target: { value: 'heatmap' } })

    expect(campaignSelect().value).toBe('2')
    expect(hasAllTime()).toBe(false)
    await waitFor(() => expect(heatmapUrls().at(-1)).toContain('campaign_id=2'))
  })

  it('keeps an explicitly chosen campaign when switching to the heatmap', async () => {
    renderMapPage()
    await waitFor(() => expect(campaignSelect().value).toBe('2'))
    fireEvent.change(screen.getByLabelText(/display style/i), { target: { value: 'points' } })
    fireEvent.change(campaignSelect(), { target: { value: '1' } })

    fireEvent.change(screen.getByLabelText(/display style/i), { target: { value: 'heatmap' } })

    expect(campaignSelect().value).toBe('1')
  })
})
