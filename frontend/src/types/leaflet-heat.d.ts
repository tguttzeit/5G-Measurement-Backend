// leaflet.heat has no published types; it augments the global `L` namespace at runtime with
// `L.heatLayer(...)`. This just gives the import itself a module shape so TS accepts it -
// see MapHeatmapPage.tsx for the (typed via a local interface) call site.
declare module 'leaflet.heat'
