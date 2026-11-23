export interface SelectionStats {
  count: number
  min: number
  max: number
  mean: number
  median: number
  stdDev: number
}

export function computeSelectionStats(values: readonly number[]): SelectionStats | null {
  if (values.length === 0) return null

  const sorted = [...values].sort((a, b) => a - b)
  const count = sorted.length
  const mean = sorted.reduce((sum, v) => sum + v, 0) / count
  const variance = sorted.reduce((sum, v) => sum + (v - mean) ** 2, 0) / count
  const middle = Math.floor(count / 2)
  const median = count % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2

  return {
    count,
    min: sorted[0],
    max: sorted[count - 1],
    mean,
    median,
    stdDev: Math.sqrt(variance),
  }
}
