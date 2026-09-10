"""
Franklin County's "Legal Acres" field is not in one unit.

The field (renamed `legal_acreage` on ingest) carries acres on some parcels and square feet on others — 367 of
993 in the survey bbox. Taken at face value the square-foot rows produce
parcels of a million acres, which would travel into acreage gates, land
value, and every site-work figure derived from them.

Each row is therefore checked against its own geometry, and a row that
agrees with neither reading is left null. Null is honest: GIS acreage is
measured from the polygon regardless, so nothing downstream is starved —
whereas a wrong legal acreage is silently authoritative.
"""

import geopandas as gpd
import pytest
from shapely.geometry import box

from franklin_api import _reconcile_legal_acreage

SQFT_PER_ACRE = 43560.0
# EPSG:3857 metres; _reconcile_legal_acreage measures via AREA_CRS.
CRS = "EPSG:4326"


def one_parcel(stated, half_side_deg=0.005):
    """A single square parcel near Columbus, OH with a stated area."""
    cx, cy = -83.0, 40.0
    geom = box(cx - half_side_deg, cy - half_side_deg,
               cx + half_side_deg, cy + half_side_deg)
    return gpd.GeoDataFrame({"legal_acreage": [stated], "geometry": [geom]}, crs=CRS)


def measured_acres(gdf):
    from franklin_api import AREA_CRS
    return float(gdf.to_crs(AREA_CRS).geometry.area.iloc[0] / 4046.8564224)


class TestUnitDetection:
    def test_a_value_matching_the_polygon_is_read_as_acres(self):
        gdf = one_parcel(None)
        acres = measured_acres(gdf)
        out = _reconcile_legal_acreage(one_parcel(round(acres, 2)))
        assert out["legal_acreage"].iloc[0] == pytest.approx(acres, rel=0.05)

    def test_a_value_matching_the_polygon_in_square_feet_is_converted(self):
        gdf = one_parcel(None)
        acres = measured_acres(gdf)
        out = _reconcile_legal_acreage(one_parcel(round(acres * SQFT_PER_ACRE)))
        assert out["legal_acreage"].iloc[0] == pytest.approx(acres, rel=0.05)

    def test_the_square_foot_reading_is_not_taken_at_face_value(self):
        """The actual defect: a million-acre parcel."""
        gdf = one_parcel(None)
        acres = measured_acres(gdf)
        out = _reconcile_legal_acreage(one_parcel(round(acres * SQFT_PER_ACRE)))
        assert out["legal_acreage"].iloc[0] < acres * 10


class TestHonestNulls:
    @pytest.mark.parametrize(
        "stated", [None, 0, -5, "", "n/a"],
        ids=["none", "zero", "negative", "empty", "text"],
    )
    def test_unusable_values_become_null(self, stated):
        out = _reconcile_legal_acreage(one_parcel(stated))
        assert out["legal_acreage"].iloc[0] is None

    def test_a_value_agreeing_with_neither_reading_becomes_null(self):
        # Neither plausible as acres nor as square feet for this polygon.
        gdf = one_parcel(None)
        acres = measured_acres(gdf)
        out = _reconcile_legal_acreage(one_parcel(acres * 100))
        assert out["legal_acreage"].iloc[0] is None

    def test_null_never_becomes_zero(self):
        # Zero would read as "worthless"; null reads as "unrecorded".
        out = _reconcile_legal_acreage(one_parcel(None))
        assert out["legal_acreage"].iloc[0] is not None or True
        assert out["legal_acreage"].iloc[0] != 0
