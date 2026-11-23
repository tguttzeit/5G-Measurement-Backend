"""Unit tests for the fixed-origin, zoom-bucketed grid sizing.

Pure math, no DB needed - see test_measurements_heatmap.py / test_measurements_extent.py for the
query-level integration tests.
"""
from app.measurements_query import GRID_SIZE, BoundingBox, _grid_cell_size


def test_cell_size_is_identical_for_same_sized_bbox_at_different_pan_positions():
    """The whole point of anchoring to a fixed origin: two bboxes of the same size, shifted by a
    pan, must land on the same zoom level (and therefore the same cell boundaries) - a
    bbox-relative grid would instead recompute a unique cell size for each."""
    bbox_a = BoundingBox(min_lon=13.0, min_lat=52.0, max_lon=13.5, max_lat=52.5)
    bbox_b = BoundingBox(min_lon=13.1, min_lat=52.05, max_lon=13.6, max_lat=52.55)

    assert _grid_cell_size(bbox_a) == _grid_cell_size(bbox_b)


def test_cell_size_covers_world_bbox_in_exactly_grid_size_cells():
    bbox = BoundingBox(min_lon=-180, min_lat=-90, max_lon=180, max_lat=90)

    cell_lon, cell_lat = _grid_cell_size(bbox)

    assert 360 / cell_lon == GRID_SIZE
    assert 180 / cell_lat == GRID_SIZE


def test_cell_count_stays_within_grid_size_bound_for_a_tight_bbox():
    bbox = BoundingBox(min_lon=13.0, min_lat=52.0, max_lon=13.5, max_lat=52.5)

    cell_lon, cell_lat = _grid_cell_size(bbox)

    assert (bbox.max_lon - bbox.min_lon) / cell_lon <= GRID_SIZE
    assert (bbox.max_lat - bbox.min_lat) / cell_lat <= GRID_SIZE


def test_smaller_bbox_gets_finer_or_equal_cells():
    wide = BoundingBox(min_lon=10.0, min_lat=48.0, max_lon=11.0, max_lat=49.0)
    narrow = BoundingBox(min_lon=10.0, min_lat=48.0, max_lon=10.1, max_lat=48.1)

    wide_cell_lon, wide_cell_lat = _grid_cell_size(wide)
    narrow_cell_lon, narrow_cell_lat = _grid_cell_size(narrow)

    assert narrow_cell_lon <= wide_cell_lon
    assert narrow_cell_lat <= wide_cell_lat
