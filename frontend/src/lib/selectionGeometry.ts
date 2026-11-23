export interface GeoBounds {
  south: number
  west: number
  north: number
  east: number
}

type LatLng = readonly [lat: number, lng: number]

function contains(bounds: GeoBounds, [lat, lng]: LatLng): boolean {
  return lat >= bounds.south && lat <= bounds.north && lng >= bounds.west && lng <= bounds.east
}

// Each feature is a list of its fixes (one for a measurement point, start + end for a latency
// line); a feature is selected when any of its fixes lies inside the rectangle.
export function indicesInBounds(fixesPerFeature: readonly (readonly LatLng[])[], bounds: GeoBounds): number[] {
  const indices: number[] = []
  fixesPerFeature.forEach((fixes, index) => {
    if (fixes.some((fix) => contains(bounds, fix))) indices.push(index)
  })
  return indices
}
