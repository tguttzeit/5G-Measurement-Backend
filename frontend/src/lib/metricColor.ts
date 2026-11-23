import i18n from '../i18n'
// Shared metric -> intensity -> color logic for the map, so the heat layer and
// the individual point markers render the same value through the same colors instead of each
// maintaining their own copy.

export const MEASUREMENT_METRICS = ['rsrp', 'rsrq', 'sinr'] as const
// Latency/throughput results - served by /latency-results/* rather than
// /measurements/*, but colored through the same ranges/gradient as the signal metrics.
export const LATENCY_METRICS = [
  'baseline_rtt_ms',
  'rtt_under_load_ms',
  'rtt_p99_ms',
  'download_mbits_s',
  'upload_mbits_s',
] as const
export const METRICS = [...MEASUREMENT_METRICS, ...LATENCY_METRICS] as const
export type MeasurementMetric = typeof MEASUREMENT_METRICS[number]
export type LatencyMetric = typeof LATENCY_METRICS[number]
export type Metric = typeof METRICS[number]

export function isLatencyMetric(metric: Metric): metric is LatencyMetric {
  return (LATENCY_METRICS as readonly string[]).includes(metric)
}

export function metricLabel(metric: Metric): string {
  return i18n.t(`common:metric.${metric}`)
}

// Industry-standard LTE/5G signal-quality endpoints -
// "excellent" and "poor" as commonly defined by network-quality tooling, not derived from any
// particular campaign's observed data. A weak campaign should read as weak, not get rescaled to
// span the full red-to-green range against itself.
export const METRIC_RANGES: Record<Metric, { min: number; max: number }> = {
  rsrp: { min: -110, max: -80 },
  rsrq: { min: -20, max: -10 },
  sinr: { min: 0, max: 20 },
  // `min` is always the worst end, so for the RTT metrics (lower ms = better) it is numerically
  // greater than `max` - normalizeMetricValue handles that without any special-casing.
  baseline_rtt_ms: { min: 100, max: 10 },
  rtt_under_load_ms: { min: 200, max: 30 },
  rtt_p99_ms: { min: 350, max: 60 },
  download_mbits_s: { min: 10, max: 500 },
  upload_mbits_s: { min: 5, max: 100 },
}

// A real measurement this far below the configured range's min still renders as this much
// intensity, never all the way down to 0. leaflet.heat's heat layer treats intensity as the
// point's alpha weight - an intensity of exactly 0 paints nothing at all (fully transparent),
// not "worst-case red" - so a point this poor would otherwise be invisible rather than the
// deep-red color its value should show. Small enough to still read as "near the bottom" on the
// gradient, large enough to actually render.
export const MIN_VISIBLE_INTENSITY = 0.05

// Normalized metric value (MIN_VISIBLE_INTENSITY = worst, 1 = best/max), clamped - a value
// outside the defined range still renders as the most-extreme color instead of under/overflowing
// it, and never drops to fully-transparent (see MIN_VISIBLE_INTENSITY).
export function normalizeMetricValue(metric: Metric, value: number): number {
  const { min, max } = METRIC_RANGES[metric]
  return Math.max(MIN_VISIBLE_INTENSITY, Math.min(1, (value - min) / (max - min)))
}

// Red -> yellow -> green: the traffic-light convention most signal-strength tools use, passed
// explicitly to `heatLayer()` instead of its default blue-to-red gradient.
export const METRIC_GRADIENT: Record<number, string> = {
  0.0: '#ff0000',
  0.5: '#ffff00',
  1.0: '#00cc00',
}

const GRADIENT_STOPS = Object.entries(METRIC_GRADIENT)
  .map(([stop, color]) => [Number(stop), color] as const)
  .sort((a, b) => a[0] - b[0])

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function rgbToHex([r, g, b]: [number, number, number]): string {
  return `#${[r, g, b].map((c) => Math.round(c).toString(16).padStart(2, '0')).join('')}`
}

// The same color-at-intensity mapping `heatLayer`'s `gradient` option resolves internally for
// the canvas heat layer, exposed here so a discrete marker can be colored identically.
export function colorForIntensity(intensity: number): string {
  const clamped = Math.max(0, Math.min(1, intensity))
  for (let i = 1; i < GRADIENT_STOPS.length; i++) {
    const [stopA, colorA] = GRADIENT_STOPS[i - 1]
    const [stopB, colorB] = GRADIENT_STOPS[i]
    if (clamped <= stopB) {
      const t = (clamped - stopA) / (stopB - stopA)
      const rgbA = hexToRgb(colorA)
      const rgbB = hexToRgb(colorB)
      return rgbToHex([
        rgbA[0] + (rgbB[0] - rgbA[0]) * t,
        rgbA[1] + (rgbB[1] - rgbA[1]) * t,
        rgbA[2] + (rgbB[2] - rgbA[2]) * t,
      ])
    }
  }
  return GRADIENT_STOPS[GRADIENT_STOPS.length - 1][1]
}

export function colorForMetricValue(metric: Metric, value: number): string {
  return colorForIntensity(normalizeMetricValue(metric, value))
}
