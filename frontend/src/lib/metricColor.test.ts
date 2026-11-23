import { describe, expect, it } from 'vitest'
import {
  METRICS,
  metricLabel,
  METRIC_RANGES,
  MIN_VISIBLE_INTENSITY,
  colorForIntensity,
  colorForMetricValue,
  isLatencyMetric,
  normalizeMetricValue,
} from './metricColor'

describe('normalizeMetricValue', () => {
  it('maps the configured min to the visibility floor and max to 1', () => {
    expect(normalizeMetricValue('rsrp', METRIC_RANGES.rsrp.min)).toBe(MIN_VISIBLE_INTENSITY)
    expect(normalizeMetricValue('rsrp', METRIC_RANGES.rsrp.max)).toBe(1)
  })

  it('clamps values below min to the visibility floor (never 0) and above max to 1', () => {
    // Regression: a point this bad must stay visible (rendered as worst-case red),
    // not disappear - leaflet.heat treats intensity 0 as fully transparent, not "worst color".
    expect(normalizeMetricValue('sinr', METRIC_RANGES.sinr.min - 100)).toBe(MIN_VISIBLE_INTENSITY)
    expect(normalizeMetricValue('sinr', METRIC_RANGES.sinr.max + 100)).toBe(1)
  })

  it('interpolates linearly between min and max', () => {
    const { min, max } = METRIC_RANGES.rsrq
    expect(normalizeMetricValue('rsrq', (min + max) / 2)).toBeCloseTo(0.5)
  })
})

describe('latency metrics', () => {
  it('treats lower RTT as better: the worst-end min maps to the floor, the best-end max to 1', () => {
    expect(normalizeMetricValue('baseline_rtt_ms', 100)).toBe(MIN_VISIBLE_INTENSITY)
    expect(normalizeMetricValue('baseline_rtt_ms', 10)).toBe(1)
    expect(normalizeMetricValue('baseline_rtt_ms', 55)).toBeCloseTo(0.5)
    expect(colorForMetricValue('rtt_p99_ms', 60)).toBe('#00cc00')
  })

  it('clamps RTT values beyond either end of the range', () => {
    expect(normalizeMetricValue('rtt_under_load_ms', 5000)).toBe(MIN_VISIBLE_INTENSITY)
    expect(normalizeMetricValue('rtt_under_load_ms', 1)).toBe(1)
  })

  it('treats higher throughput as better', () => {
    expect(normalizeMetricValue('download_mbits_s', 10)).toBe(MIN_VISIBLE_INTENSITY)
    expect(normalizeMetricValue('download_mbits_s', 500)).toBe(1)
    expect(normalizeMetricValue('upload_mbits_s', 52.5)).toBeCloseTo(0.5)
  })

  it('defines a range and label for every metric', () => {
    for (const metric of METRICS) {
      expect(METRIC_RANGES[metric]).toBeDefined()
      expect(metricLabel(metric)).toBeTruthy()
    }
  })

  it('classifies latency metrics separately from measurement metrics', () => {
    expect(isLatencyMetric('baseline_rtt_ms')).toBe(true)
    expect(isLatencyMetric('rsrp')).toBe(false)
  })
})

describe('colorForIntensity', () => {
  it('returns the exact gradient stop colors at 0, 0.5, and 1', () => {
    expect(colorForIntensity(0)).toBe('#ff0000')
    expect(colorForIntensity(0.5)).toBe('#ffff00')
    expect(colorForIntensity(1)).toBe('#00cc00')
  })

  it('clamps out-of-range intensities to the nearest endpoint color', () => {
    expect(colorForIntensity(-5)).toBe('#ff0000')
    expect(colorForIntensity(5)).toBe('#00cc00')
  })

  it('blends between adjacent stops for intermediate intensities', () => {
    const quarter = colorForIntensity(0.25)
    expect(quarter).not.toBe('#ff0000')
    expect(quarter).not.toBe('#ffff00')
  })
})

describe('colorForMetricValue', () => {
  it('matches heatLayer gradient endpoints for a metric at its range extremes - same color, two call paths (heat layer and point markers)', () => {
    expect(colorForMetricValue('rsrp', METRIC_RANGES.rsrp.min)).toBe(
      colorForIntensity(MIN_VISIBLE_INTENSITY),
    )
    expect(colorForMetricValue('rsrp', METRIC_RANGES.rsrp.max)).toBe(colorForIntensity(1))
  })
})
