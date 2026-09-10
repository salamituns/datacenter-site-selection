"""
The Licking County adapter, tested offline against the probe's findings.

What is tested is the contract the engine relies on, not the county's
server: identity filtering and the duplicate-id guard, incentive reading
from the inline roll fields, the ArcGIS epoch date conversion, and the
zoning layer concatenation that turns 25 per-township layers into one
frame with the columns the gate engine overlays against.
"""

import geopandas as gpd
import pytest
from shapely.geometry import box

from licking_api import LickingParcelAPI, _epoch_ms_to_iso

CRS = "EPSG:4326"
BBOX = "-82.45,39.93,-82.35,40.02"


def _props(**kw):
    base = {
        "Parcel": "001-000006-00.000",
        "TaxAcres": 100.0,
        "Class": "Agricultural",
        "Township": "Bowling Green",
        "MarketLandValue": 500000,
        "MarketImpValue": 0,
        "MarketTotalValue": 500000,
        "CAUVAcres": 0.0,
        "CAUVLandValue": 0,
        "AbatedImpValue": 0,
        "TIF": "No",
        "T1SaleAmount": None,
        "T1Date": None,
    }
    base.update(kw)
    return base


def _feature(props):
    return {
        "properties": props,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-82.44, 39.95], [-82.44, 39.96],
                             [-82.43, 39.96], [-82.43, 39.95],
                             [-82.44, 39.95]]],
        },
    }


class TestIdentity:
    def test_null_parcel_rows_are_dropped(self, monkeypatch):
        api = LickingParcelAPI()
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [_feature(_props(Parcel=None, TaxAcres=50))])
        gdf = api.fetch_parcels(BBOX, 20.0)
        assert gdf is None  # nothing survived the null-Parcel filter

    def test_duplicate_ids_keep_the_first_and_are_counted(self, monkeypatch, caplog):
        api = LickingParcelAPI()
        # 200 stated acres against the ~230-acre test polygon, so the
        # per-row acreage reconciliation keeps the value rather than
        # nulling a row that agrees with neither reading.
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [
                _feature(_props(Parcel="001-000006-00.000", TaxAcres=200)),
                _feature(_props(Parcel="001-000006-00.000", TaxAcres=400)),
            ])
        with caplog.at_level("WARNING"):
            gdf = api.fetch_parcels(BBOX, 20.0)
        assert len(gdf) == 1
        assert float(gdf["legal_acreage"].iloc[0]) == 200.0
        assert "duplicate Parcel ids" in caplog.text


class TestCauvAndIncentives:
    def test_cauv_enrollment_reads_the_explicit_columns(self, monkeypatch):
        api = LickingParcelAPI()
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [
                _feature(_props(Parcel="A", CAUVAcres=145.39, CAUVLandValue=225330)),
                _feature(_props(Parcel="B", CAUVAcres=0.0, CAUVLandValue=0)),
                _feature(_props(Parcel="C", CAUVAcres=0.0, CAUVLandValue=30720)),
            ])
        gdf = api.fetch_parcels(BBOX, 20.0)
        assert list(gdf["in_cauv"]) == [True, False, True]

    def test_incentives_come_from_the_roll_not_a_companion_layer(self, monkeypatch):
        api = LickingParcelAPI()
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [
                _feature(_props(Parcel="A", AbatedImpValue=1538000, TIF="No")),
                _feature(_props(Parcel="B", AbatedImpValue=0,
                                TIF="Etna Twp JEDD2 - Southgate")),
                _feature(_props(Parcel="C", AbatedImpValue=0, TIF="No")),
                _feature(_props(Parcel="D", AbatedImpValue=0, TIF=None)),
            ])
        parcels = api.fetch_parcels(BBOX, 20.0)
        inc = api.parcel_incentives(-82.45, 39.93, -82.35, 40.02, parcels)
        assert set(inc) == {"A", "B"}
        assert inc["A"]["abatement"]["abated_improvement_value"] == 1538000.0
        assert "tif" not in inc["A"]
        assert inc["B"]["tif"]["name"] == "Etna Twp JEDD2 - Southgate"
        assert "abatement" not in inc["B"]

    def test_incentives_without_parcels_is_empty(self):
        assert LickingParcelAPI().parcel_incentives(-1, -1, 1, 1, None) == {}


class TestZoningConcatenation:
    def test_township_layers_become_one_frame_with_gate_columns(self, monkeypatch):
        api = LickingParcelAPI()
        monkeypatch.setattr(api, "_zoning_layer_ids",
                            lambda: [(0, "Bennington"), (8, "Hanover (Unzoned)")])
        by_layer = {
            "0": [{"properties": {"ZoningClass": "M-1",
                                  "ZoningDescription": "Light Manufacturing",
                                  "ZoningOverlay": "N", "Township": "Bennington",
                                  "Resolution": "2021-38", "URL": None},
                   "geometry": _feature({})["geometry"]}],
            "8": [{"properties": {"ZoningClass": "UZ", "ZoningDescription": "Unzoned",
                                  "ZoningOverlay": None, "Township": "Hanover",
                                  "Resolution": None, "URL": None},
                   "geometry": _feature({})["geometry"]}],
        }
        monkeypatch.setattr(
            api, "_paged",
            lambda url, bbox, fields, where="1=1": by_layer[url.split("/")[-2]])
        z = api.fetch_zoning(BBOX)
        assert list(z.columns[:3]) == ["zone", "zone_name", "ordinance"]
        assert list(z["zone"]) == ["M-1", "UZ"]
        assert "Bennington Township Zoning Resolution (2021-38)" in list(z["ordinance"])
        assert "Hanover Township Zoning Resolution" in list(z["ordinance"])

    def test_unavailable_service_is_none_not_an_empty_frame(self, monkeypatch):
        api = LickingParcelAPI()
        monkeypatch.setattr(api, "_zoning_layer_ids", lambda: None)
        assert api.fetch_zoning(BBOX) is None

    def test_no_layer_features_is_none(self, monkeypatch):
        api = LickingParcelAPI()
        monkeypatch.setattr(api, "_zoning_layer_ids", lambda: [(0, "Bennington")])
        monkeypatch.setattr(api, "_paged", lambda *a, **k: [])
        assert api.fetch_zoning(BBOX) is None


class TestArcGisDates:
    def test_epoch_milliseconds_become_iso_dates(self):
        assert _epoch_ms_to_iso(1757462400000) == "2025-09-10"

    def test_unusable_values_become_none(self):
        for v in (None, "", "n/a", float("nan"), 10 ** 30):
            assert _epoch_ms_to_iso(v) is None


class TestLayerSources:
    def test_zoning_is_a_real_source_wetlands_and_nfhl_stay_national(self):
        src = LickingParcelAPI().layer_sources()
        assert src["parcels"]["source_key"] == "licking_tax_parcels"
        assert src["zoning"]["source_key"] == "licking_township_zoning"
        assert src["wetlands"]["source_key"] == "nwi_wetlands"
        assert src["nfhl"]["source_key"] is None
