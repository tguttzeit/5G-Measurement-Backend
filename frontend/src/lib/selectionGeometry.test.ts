import { describe, expect, it } from 'vitest'
import { indicesInBounds, type GeoBounds } from './selectionGeometry'

const bounds: GeoBounds = { south: 48, west: 10, north: 49, east: 11 }

describe('indicesInBounds', () => {
  it('returns indices of points inside the bounds, edges included', () => {
    const points: [number, number][] = [
      [48.5, 10.5],
      [50, 10.5],
      [48, 10],
      [48.5, 12],
    ]
    expect(indicesInBounds(points.map((p) => [p]), bounds)).toEqual([0, 2])
  })

  it('matches a line when its start or end lies inside the bounds', () => {
    const lines: [number, number][][] = [
      [[48.5, 10.5], [60, 20]],
      [[60, 20], [48.5, 10.5]],
      [[60, 20], [61, 21]],
    ]
    expect(indicesInBounds(lines, bounds)).toEqual([0, 1])
  })

  it('returns an empty list when nothing is inside', () => {
    expect(indicesInBounds([[[0, 0]]], bounds)).toEqual([])
  })
})
