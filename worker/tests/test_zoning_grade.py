"""
A county that publishes no zoning layer and a parcel that falls in a gap of
one are different facts, and for most of a year they shared a sentence.

Ohio zones by municipality and township rather than by county, so Franklin
has no county layer at all — yet all 982 of its parcels read "the
authoritative zoning map does not cover this parcel", which describes a map
with a hole in it. The details dict said zoning_layer: missing the whole
time; only the sentence a person reads was wrong.
"""

import geopandas as gpd
from shapely.geometry import box

from parcel_gates import qualify_parcels


RULES = {"zoning_dc_use": {"rule_version": "test",
                           "params": {"by_right": [], "special_exception": [],
                                      "prohibited": []}}}


def _parcels():
    return gpd.GeoDataFrame(
        [{"pin": "P1", "legal_acreage": 50.0,
          "geometry": box(-82.9, 39.9, -82.89, 39.91)}],
        crs="EPSG:4326")


def _zoning_elsewhere():
    """A real zoning layer that simply does not reach the parcel."""
    return gpd.GeoDataFrame(
        [{"zone": "RA", "zone_name": "Rural", "ordinance": "Test Resolution",
          "geometry": box(-83.5, 39.0, -83.4, 39.1)}],
        crs="EPSG:4326")


def _run(zoning):
    _, _, gates, _ = qualify_parcels(
        parcels_gdf=_parcels(), zoning_gdf=zoning, wetlands_gdf=None,
        nfhl_gdf=None, lines_gdf=None, subs_gdf=None, rules=RULES,
        state_code="OH", county_name="Test County, OH", snapshots={},
        retrieve_time="2026-09-14T00:00:00Z", region_key="OH-TEST")
    return next(g for g in gates if g["gate_key"] == "zoning_dc_use")


def test_no_layer_says_there_is_no_layer():
    g = _run(None)
    assert g["status"] == "UNKNOWN"
    assert "publishes no zoning layer" in g["rationale"]
    assert "it is the absence of one" in g["rationale"]
    assert g["details"]["zoning_layer"] == "missing"
    assert g["details"]["zoning_grade"] == "screening"


def test_no_layer_does_not_claim_a_map_that_misses_the_parcel():
    """The specific wording that misdescribed Franklin for 982 parcels."""
    g = _run(None)
    assert "does not cover this parcel" not in g["rationale"]
    assert "boundary sliver" not in g["rationale"]


def test_a_real_gap_in_a_real_map_still_reads_as_a_gap():
    g = _run(_zoning_elsewhere())
    assert g["status"] == "UNKNOWN"
    assert "covers this jurisdiction but not this parcel" in g["rationale"]
    assert g["details"]["zoning_layer"] == "present"
    assert g["details"]["zoning_grade"] == "parcel"


def test_the_two_states_are_distinguishable_by_details_alone():
    """A consumer filtering on details must not need to parse prose."""
    assert _run(None)["details"]["zoning_grade"] == "screening"
    assert _run(_zoning_elsewhere())["details"]["zoning_grade"] == "parcel"
