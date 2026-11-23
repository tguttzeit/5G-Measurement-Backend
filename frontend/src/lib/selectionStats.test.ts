import { describe, expect, it } from 'vitest'
import { computeSelectionStats } from './selectionStats'

describe('computeSelectionStats', () => {
  it('returns null for an empty list', () => {
    expect(computeSelectionStats([])).toBeNull()
  })

  it('handles a single value', () => {
    expect(computeSelectionStats([-90])).toEqual({
      count: 1,
      min: -90,
      max: -90,
      mean: -90,
      median: -90,
      stdDev: 0,
    })
  })

  it('computes min, max, mean and population standard deviation', () => {
    const stats = computeSelectionStats([2, 4, 4, 4, 5, 5, 7, 9])!
    expect(stats.count).toBe(8)
    expect(stats.min).toBe(2)
    expect(stats.max).toBe(9)
    expect(stats.mean).toBe(5)
    expect(stats.stdDev).toBe(2)
  })

  it('uses the middle value as median for an odd count', () => {
    expect(computeSelectionStats([9, 1, 5])!.median).toBe(5)
  })

  it('averages the two middle values as median for an even count', () => {
    expect(computeSelectionStats([4, 1, 3, 2])!.median).toBe(2.5)
  })

  it('does not mutate its input', () => {
    const values = [3, 1, 2]
    computeSelectionStats(values)
    expect(values).toEqual([3, 1, 2])
  })
})
