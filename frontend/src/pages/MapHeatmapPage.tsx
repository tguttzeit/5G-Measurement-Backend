import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { CircleMarker, MapContainer, Polyline, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import type { LeafletMouseEvent } from 'leaflet'
import L, { type LatLngBounds } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.heat'
import html2canvas from 'html2canvas'
import { useSearchParams } from 'react-router-dom'
import {
  type Campaign,
  defaultCampaign,
  fetchPublicCampaigns,
} from '../api/campaigns'
import {
  fetchDetailedMeasurements,
  fetchPublicMeasurementPoints,
  type PublicRawFeature,
  type RawFeature,
} from '../api/measurementsDetailed'
import {
  fetchLatencyRaw,
  fetchPublicLatencyPoints,
  type LatencyRawFeature,
  type PublicLatencyFeature,
} from '../api/latencyResultsDetailed'
import { ApiError } from '../api/client'
import { type SelectionExportFormat, downloadSelectionExport } from '../api/selectionExport'
import { useAuth } from '../components/AuthProvider'
import { useIsDarkMode } from '../components/ThemeProvider'
import { Banner, Button, Card, Select, Table, TextInput } from '../components/ui'
import {
  colorForIntensity,
  colorForMetricValue,
  isLatencyMetric,
  LATENCY_METRICS,
  metricLabel,
  METRICS,
  type LatencyMetric,
  type MeasurementMetric,
  type Metric,
  normalizeMetricValue,
} from '../lib/metricColor'
import { attachModifierBoxDrag } from '../lib/modifierBoxDrag'
import { type GeoBounds, indicesInBounds } from '../lib/selectionGeometry'
import { computeSelectionStats } from '../lib/selectionStats'
import { Timestamp } from '../components/Timestamp'
import '../styles/shared.css'
import './MapHeatmapPage.css'

function heatmapErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
  }
  return i18n.t('map:loadFailed')
}

// Public endpoint - no Authorization header needed, unlike apiClient's requests.
const API_BASE = '/api'

const MIN_MAP_HEIGHT = 400
// Matches .app-shell__content's own bottom padding, so the map's bottom edge lines up with it.
const PAGE_BOTTOM_PADDING = 24

const MISSION_TYPES = ['ground', 'drone'] as const
type MissionType = (typeof MISSION_TYPES)[number]
const DEFAULT_MISSION_TYPE: MissionType = 'ground'

function parseMissionType(value: string | null): MissionType {
  return MISSION_TYPES.find((type) => type === value) ?? DEFAULT_MISSION_TYPE
}

// Latency/throughput metrics come from their own endpoints; the response shapes of
// the public heatmap/extent routes are identical, so only the path prefix differs.
function metricApiPath(metric: Metric): string {
  return `${API_BASE}/${isLatencyMetric(metric) ? 'latency-results' : 'measurements'}`
}

interface HeatmapFeature {
  type: 'Feature'
  geometry: { type: 'Point'; coordinates: [number, number] }
  properties: { value: number; count: number }
}

interface HeatmapFeatureCollection {
  type: 'FeatureCollection'
  features: HeatmapFeature[]
}

type DisplayStyle = 'heatmap' | 'points'

// leaflet.heat has no per-point radius - every point in a layer shares the same canvas stamp
// size, only its intensity (alpha weight) varies. A point representing several merged
// measurements (aggregate view's dedup/grid cells, properties.count > 1) would otherwise look
// exactly as "hot" as a single raw reading, undercounting it relative to how those measurements
// would have rendered individually. Feeding the same point in multiple times lets
// leaflet.heat's own additive blending do the weighting - the same effect several nearby raw
// points would have had - without touching its API. Square-rooted and capped so a heavily
// grid-aggregated cell (count in the hundreds/thousands) doesn't replicate an enormous number of
// times; this only needs to counteract dedup's small merge counts, not represent count exactly.
function weightForCount(count: number | undefined): number {
  // ceil, not round - round(sqrt(2)) is 1 (rounds down to no boost at all), but count=2 is the
  // single most common merge in dedup mode and must still end up weighted higher than count=1.
  return Math.min(5, Math.max(1, Math.ceil(Math.sqrt(count ?? 1))))
}

// leaflet.heat also has no per-point *radius* - every point in one heatLayer() call shares the
// same canvas stamp size. A grid cell fusing hundreds or thousands of rows (the above-threshold
// aggregation fallback) otherwise renders as a dot exactly the same size as a single raw reading,
// giving no visual sense that it represents vastly more data (weightForCount's
// capped intensity boost alone doesn't convey that gap either, it's deliberately flattened past
// a handful of merges). Bucketing points by count into a few discrete radius/blur tiers, and
// rendering one heatLayer per tier, is a workaround for not having true per-point sizing: a
// heavily-fused point visibly covers more map area, not just a brighter dot. Not scientifically
// derived - tune the breakpoints/sizes against how real data actually looks.
const COUNT_RADIUS_TIERS: ReadonlyArray<{ maxCount: number; radius: number; blur: number }> = [
  { maxCount: 1, radius: 18, blur: 14 },
  { maxCount: 4, radius: 24, blur: 18 },
  { maxCount: 19, radius: 32, blur: 24 },
  { maxCount: 99, radius: 42, blur: 32 },
  { maxCount: Infinity, radius: 55, blur: 42 },
]

// leaflet.heat colors a pixel from its own accumulated alpha, not the data value - so a single
// point's own blur falloff would sweep through every other color on the gradient on its way to
// transparent (a "good" point's edge fading through yellow into red), no matter how small its
// radius. The only way to keep one point's blob a single, constant hue is to not give it a
// gradient to sweep through at all: bucket points into a fixed number of color bins and render
// each bin as its own heat layer with a flat (same color at both ends) gradient - alpha still
// fades normally within a bin's layer (that's the soft edge), but there is no second color for it
// to fade towards. Different bins still blend into each other where their blobs overlap, via
// ordinary canvas alpha compositing.
const COLOR_BUCKET_COUNT = 10

function colorBucketFor(intensity: number): number {
  return Math.round(intensity * (COLOR_BUCKET_COUNT - 1))
}

function colorForBucket(bucket: number): string {
  return colorForIntensity(bucket / (COLOR_BUCKET_COUNT - 1))
}

function radiusTierFor(count: number | undefined) {
  const c = count ?? 1
  return COUNT_RADIUS_TIERS.find((tier) => c <= tier.maxCount) ?? COUNT_RADIUS_TIERS[COUNT_RADIUS_TIERS.length - 1]
}

interface Filters {
  metric: Metric
  missionType: MissionType
  deviceId: string
  campaignId: number | null
}

function boundsToBbox(bounds: LatLngBounds): string {
  const sw = bounds.getSouthWest()
  const ne = bounds.getNorthEast()
  return `${sw.lng},${sw.lat},${ne.lng},${ne.lat}`
}

function buildQuery(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value)
  }
  return search.toString()
}

function filterParams(filters: Filters): Record<string, string | undefined> {
  return {
    metric: filters.metric,
    mission_type: filters.missionType,
    device_id: filters.deviceId || undefined,
    // No free-form date range here by design - aggregation is always scoped to exactly
    // one campaign, so two campaigns' data can never be blended into one averaged point.
    campaign_id: filters.campaignId != null ? String(filters.campaignId) : undefined,
  }
}

function HeatLayer({
  features,
  metric,
  opacity,
}: {
  features: HeatmapFeature[]
  metric: Metric
  opacity: number
}) {
  const map = useMap()

  useEffect(() => {
    const heat = L as unknown as { heatLayer: (pts: unknown, opts: unknown) => L.Layer }
    const layerGroup = L.layerGroup()

    // Bucketed by (tier radius, color bin) - each bin gets its own flat-gradient heat layer (see
    // colorBucketFor/colorForBucket above), so a single point's blur falloff has no second color
    // to sweep through on its way to fully transparent.
    const pointsByTierAndBucket = new Map<string, { radius: number; blur: number; bucket: number; points: [number, number, number][] }>()

    for (const feature of features) {
      const [lon, lat] = feature.geometry.coordinates
      const tier = radiusTierFor(feature.properties.count)
      const weight = weightForCount(feature.properties.count)
      const bucket = colorBucketFor(normalizeMetricValue(metric, feature.properties.value))

      const key = `${tier.radius}:${bucket}`
      const entry = pointsByTierAndBucket.get(key) ?? { radius: tier.radius, blur: tier.blur, bucket, points: [] }
      for (let i = 0; i < weight; i++) {
        entry.points.push([lat, lon, 1])
      }
      pointsByTierAndBucket.set(key, entry)
    }

    for (const { radius, blur, bucket, points } of pointsByTierAndBucket.values()) {
      const color = colorForBucket(bucket)
      heat
        .heatLayer(points, { radius, blur, maxZoom: 17, gradient: { 0: color, 1: color } })
        .addTo(layerGroup)
    }
    layerGroup.addTo(map)

    return () => {
      map.removeLayer(layerGroup)
    }
  }, [map, features, metric])

  // leaflet.heat hardcodes its canvases into the map's overlayPane (ignores any `pane` option),
  // so there's no layer-level opacity to set - fade the canvases directly instead. Runs after the
  // layer-build effect above on every render, so it always sees the canvases that effect just
  // created, not stale ones from before a feature/metric change.
  useEffect(() => {
    const canvases = map.getContainer().querySelectorAll<HTMLCanvasElement>('canvas.leaflet-heatmap-layer')
    canvases.forEach((canvas) => {
      canvas.style.opacity = String(opacity)
    })
  }, [map, features, metric, opacity])

  return null
}

// One discrete marker per feature instead of blurring them into a heat blob - keeps
// raw mode's point-level detail (which device, the value at that exact spot) instead of throwing
// it away, and reuses HeatLayer's own color-at-value logic so switching display style doesn't
// change what a given value looks like.
//
// Clicking a marker selects it (replacing any other selection); shift-clicking toggles it into/
// out of the selection instead, building up a multi-point comparison - see the selected-points
// table rendered below the map. The row filter that produced these features already guarantees
// `metric`'s own column is non-null (see app/measurements_query.py::query_raw_points), so reading
// it here never falls back to a "no data" color.
function PointsLayer({
  features,
  metric,
  selectedIndices,
  onPointClick,
  opacity,
}: {
  features: PublicRawFeature[]
  metric: MeasurementMetric
  selectedIndices: number[]
  onPointClick: (index: number, shiftKey: boolean) => void
  opacity: number
}) {
  return (
    <>
      {features.map((feature, index) => {
        const [lon, lat] = feature.geometry.coordinates
        const value = feature.properties[metric]!
        const selected = selectedIndices.includes(index)
        return (
          <CircleMarker
            key={index}
            center={[lat, lon]}
            radius={6}
            pathOptions={{
              color: selected ? '#000000' : '#1a1a1a',
              weight: selected ? 3 : 1,
              fillColor: colorForMetricValue(metric, value),
              fillOpacity: 0.85 * opacity,
              opacity,
            }}
            eventHandlers={{
              click: (e: LeafletMouseEvent) => onPointClick(index, e.originalEvent.shiftKey),
            }}
          />
        )
      })}
    </>
  )
}

// Latency counterpart of PointsLayer: each result is drawn as a line between its
// start and end fix instead of a single marker, colored through the same shared color logic.
function LatencyPointsLayer({
  features,
  metric,
  selectedIndices,
  onPointClick,
  opacity,
}: {
  features: PublicLatencyFeature[]
  metric: LatencyMetric
  selectedIndices: number[]
  onPointClick: (index: number, shiftKey: boolean) => void
  opacity: number
}) {
  return (
    <>
      {features.map((feature, index) => {
        const [[startLon, startLat], [endLon, endLat]] = feature.geometry.coordinates
        const value = feature.properties[metric]!
        const selected = selectedIndices.includes(index)
        return (
          <Polyline
            key={index}
            positions={[
              [startLat, startLon],
              [endLat, endLon],
            ]}
            pathOptions={{
              color: colorForMetricValue(metric, value),
              weight: selected ? 8 : 4,
              opacity: 0.9 * opacity,
            }}
            eventHandlers={{
              click: (e: LeafletMouseEvent) => onPointClick(index, e.originalEvent.shiftKey),
            }}
          />
        )
      })}
    </>
  )
}

// Ctrl+drag zooms to the rectangle (replacing Leaflet's Shift-bound box zoom, see boxZoom={false}
// on the MapContainer); Shift+drag hands the rectangle to the page to select the points inside it.
function BoxDragControls({
  onSelectBox,
}: {
  onSelectBox: ((bounds: GeoBounds) => void) | null
}) {
  const map = useMap()
  const onSelectBoxRef = useRef(onSelectBox)
  onSelectBoxRef.current = onSelectBox

  useEffect(
    () =>
      attachModifierBoxDrag(map, {
        onZoomBox: ({ south, west, north, east }) =>
          map.fitBounds([
            [south, west],
            [north, east],
          ]),
        onSelectBox: (bounds) => onSelectBoxRef.current?.(bounds),
      }),
    [map],
  )

  return null
}

function MapResizer({ height, onResize }: { height: number; onResize: (bounds: LatLngBounds) => void }) {
  const map = useMap()

  useEffect(() => {
    // The wrapper div's height changes after mount (see updateMapHeight), but Leaflet only
    // measures its container once - without this it keeps rendering/querying at the old size.
    map.invalidateSize()
    onResize(map.getBounds())
    // onResize is the inline setBbox(boundsToBbox(...)) closure below; only height should
    // trigger a re-measure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, height])

  return null
}

function BoundsWatcher({ onChange }: { onChange: (bounds: LatLngBounds) => void }) {
  const map = useMapEvents({
    moveend: () => onChange(map.getBounds()),
  })

  useEffect(() => {
    onChange(map.getBounds())
    // Only run once, on mount, to seed the initial bbox - onChange is stable across renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return null
}

interface MeasurementExtent {
  bbox: [number, number, number, number] | null
}

async function fetchExtentBounds(
  metric: Metric,
  campaignId: number | null,
  missionType: string,
  signal: AbortSignal,
): Promise<LatLngBounds | null> {
  const query = buildQuery({
    metric,
    mission_type: missionType,
    campaign_id: campaignId != null ? String(campaignId) : undefined,
  })
  const response = await fetch(`${metricApiPath(metric)}/extent?${query}`, { signal })
  if (!response.ok) return null
  const data: MeasurementExtent = await response.json()
  if (!data.bbox) return null
  const [minLon, minLat, maxLon, maxLat] = data.bbox
  return L.latLngBounds([minLat, minLon], [maxLat, maxLon])
}

// Fits the map to existing data once per mount/campaign/mission-type change, not on every filter
// or BoundsWatcher-driven refetch - re-fitting under the user while they pan/zoom would fight them.
function InitialViewFitter({
  campaignId,
  metric,
  missionType,
}: {
  campaignId: number | null
  metric: Metric
  missionType: string
}) {
  const map = useMap()
  const firedFor = useRef<string | 'never'>('never')

  useEffect(() => {
    const key = `${campaignId}:${missionType}`
    if (firedFor.current === key) return
    firedFor.current = key

    const controller = new AbortController()

    async function fitToData() {
      // The real extent of the matching rows - not grid cell centers, so there's no
      // inset between what's fitted and where the data actually is.
      const bounds = await fetchExtentBounds(metric, campaignId, missionType, controller.signal)
      if (!bounds) return

      map.fitBounds(bounds, { padding: [20, 20] })
    }

    // No data yet, or the fetch failed - leave the map at its default center/zoom.
    fitToData().catch(() => {})

    return () => controller.abort()
    // metric intentionally excluded - this should only re-run on campaign/mission-type change,
    // not every time the user changes the metric filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, campaignId, missionType])

  return null
}

function formatStat(value: number): string {
  return value.toFixed(2)
}

async function downloadExport(bbox: string, filters: Filters, format: 'csv' | 'geojson') {
  const query = buildQuery({ ...filterParams(filters), bbox, format })
  const response = await fetch(`${API_BASE}/measurements/export?${query}`)
  if (!response.ok) {
    throw new Error(`Export failed with status ${response.status}`)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `measurements.${format}`
  link.click()
  URL.revokeObjectURL(url)
}

async function downloadPngScreenshot(mapElement: HTMLElement) {
  const canvas = await html2canvas(mapElement, { useCORS: true })
  const url = canvas.toDataURL('image/png')
  const link = document.createElement('a')
  link.href = url
  link.download = 'measurements-map.png'
  link.click()
}

export function MapHeatmapPage() {
  const { t } = useTranslation('map')
  const { isAuthenticated } = useAuth()
  const isDarkMode = useIsDarkMode()
  const [searchParams, setSearchParams] = useSearchParams()
  // Opened from the Runs page ("Show on map"): scopes the view to one run of one device. Only
  // for logged-in users - run IDs never appear in the public endpoints, so anonymous visitors
  // just get the normal public map.
  const runId = isAuthenticated ? searchParams.get('run') : null
  const campaignHint = runId ? Number(searchParams.get('campaign')) || null : null
  // Runs are identified by (device_id, run_id), so the device filter must already be in place for
  // the first fetch rather than arriving after the Device ID input's debounce.
  const [initialDeviceId] = useState(() => (runId ? (searchParams.get('device') ?? '') : ''))
  // The map always shows exactly one mission type, so a drone run opened from the Runs page has to
  // start on drone or the default would hide it.
  const [initialMissionType] = useState(() =>
    runId ? parseMissionType(searchParams.get('mission')) : DEFAULT_MISSION_TYPE,
  )
  const [filters, setFilters] = useState<Filters>({
    metric: 'rsrp',
    missionType: initialMissionType,
    deviceId: initialDeviceId,
    campaignId: null,
  })
  // Guests get 'points' too, but backed by the public endpoints whose rows carry no
  // device ID or timestamp - see fetchPublicMeasurementPoints / fetchPublicLatencyPoints.
  const [selectedDisplayStyle, setDisplayStyle] = useState<DisplayStyle>('heatmap')
  const [layerOpacity, setLayerOpacity] = useState(1)
  // Only the raw endpoints can filter by run, so a run always renders as Points.
  const displayStyle: DisplayStyle = runId ? 'points' : selectedDisplayStyle
  const [deviceIdInput, setDeviceIdInput] = useState(initialDeviceId)
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [bbox, setBbox] = useState<string | null>(null)
  const [heatmapFeatures, setHeatmapFeatures] = useState<HeatmapFeature[]>([])
  const [rawFeatures, setRawFeatures] = useState<(RawFeature | PublicRawFeature)[]>([])
  const [latencyRawFeatures, setLatencyRawFeatures] = useState<(LatencyRawFeature | PublicLatencyFeature)[]>([])
  // Indices into rawFeatures - which markers the user clicked (plain click replaces the
  // selection, shift-click toggles into/out of it) to compare in the table below the map.
  const [selectedIndices, setSelectedIndices] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState<string | null>(null)
  const [exportingSelection, setExportingSelection] = useState<SelectionExportFormat | null>(null)
  const [mapHeight, setMapHeight] = useState(MIN_MAP_HEIGHT)
  const [isFullscreen, setIsFullscreen] = useState(false)
  // Gates rendering InitialViewFitter until the default campaign (if any) is known, so the
  // initial data-driven fit fires once for the real campaign instead of once for `null` and
  // again right after when the default campaign resolves.
  const [campaignsLoaded, setCampaignsLoaded] = useState(false)

  const mapWrapperRef = useRef<HTMLDivElement>(null)
  const pointsPanelRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    fetchPublicCampaigns()
      .then(({ campaigns }) => {
        setCampaigns(campaigns)
        const current = defaultCampaign(campaigns)
        // A run can lie outside the current campaign, so a run view starts on "All time".
        if (current && !runId) {
          setFilters((prev) => ({ ...prev, campaignId: current.id }))
        }
      })
      .catch(() => setError(i18n.t('map:loadCampaignsFailed')))
      .finally(() => setCampaignsLoaded(true))
    // runId is only read for the initial selection, not a reason to refetch the campaign list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    // Fills to the bottom of the viewport instead of leaving whitespace below a fixed height -
    // measured against the actual layout rather than a hardcoded offset, since the surrounding
    // shell's header/content padding isn't a fixed height.
    function updateMapHeight() {
      if (!mapWrapperRef.current) return
      const top = mapWrapperRef.current.getBoundingClientRect().top
      setMapHeight(Math.max(MIN_MAP_HEIGHT, window.innerHeight - top - PAGE_BOTTOM_PADDING))
    }

    // Entering/exiting fullscreen doesn't reliably fire a `resize` event in every browser, so
    // recompute explicitly here: the full viewport height while fullscreen, the normal
    // layout-based height otherwise. MapResizer re-measures Leaflet's own container whenever
    // mapHeight changes.
    function handleFullscreenChange() {
      const nowFullscreen = document.fullscreenElement === mapWrapperRef.current
      setIsFullscreen(nowFullscreen)
      if (nowFullscreen) {
        setMapHeight(window.innerHeight)
      } else {
        updateMapHeight()
      }
    }

    updateMapHeight()
    window.addEventListener('resize', updateMapHeight)
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => {
      window.removeEventListener('resize', updateMapHeight)
      document.removeEventListener('fullscreenchange', handleFullscreenChange)
    }
  }, [])

  useEffect(() => {
    const timeout = setTimeout(() => {
      setFilters((prev) => ({ ...prev, deviceId: deviceIdInput }))
    }, 400)

    return () => clearTimeout(timeout)
  }, [deviceIdInput])

  // The heatmap endpoints always cover one campaign, so leaving "All time" selected would show
  // the latest campaign while claiming to show everything - select that campaign instead.
  function handleDisplayStyleChange(style: DisplayStyle) {
    setDisplayStyle(style)
    if (style === 'heatmap' && filters.campaignId === null) {
      const current = defaultCampaign(campaigns)
      if (current) {
        setFilters((prev) => ({ ...prev, campaignId: current.id }))
      }
    }
  }

  const fetchHeatmap = useCallback(async () => {
    if (!bbox) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)

    try {
      if (displayStyle === 'points' && isLatencyMetric(filters.metric)) {
        const data = isAuthenticated
          ? await fetchLatencyRaw({
              bbox,
              metric: filters.metric,
              deviceId: filters.deviceId || undefined,
              missionType: filters.missionType,
              campaignId: filters.campaignId,
              runId: runId ?? undefined,
            })
          : await fetchPublicLatencyPoints({
              bbox,
              metric: filters.metric,
              missionType: filters.missionType,
              campaignId: filters.campaignId,
            })
        setLatencyRawFeatures(data.features)
        setSelectedIndices([])
        return
      }

      if (displayStyle === 'points') {
        const data = isAuthenticated
          ? await fetchDetailedMeasurements({
              bbox,
              metric: filters.metric,
              view: 'raw',
              deviceId: filters.deviceId || undefined,
              missionType: filters.missionType,
              campaignId: filters.campaignId,
              runId: runId ?? undefined,
            })
          : await fetchPublicMeasurementPoints({
              bbox,
              metric: filters.metric,
              missionType: filters.missionType,
              campaignId: filters.campaignId,
            })
        setRawFeatures(data.features as (RawFeature | PublicRawFeature)[])
        setSelectedIndices([])
        return
      }

      const query = buildQuery({ ...filterParams(filters), bbox })
      const response = await fetch(`${metricApiPath(filters.metric)}/heatmap?${query}`, {
        signal: controller.signal,
      })
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`)
      }
      const data: HeatmapFeatureCollection = await response.json()
      setHeatmapFeatures(data.features)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setError(heatmapErrorMessage(err))
    } finally {
      if (abortRef.current === controller) {
        setLoading(false)
      }
    }
  }, [bbox, filters, isAuthenticated, displayStyle, runId])

  useEffect(() => {
    fetchHeatmap()
  }, [fetchHeatmap])

  // The map fills down to the bottom of the viewport, so the selected-points table below it
  // starts out entirely off-screen - without this, clicking a marker looks like it does nothing
  // at all until the user thinks to scroll down. Only fires on a brand new selection (0 -> 1+),
  // not on every subsequent shift-click, so building up a multi-point comparison doesn't keep
  // yanking the page back down underneath the user.
  const hadSelectionRef = useRef(false)
  useEffect(() => {
    const hasSelection = selectedIndices.length > 0
    if (hasSelection && !hadSelectionRef.current) {
      pointsPanelRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
    }
    hadSelectionRef.current = hasSelection
  }, [selectedIndices])

  const clearRunFilter = () => {
    setSearchParams({}, { replace: true })
    setFilters((prev) => ({ ...prev, deviceId: '' }))
    setDeviceIdInput('')
  }

  const toggleFullscreen = () => {
    if (!mapWrapperRef.current) return
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {})
    } else {
      mapWrapperRef.current.requestFullscreen().catch(() => {})
    }
  }

  const handleExport = async (format: 'csv' | 'geojson' | 'png') => {
    if (!bbox) return
    setExporting(format)
    setError(null)
    try {
      if (format === 'png') {
        if (mapWrapperRef.current) {
          await downloadPngScreenshot(mapWrapperRef.current)
        }
      } else {
        await downloadExport(bbox, filters, format)
      }
    } catch {
      setError(t('exportFailed', { format: format.toUpperCase() }))
    } finally {
      setExporting(null)
    }
  }

  const handleSelectionExport = async (format: SelectionExportFormat) => {
    const ids = selectedIndices.flatMap((index) => {
      const id = rawFeatures[index]?.properties.id
      return id === undefined ? [] : [id]
    })
    setExportingSelection(format)
    setError(null)
    try {
      await downloadSelectionExport(ids, format)
    } catch {
      setError(t('selection.exportFailed', { format: format.toUpperCase() }))
    } finally {
      setExportingSelection(null)
    }
  }

  // Plain click replaces the selection with just this point; shift-click toggles it into/out of
  // the existing selection instead, so several points can be compared side by side at once.
  const handlePointClick = (index: number, shiftKey: boolean) => {
    setSelectedIndices((prev) => {
      if (shiftKey) {
        return prev.includes(index) ? prev.filter((i) => i !== index) : [...prev, index]
      }
      return [index]
    })
  }

  // Shift+drag adds every loaded point (or latency line with a fix) inside the rectangle to the
  // selection; points outside the loaded set are not considered.
  const handleBoxSelect = (bounds: GeoBounds) => {
    const fixesPerFeature = isLatencyMetric(filters.metric)
      ? latencyRawFeatures.map(({ geometry }) =>
          geometry.coordinates.map(([lon, lat]) => [lat, lon] as const),
        )
      : rawFeatures.map(({ geometry }) => [[geometry.coordinates[1], geometry.coordinates[0]] as const])
    const inside = indicesInBounds(fixesPerFeature, bounds)
    if (inside.length === 0) return
    setSelectedIndices((prev) => [...new Set([...prev, ...inside])])
  }

  const latencySelected = isLatencyMetric(filters.metric)
  const selectedValues = selectedIndices.flatMap((index) => {
    const value = isLatencyMetric(filters.metric)
      ? latencyRawFeatures[index]?.properties[filters.metric]
      : rawFeatures[index]?.properties[filters.metric as MeasurementMetric]
    return value == null ? [] : [value]
  })
  const selectionStats = computeSelectionStats(selectedValues)
  const exportDisabledReason = latencySelected
    ? t('exportOnlyMeasurement')
    : displayStyle !== 'heatmap'
      ? t('exportOnlyHeatmap')
      : undefined

  return (
    <section>
      <div className="page-header page-header--row" style={{ marginBottom: 'var(--space-4)' }}>
        <div>
          <h1 className="page-header__title">{t('title')}</h1>
          <p className="page-header__subtitle">
            {t('subtitle')}
          </p>
        </div>
        <Button onClick={fetchHeatmap} disabled={loading}>
          {t('refresh')}
        </Button>
      </div>

      <div className="filter-grid">
        <Select
          label={t('filters.metric')}
          value={filters.metric}
          onChange={(e) => setFilters((prev) => ({ ...prev, metric: e.target.value as Metric }))}
        >
          {METRICS.map((metric) => (
            <option key={metric} value={metric}>{metricLabel(metric)}</option>
          ))}
        </Select>

        <Select
          label={t('filters.missionType')}
          value={filters.missionType}
          onChange={(e) =>
            setFilters((prev) => ({ ...prev, missionType: parseMissionType(e.target.value) }))
          }
        >
          {MISSION_TYPES.map((type) => (
            <option key={type} value={type}>{t(`missionType.${type}`, { ns: 'common' })}</option>
          ))}
        </Select>

        {/* Not a dropdown of all registered devices - the device roster stays non-public on
            this public page. Enter a known device ID to filter by it. Hidden for anonymous
            visitors - the filter has turned out to not be useful without being logged in, and the
            public Points endpoints deliberately do not accept it. */}
        {isAuthenticated && (
          <TextInput
            label={t('filters.deviceId')}
            type="text"
            value={deviceIdInput}
            onChange={(e) => setDeviceIdInput(e.target.value)}
            placeholder={t('filters.devicePlaceholder')}
          />
        )}

        <Select
          label={t('filters.campaign')}
          value={filters.campaignId ?? ''}
          onChange={(e) =>
            setFilters((prev) => ({
              ...prev,
              campaignId: e.target.value ? Number(e.target.value) : null,
            }))
          }
        >
          {campaigns.length === 0 && <option value="">{t('filters.noCampaigns')}</option>}
          {/* "All time" only makes sense once logged in - the public view is always scoped to
              exactly one campaign (see resolve_campaign) so it can never blend two campaigns.
              The heatmap endpoints are per campaign too, so it is not offered there either. */}
          {isAuthenticated && campaigns.length > 0 && displayStyle !== 'heatmap' && (
            <option value="">{t('filters.allTime')}</option>
          )}
          {campaigns.map((campaign) => (
            <option key={campaign.id} value={campaign.id}>
              {campaign.name}
            </option>
          ))}
        </Select>

        {/* Heatmap renders the public aggregate shape; Points renders individual raw
            measurements - from the authenticated endpoints when logged in, or from the public
            ones (without device ID and timestamp) for guests. */}
        <Select
          label={t('filters.displayStyle')}
          value={displayStyle}
          onChange={(e) => handleDisplayStyleChange(e.target.value as DisplayStyle)}
          disabled={runId !== null}
        >
          <option value="heatmap">{t('filters.heatmap')}</option>
          <option value="points">{t('filters.points')}</option>
        </Select>

        <div className="ui-field">
          <label className="ui-field__label" htmlFor="layer-opacity">
            {t('filters.opacity')}
          </label>
          <input
            id="layer-opacity"
            type="range"
            className="map-opacity-slider"
            min={0}
            max={1}
            step={0.05}
            value={layerOpacity}
            onChange={(e) => setLayerOpacity(Number(e.target.value))}
          />
        </div>
      </div>

      {runId && (
        <Banner tone="warning" style={{ marginBottom: 'var(--space-4)' }}>
          {initialDeviceId ? t('runFilter.withDevice', { runId, deviceId: initialDeviceId }) : t('runFilter.runOnly', { runId })}{' '}
          <Button variant="secondary" size="sm" onClick={clearRunFilter}>
            {t('runFilter.clear')}
          </Button>
        </Banner>
      )}

      <div className="map-export-row">
        {(['csv', 'geojson', 'png'] as const).map((format) => (
          <Button
            key={format}
            variant="secondary"
            size="sm"
            onClick={() => handleExport(format)}
            // Export only ever covers the public aggregate measurement shape - disabled for the
            // Points style and for latency metrics rather than silently exporting
            // different data than what's on screen.
            disabled={exporting !== null || !bbox || displayStyle !== 'heatmap' || latencySelected}
            title={exportDisabledReason}
          >
            {exporting === format ? t('exporting') : t('export', { format: format.toUpperCase() })}
          </Button>
        ))}
      </div>

      {error && <Banner tone="danger" style={{ marginBottom: 'var(--space-4)' }}>{error}</Banner>}

      <div
        ref={mapWrapperRef}
        className={`map-wrapper${isDarkMode ? ' map-wrapper--dark' : ''}`}
        style={{ height: `${mapHeight}px` }}
      >
        {/* Lives inside the fullscreened element (unlike the filter/export controls above it)
            so it's still reachable to exit fullscreen, not just via the browser's own Esc handling. */}
        <Button
          variant="secondary"
          size="sm"
          className="map-fullscreen-toggle"
          onClick={toggleFullscreen}
        >
          {isFullscreen ? t('exitFullscreen') : t('fullscreen')}
        </Button>
        <MapContainer center={[51.0, 10.0]} zoom={6} boxZoom={false} style={{ height: '100%', width: '100%' }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <BoxDragControls onSelectBox={displayStyle === 'points' ? handleBoxSelect : null} />
          <BoundsWatcher onChange={(bounds) => setBbox(boundsToBbox(bounds))} />
          <MapResizer height={mapHeight} onResize={(bounds) => setBbox(boundsToBbox(bounds))} />
          {displayStyle === 'heatmap' ? (
            <HeatLayer features={heatmapFeatures} metric={filters.metric} opacity={layerOpacity} />
          ) : isLatencyMetric(filters.metric) ? (
            <LatencyPointsLayer
              features={latencyRawFeatures}
              metric={filters.metric}
              selectedIndices={selectedIndices}
              onPointClick={handlePointClick}
              opacity={layerOpacity}
            />
          ) : (
            <PointsLayer
              features={rawFeatures}
              metric={filters.metric}
              selectedIndices={selectedIndices}
              onPointClick={handlePointClick}
              opacity={layerOpacity}
            />
          )}
          {campaignsLoaded && (
            <InitialViewFitter
              campaignId={filters.campaignId ?? campaignHint}
              metric={filters.metric}
              missionType={filters.missionType}
            />
          )}
        </MapContainer>
      </div>

      <p className="map-hint">
        {displayStyle === 'points' ? t('hint.points') : t('hint.heatmap')}
      </p>

      {/* Click a marker above to see its full detail here - RSRP/RSRQ/SINR together (or all five latency
          metrics), not just whichever metric is currently coloring the markers. Shift-click adds more
          rows instead of replacing the selection, for comparing several points at once. Guests
          get the same table without the Device/Time columns: their responses do not
          contain those fields, so the columns are omitted rather than rendered empty. */}
      {displayStyle === 'points' && selectedIndices.length > 0 && (
        <div ref={pointsPanelRef}>
          <Card className="map-points-panel">
            <div className="map-points-panel__header">
              <h2>
                {t('selection.title', { count: selectedIndices.length })}
                {selectionStats && ` - ${metricLabel(filters.metric)}`}
              </h2>
              <div className="map-points-panel__actions">
                {!latencySelected &&
                  (['csv', 'geojson'] as const).map((format) => (
                    <Button
                      key={format}
                      variant="secondary"
                      size="sm"
                      onClick={() => handleSelectionExport(format)}
                      disabled={exportingSelection !== null}
                    >
                      {exportingSelection === format
                        ? t('exporting')
                        : t('selection.export', { format: format === 'csv' ? 'CSV' : 'GeoJSON' })}
                    </Button>
                  ))}
                <Button variant="secondary" size="sm" onClick={() => setSelectedIndices([])}>
                  {t('selection.clear')}
                </Button>
              </div>
            </div>
            {selectionStats && (
              <dl className="map-points-stats" aria-label={t('selection.statistics')}>
                {(
                  [
                    ['count', selectionStats.count],
                    ['min', selectionStats.min],
                    ['max', selectionStats.max],
                    ['mean', selectionStats.mean],
                    ['median', selectionStats.median],
                    ['stdDev', selectionStats.stdDev],
                  ] as const
                ).map(([stat, value]) => (
                  <div key={stat}>
                    <dt>{t(`selection.stats.${stat}`)}</dt>
                    <dd>{stat === 'count' ? value : formatStat(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
            {latencySelected ? (
            <Table>
              <thead>
                <tr>
                  {isAuthenticated && (
                    <>
                      <th>{t('selection.columns.device')}</th>
                      <th>{t('selection.columns.test')}</th>
                      <th>{t('selection.columns.started')}</th>
                    </>
                  )}
                  {LATENCY_METRICS.map((metric) => (
                    <th key={metric}>{metricLabel(metric)}</th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody>
                {selectedIndices.map((index) => {
                  const feature = latencyRawFeatures[index]
                  if (!feature) return null
                  const identity = 'device_id' in feature.properties ? feature.properties : null
                  return (
                    <tr key={index}>
                      {identity && (
                        <>
                          <td>{identity.device_id}</td>
                          <td>{identity.test_type}</td>
                          <td><Timestamp value={identity.start_timestamp} /></td>
                        </>
                      )}
                      {LATENCY_METRICS.map((metric) => (
                        <td key={metric}>{feature.properties[metric] ?? '—'}</td>
                      ))}
                      <td>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={t('selection.remove')}
                          onClick={() =>
                            setSelectedIndices((prev) => prev.filter((i) => i !== index))
                          }
                        >
                          ×
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
            ) : (
            <Table>
              <thead>
                <tr>
                  {isAuthenticated && (
                    <>
                      <th>{t('selection.columns.device')}</th>
                      <th>{t('selection.columns.time')}</th>
                    </>
                  )}
                  <th>RSRP</th>
                  <th>RSRQ</th>
                  <th>SINR</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {selectedIndices.map((index) => {
                  const feature = rawFeatures[index]
                  if (!feature) return null
                  const { rsrp, rsrq, sinr } = feature.properties
                  const identity = 'device_id' in feature.properties ? feature.properties : null
                  return (
                    <tr key={index}>
                      {identity && (
                        <>
                          <td>{identity.device_id}</td>
                          <td><Timestamp value={identity.timestamp} /></td>
                        </>
                      )}
                      <td>{rsrp ?? '—'}</td>
                      <td>{rsrq ?? '—'}</td>
                      <td>{sinr ?? '—'}</td>
                      <td>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={t('selection.remove')}
                          onClick={() =>
                            setSelectedIndices((prev) => prev.filter((i) => i !== index))
                          }
                        >
                          ×
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
            )}
          </Card>
        </div>
      )}
    </section>
  )
}
