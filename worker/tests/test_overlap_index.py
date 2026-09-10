"""
`_OverlapIndex` must agree with the union-and-intersect it replaced.

The optimisation was a performance change, not a semantic one: an STRtree
narrows by bounding box and the surviving candidates are unioned and
intersected exactly as before. That claim is only worth what it is tested
against, and it sits directly under five gate verdicts — wetlands,
floodway, floodplain, protected land, and water availability — so a
silently different answer here is a wrong verdict on a real parcel.

The reference implementation below is the previous code, kept verbatim so
the comparison stays honest.
"""

import random

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from parcel_gates import _OverlapIndex

CRS = "EPSG:3857"


def reference_fraction(parcel_geom, layer_union, parcel_area_m2):
    """The implementation `_OverlapIndex` replaced."""
    if layer_union is None or parcel_area_m2 <= 0:
        return 0.0
    inter = parcel_geom.intersection(layer_union)
    if inter.is_empty:
        return 0.0
    return float(min(100.0, (inter.area / parcel_area_m2) * 100.0))


def gdf(parts):
    return gpd.GeoDataFrame(geometry=list(parts), crs=CRS) if parts else None


class TestEquivalence:
    @pytest.mark.parametrize("n_parts", [0, 1, 2, 25, 200])
    def test_matches_reference_on_random_layers(self, n_parts):
        rng = random.Random(1234 + n_parts)
        parts = [
            box(x, y, x + rng.uniform(5, 80), y + rng.uniform(5, 80))
            for x, y in (
                (rng.uniform(0, 1000), rng.uniform(0, 1000)) for _ in range(n_parts)
            )
        ]
        ix = _OverlapIndex(gdf(parts))
        union = unary_union(parts) if parts else None

        for _ in range(60):
            px, py = rng.uniform(0, 1000), rng.uniform(0, 1000)
            parcel = box(px, py, px + rng.uniform(5, 150), py + rng.uniform(5, 150))
            area = parcel.area
            assert ix.fraction(parcel, area) == pytest.approx(
                reference_fraction(parcel, union, area), abs=1e-9
            )

    def test_matches_reference_on_overlapping_parts(self):
        """
        Overlapping layer parts are the case a naive per-part sum would get
        wrong — double-counting the shared area and reporting >100%. The
        candidates must be unioned before the intersection, not added.
        """
        parts = [box(0, 0, 10, 10), box(5, 0, 15, 10), box(8, 0, 18, 10)]
        ix = _OverlapIndex(gdf(parts))
        parcel = box(0, 0, 20, 10)
        area = parcel.area
        got = ix.fraction(parcel, area)
        assert got == pytest.approx(
            reference_fraction(parcel, unary_union(parts), area), abs=1e-9
        )
        assert got == pytest.approx(90.0, abs=1e-9)  # 18 of 20 units wide

    def test_multipart_layer_matches_the_same_layer_exploded(self):
        """
        The index explodes MultiPolygons so the tree can narrow to the
        parts near the parcel (a million-vertex wetland complex in one
        feature otherwise follows every parcel its envelope touches). The
        explode must not change the answer: fraction against the multipart
        layer equals fraction against the same polygons supplied loose.
        """
        loose = [box(0, 0, 6, 6), box(20, 0, 26, 6), box(40, 0, 46, 6)]
        from shapely.geometry import MultiPolygon

        as_parts = gdf(loose)
        as_multiparts = gdf([MultiPolygon(loose), loose[0]])
        parcel = box(0, 0, 30, 6)
        assert _OverlapIndex(as_multiparts).fraction(
            parcel, parcel.area
        ) == pytest.approx(_OverlapIndex(as_parts).fraction(parcel, parcel.area))

    def test_multipart_layer_matches_the_reference_union(self):
        # Same claim against the reference implementation, not just the
        # exploded form of itself: the union of the parts is the union of
        # the feature.
        from shapely.geometry import MultiPolygon

        feature = MultiPolygon([box(0, 0, 10, 10), box(15, 0, 25, 10)])
        ix = _OverlapIndex(gdf([feature, box(8, 0, 18, 10)]))
        parcel = box(0, 0, 30, 10)
        assert ix.fraction(parcel, parcel.area) == pytest.approx(
            reference_fraction(
                parcel, unary_union([feature, box(8, 0, 18, 10)]), parcel.area
            ),
            abs=1e-9,
        )


class TestEdgeCases:
    def test_absent_layer_is_zero_not_an_error(self):
        # A layer that failed to fetch must yield 0% so the caller can
        # concede UNKNOWN, never raise mid-run.
        assert _OverlapIndex(None).fraction(box(0, 0, 10, 10), 100.0) == 0.0

    def test_empty_geodataframe_is_zero(self):
        assert _OverlapIndex(gdf([])).fraction(box(0, 0, 10, 10), 100.0) == 0.0

    def test_zero_area_parcel_is_zero_not_a_division_error(self):
        ix = _OverlapIndex(gdf([box(0, 0, 10, 10)]))
        assert ix.fraction(box(0, 0, 10, 10), 0.0) == 0.0

    def test_full_containment_is_one_hundred_percent(self):
        ix = _OverlapIndex(gdf([box(-5, -5, 15, 15)]))
        parcel = box(0, 0, 10, 10)
        assert ix.fraction(parcel, parcel.area) == pytest.approx(100.0)

    def test_edge_touch_is_not_overlap(self):
        # Shares a boundary, encloses no area.
        ix = _OverlapIndex(gdf([box(10, 0, 20, 10)]))
        parcel = box(0, 0, 10, 10)
        assert ix.fraction(parcel, parcel.area) == 0.0

    def test_bounding_box_hit_with_no_geometric_overlap(self):
        """
        The failure mode unique to the indexed version: STRtree narrows by
        bounding box, so a candidate can be returned that does not actually
        intersect. If the result were taken from the tree alone rather than
        from a real intersection, this would report overlap where there is
        none — a false FAIL on the wetlands or floodway gate.
        """
        spike = Polygon([(10.001, 0), (20, 0), (20, 10)])
        assert spike.bounds[0] < 10.001 + 1e-9
        ix = _OverlapIndex(gdf([spike]))
        parcel = box(0, 0, 10, 10)
        assert ix.fraction(parcel, parcel.area) == 0.0

    def test_result_is_capped_at_one_hundred(self):
        # Guards against a parcel area smaller than its own intersection
        # through CRS or precision noise.
        ix = _OverlapIndex(gdf([box(-100, -100, 100, 100)]))
        assert ix.fraction(box(0, 0, 10, 10), 1.0) == 100.0

    def test_none_and_empty_geometries_in_the_layer_are_skipped(self):
        parts = [box(0, 0, 10, 10), Polygon()]
        ix = _OverlapIndex(gpd.GeoDataFrame(geometry=parts, crs=CRS))
        parcel = box(0, 0, 10, 10)
        assert ix.fraction(parcel, parcel.area) == pytest.approx(100.0)


def test_single_candidate_path_agrees_with_multi_candidate_path():
    # The implementation skips the union when there is exactly one
    # candidate; that shortcut must not change the answer.
    one = _OverlapIndex(gdf([box(0, 0, 5, 10)]))
    two = _OverlapIndex(gdf([box(0, 0, 5, 10), box(0, 0, 2, 10)]))
    parcel = box(0, 0, 10, 10)
    assert one.fraction(parcel, parcel.area) == pytest.approx(
        two.fraction(parcel, parcel.area)
    )
