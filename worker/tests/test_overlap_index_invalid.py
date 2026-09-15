"""
_OverlapIndex indexed layer geometry without validating it.

Every adapter runs buffer(0) on the parcels it fetches; nothing ran on the
layers those parcels are measured against. GEOS raises TopologyException from
intersection() on an invalid polygon, so one malformed feature killed a
20-minute publishing run — which is exactly what happened to Franklin once
its corrected bounding box reached 168 square miles of county the hand-typed
box had missed, and that new ground turned out to carry a bad PAD-US feature.

    shapely.errors.GEOSException: TopologyException: side location conflict
    at -191753.45911614501 4442219.093763059
"""

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

from parcel_gates import _OverlapIndex


def _bowtie():
    """
    A self-intersecting polygon — the classic source of "side location
    conflict". Invalid, non-empty, and fatal to intersection().
    """
    p = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])
    assert not p.is_valid
    return p


def _layer(*geoms):
    return gpd.GeoDataFrame({"geometry": list(geoms)}, crs="EPSG:5070")


def test_an_invalid_layer_polygon_no_longer_kills_the_run():
    """The regression. Before the fix this raised GEOSException."""
    ix = _OverlapIndex(_layer(_bowtie()))
    parcel = box(0, 0, 10, 10)
    pct = ix.fraction(parcel, parcel.area)      # must not raise
    assert 0.0 <= pct <= 100.0


def test_every_indexed_part_is_valid_after_construction():
    ix = _OverlapIndex(_layer(_bowtie(), box(20, 20, 30, 30)))
    assert ix._parts, "the repair must not throw the layer away"
    assert all(p.is_valid for p in ix._parts)


def test_the_repair_keeps_area_rather_than_discarding_it():
    """
    The direction that matters. This index decides protected_land, which
    FAILS at 0.5% overlap — silently shrinking a protected area turns a FAIL
    into a PASS, and that is the one error that must not happen quietly.
    The bowtie's two triangles are 50 of the 100-unit envelope.
    """
    ix = _OverlapIndex(_layer(_bowtie()))
    parcel = box(0, 0, 10, 10)
    pct = ix.fraction(parcel, parcel.area)
    assert pct > 40.0, f"repair lost the polygon's area: {pct}%"


def test_non_polygonal_shards_from_the_repair_are_dropped():
    """
    make_valid can return a GeometryCollection carrying lines beside
    polygons. This is an area index; a line contributes no area and only
    risk.
    """
    spike = Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0),
                     (0, 0), (20, 0), (0, 0)])
    ix = _OverlapIndex(_layer(spike))
    assert all(p.geom_type == "Polygon" for p in ix._parts)


def test_valid_geometry_is_untouched():
    square = box(0, 0, 10, 10)
    ix = _OverlapIndex(_layer(square))
    assert len(ix._parts) == 1
    assert ix._parts[0].equals(square)


@pytest.mark.parametrize("gdf", [None, gpd.GeoDataFrame({"geometry": []})])
def test_an_absent_layer_is_still_absent(gdf):
    ix = _OverlapIndex(gdf)
    assert ix.fraction(box(0, 0, 1, 1), 1.0) == 0.0
