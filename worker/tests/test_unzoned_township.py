"""
An Ohio township may adopt zoning (ORC 519) and many never have. Where a
county's planning commission records that a township adopted none, nothing
zones that land — a decidable answer rather than an absence of one.

Fairfield County RPC: "Clear Creek and Madison Township do not have zoning in
effect at this time." That is 509 of Fairfield's 3,541 parcels.

PASS is the permissive direction, so the scoping is what these tests are
mostly about: a township's silence cannot speak for a parcel inside a village
that adopted its own zoning, and an MCD that is not a functioning township
cannot speak at all.
"""

import geopandas as gpd
from shapely.geometry import box

from parcel_gates import qualify_parcels

PARCEL = box(-82.60, 39.70, -82.59, 39.71)
ELSEWHERE = box(-82.40, 39.50, -82.39, 39.51)


def _rules(unzoned):
    return {"zoning_dc_use": {"rule_version": "2026-rpc-reviewed",
                              "params": {"by_right": [], "special_exception": [],
                                         "prohibited": [],
                                         "unzoned_townships": unzoned}}}


def _parcels():
    return gpd.GeoDataFrame(
        [{"pin": "P1", "legal_acreage": 60.0, "geometry": PARCEL}],
        crs="EPSG:4326")


def _subdivisions(name, lsad="44", funcstat="A", geom=PARCEL):
    """lsad 44 / funcstat A is a functioning Ohio township."""
    return gpd.GeoDataFrame(
        [{"sub_geoid": "3900112345", "sub_name": name, "sub_lsad": lsad,
          "sub_funcstat": funcstat, "geometry": geom}],
        crs="EPSG:4326")


def _places(geom=ELSEWHERE):
    return gpd.GeoDataFrame(
        [{"place_geoid": "3912345", "place_name": "Somewhere Village",
          "place_basename": "Somewhere", "geometry": geom}],
        crs="EPSG:4326")


def _gate(rules, subdivisions, places):
    _, _, gates, _ = qualify_parcels(
        parcels_gdf=_parcels(), zoning_gdf=None, wetlands_gdf=None,
        nfhl_gdf=None, lines_gdf=None, subs_gdf=None, rules=rules,
        state_code="OH", county_name="Fairfield County, OH", snapshots={},
        retrieve_time="2026-09-15T00:00:00Z", region_key="OH-FAIRFIELD",
        subdivisions_gdf=subdivisions, places_gdf=places)
    return next(g for g in gates if g["gate_key"] == "zoning_dc_use")


def test_an_unzoned_township_passes_and_says_why():
    g = _gate(_rules(["Clearcreek township"]),
              _subdivisions("Clearcreek township"), _places())
    assert g["status"] == "PASS"
    assert "adopted no zoning resolution" in g["rationale"]
    assert "ORC Chapter 519" in g["rationale"]
    assert g["details"]["zoning_grade"] == "unzoned"
    assert g["details"]["township"] == "Clearcreek township"


def test_the_rationale_does_not_claim_a_district_permits_the_use():
    """PASS here means 'nothing restricts it', not 'a district allows it'."""
    g = _gate(_rules(["Clearcreek township"]),
              _subdivisions("Clearcreek township"), _places())
    assert "permitted use" not in g["rationale"]
    assert "by-right" not in g["rationale"]
    assert "absence of a restriction" in g["rationale"]


def test_a_township_not_on_the_list_stays_screening_grade():
    """Berne has zoning we have not read. Silence is not a pass."""
    g = _gate(_rules(["Clearcreek township"]),
              _subdivisions("Berne township"), _places())
    assert g["status"] == "UNKNOWN"
    assert g["details"]["zoning_grade"] == "screening"


def test_a_parcel_inside_a_village_does_not_take_the_townships_silence():
    """
    A township's instruments stop at municipal limits. The village may have
    adopted its own zoning, and the township saying nothing cannot answer for
    it — the same scoping the moratorium gate uses.
    """
    g = _gate(_rules(["Clearcreek township"]),
              _subdivisions("Clearcreek township"),
              _places(geom=PARCEL))          # the place covers the parcel
    assert g["status"] != "PASS"
    assert g["status"] == "UNKNOWN"


def test_without_the_places_layer_it_will_not_assume_unincorporated():
    """PASS is the permissive direction; it must not fire on an assumption."""
    g = _gate(_rules(["Clearcreek township"]),
              _subdivisions("Clearcreek township"), None)
    assert g["status"] == "UNKNOWN"


def test_a_non_functioning_mcd_is_not_a_township():
    """
    A Virginia election district and a Texas CCD are MCDs too. Only a
    functioning township can have adopted, or not adopted, a resolution.
    """
    g = _gate(_rules(["Clearcreek township"]),
              _subdivisions("Clearcreek township", funcstat="N"), _places())
    assert g["status"] == "UNKNOWN"


def test_an_empty_list_changes_nothing():
    g = _gate(_rules([]), _subdivisions("Clearcreek township"), _places())
    assert g["status"] == "UNKNOWN"
    assert g["details"]["zoning_grade"] == "screening"
