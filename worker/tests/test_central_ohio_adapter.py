"""
The regional adapter's own hazards. Offline.

The acreage one is the load-bearing test: ACRES is populated for Fairfield
and empty for Delaware and Union, so an adapter that read only ACRES would
return nothing for two of the three counties and look like an outage rather
than a field choice.
"""

import geopandas as gpd
import pytest
from shapely.geometry import box

from central_ohio_api import CentralOhioParcelAPI


def test_acres_is_preferred_and_statedarea_is_the_fallback():
    a = CentralOhioParcelAPI._acres
    assert a({"ACRES": 40.0, "STATEDAREA": 39.5}) == (40.0, "ACRES")
    assert a({"ACRES": None, "STATEDAREA": 39.5}) == (39.5, "STATEDAREA")
    assert a({"STATEDAREA": 39.5}) == (39.5, "STATEDAREA")


def test_zero_acreage_concedes_rather_than_failing_the_gate():
    """
    Zero acres FAILS the contiguous-acreage gate; an unstated acreage must
    CONCEDE it. A source that writes 0 for "not recorded" makes those the
    same number, and they are not the same fact.
    """
    a = CentralOhioParcelAPI._acres
    assert a({"ACRES": 0, "STATEDAREA": 0}) == (None, None)
    assert a({"ACRES": 0, "STATEDAREA": 55.0}) == (55.0, "STATEDAREA")
    assert a({}) == (None, None)
    assert a({"ACRES": "", "STATEDAREA": None}) == (None, None)


def test_only_the_three_measured_counties_are_served():
    for rk in ("OH-FAIRFIELD", "OH-UNION", "OH-DELAWARE"):
        assert CentralOhioParcelAPI(rk).county == rk.split("-")[1].title()


@pytest.mark.parametrize("rk", ["OH-MADISON", "OH-PICKAWAY"])
def test_counties_in_the_layer_without_acreage_are_refused_by_name(rk):
    """
    Madison and Pickaway are IN the regional layer but carry no acreage in
    either field. Refusing them by name beats returning zero parcels, which
    would read as an outage.
    """
    with pytest.raises(ValueError) as e:
        CentralOhioParcelAPI(rk)
    assert "Madison and Pickaway" in str(e.value)


def test_a_county_outside_the_layer_is_refused():
    with pytest.raises(ValueError):
        CentralOhioParcelAPI("OH-KNOX")


def test_zoning_is_none_by_construction():
    """
    Ohio zones by township. Returning None is what keeps qualify_parcels from
    refusing the run, and what makes the gate say there is no layer rather
    than that a map misses the parcel.
    """
    api = CentralOhioParcelAPI("OH-FAIRFIELD")
    assert api.layer_sources()["zoning"] == {"source_key": None, "endpoint": None}


def test_reconciliation_warns_when_stated_acreage_outruns_the_ground(caplog):
    """
    The check that would have caught Fauquier, where fifty interests each
    carried their parent tract's acreage: 13,493 acres claimed on 263 acres
    of land.
    """
    tract = box(-82.9, 39.9, -82.89, 39.91)
    gdf = gpd.GeoDataFrame(
        [{"legal_acreage": 500.0, "geometry": tract} for _ in range(5)],
        crs="EPSG:4326")
    with caplog.at_level("WARNING"):
        CentralOhioParcelAPI._reconcile(gdf)
    assert "Acreage reconciliation" in caplog.text
    assert "double-counting" in caplog.text


def test_reconciliation_is_quiet_when_acreage_matches_the_ground():
    gdf = gpd.GeoDataFrame(
        [{"legal_acreage": 15.9, "geometry": box(-82.9, 39.9, -82.897, 39.9023)}],
        crs="EPSG:4326")
    drawn = gdf.to_crs("EPSG:5070").geometry.area.sum() / 4046.86
    gdf["legal_acreage"] = drawn          # exact agreement
    CentralOhioParcelAPI._reconcile(gdf)  # must not raise
