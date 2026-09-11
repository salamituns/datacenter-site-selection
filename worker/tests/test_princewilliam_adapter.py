"""
The Prince William County adapter, tested offline against the probe's
findings.

What is tested is the contract the engine relies on, not the county's
server: the placeholder-GPIN filter and the duplicate guard, the
deed-acreage fallback, the refusal to read assessment values the layer
does not carry, and the zoning layer's ordinance-sourced names — which
must never come from the rezoning case name the layer publishes.
"""

import geopandas as gpd
import pytest
from shapely.geometry import box

from princewilliam_api import (
    DISTRICT_NAMES,
    ORDINANCE,
    PrinceWilliamParcelAPI,
)

CRS = "EPSG:4326"
BBOX = "-77.60,38.75,-77.50,38.85"


def _props(**kw):
    base = {
        "GPIN": "7302-03-9126",
        "TaxMapNumber": "166-01-000-0002A",
        "ParcelRecordationStatus": "Active",
        "Acreage": 58.367,
        "CAMA_DeedAcre": 58.367,
        "CAMA_TaxAcreage1": 58.367,
        "CAMA_USECODE": "911",
        "CAMA_SQFTABV": 0,
    }
    base.update(kw)
    return base


def _feature(props):
    return {
        "properties": props,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-77.59, 38.78], [-77.59, 38.79],
                             [-77.58, 38.79], [-77.58, 38.78],
                             [-77.59, 38.78]]],
        },
    }


class TestIdentity:
    def test_placeholder_gpin_is_filtered_at_query_time_and_in_row(self, monkeypatch):
        api = PrinceWilliamParcelAPI()
        seen = {}

        def fake_paged(url, bbox, fields, where="1=1"):
            seen["where"] = where
            return [_feature(_props()),
                    _feature(_props(GPIN="9999-99-9999", Acreage=999.0))]

        monkeypatch.setattr(api, "_paged", fake_paged)
        gdf = api.fetch_parcels(BBOX, 20.0)
        assert len(gdf) == 1
        assert api.PLACEHOLDER_GPIN in seen["where"]
        assert "9999-99-9999" not in list(gdf["pin"])

    def test_non_gpin_shape_is_skipped_loudly(self, monkeypatch, caplog):
        api = PrinceWilliamParcelAPI()
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [
                _feature(_props(GPIN="116-01 ROW")),
                _feature(_props()),
            ])
        with caplog.at_level("INFO"):
            gdf = api.fetch_parcels(BBOX, 20.0)
        assert len(gdf) == 1
        assert "skipped 1 non-GPIN" in caplog.text

    def test_duplicate_gpins_keep_the_first_and_warn(self, monkeypatch, caplog):
        api = PrinceWilliamParcelAPI()
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [
                _feature(_props(CAMA_DeedAcre=200, Acreage=200)),
                _feature(_props(CAMA_DeedAcre=400, Acreage=400)),
            ])
        with caplog.at_level("WARNING"):
            gdf = api.fetch_parcels(BBOX, 20.0)
        assert len(gdf) == 1
        assert "duplicate GPIN" in caplog.text

    def test_no_features_is_none_not_an_empty_frame(self, monkeypatch):
        api = PrinceWilliamParcelAPI()
        monkeypatch.setattr(api, "_paged", lambda *a, **k: [])
        assert api.fetch_parcels(BBOX, 20.0) is None


class TestAcreage:
    def test_deed_acreage_is_preferred(self, monkeypatch):
        api = PrinceWilliamParcelAPI()
        # The 0.01-degree test polygon measures ~238 acres; a stated 200
        # sits inside the reconciliation band, 61 does not.
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [
                _feature(_props(CAMA_DeedAcre=200.0, Acreage=61.0)),
            ])
        gdf = api.fetch_parcels(BBOX, 20.0)
        assert float(gdf["legal_acreage"].iloc[0]) == 200.0

    def test_plain_acreage_is_the_fallback_when_deed_is_null(self, monkeypatch):
        api = PrinceWilliamParcelAPI()
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [
                _feature(_props(CAMA_DeedAcre=None, Acreage=200.0)),
            ])
        gdf = api.fetch_parcels(BBOX, 20.0)
        assert float(gdf["legal_acreage"].iloc[0]) == 200.0


class TestAssessmentHonesty:
    def test_no_value_columns_are_read_or_invented(self, monkeypatch):
        """The layer carries no assessed values and none may appear.

        The probe's finding: the CAMA join publishes owner, deed acreage,
        use code — deliberately not values. A land_value column here
        would be a fabricated roll, and the underwriting block would
        price from it.
        """
        api = PrinceWilliamParcelAPI()
        monkeypatch.setattr(api, "_paged", lambda *a, **k: [_feature(_props())])
        gdf = api.fetch_parcels(BBOX, 20.0)
        for col in ("land_value", "building_value", "total_value",
                    "cauv_land_value", "in_cauv"):
            assert col not in gdf.columns
        assert gdf["assessment_class"].iloc[0] == "911"

    def test_use_code_missing_is_none_not_nan(self, monkeypatch):
        api = PrinceWilliamParcelAPI()
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [_feature(_props(CAMA_USECODE=None))])
        gdf = api.fetch_parcels(BBOX, 20.0)
        assert gdf["assessment_class"].iloc[0] is None


class TestZoning:
    def _zoning_feature(self, district, case="REZ2024-00024",
                        case_name="13000 Sport and Health Drive"):
        return {
            "properties": {"ZoningDistrict": district,
                           "ZoningCaseName": case_name,
                           "ZoningCaseNumber": case,
                           "last_edited_date": 1760452823000},
            "geometry": _feature({})["geometry"],
        }

    def test_district_names_come_from_the_ordinance_not_the_case(self, monkeypatch):
        api = PrinceWilliamParcelAPI()
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [self._zoning_feature("M-1"),
                             self._zoning_feature("PMR")])
        z = api.fetch_zoning(BBOX)
        assert list(z.columns[:3]) == ["zone", "zone_name", "ordinance"]
        assert z["zone_name"].iloc[0] == "Heavy Industrial"
        assert z["zone_name"].iloc[1] == "Planned Mixed Residential"
        # The case name is a detail, never the district name.
        assert "Sport and Health" not in " ".join(z["zone_name"])
        assert z["case_name"].iloc[0] == "13000 Sport and Health Drive"
        assert ORDINANCE in list(z["ordinance"])[0]

    def test_unknown_code_keeps_the_code_as_its_name(self, monkeypatch, caplog):
        api = PrinceWilliamParcelAPI()
        monkeypatch.setattr(
            api, "_paged",
            lambda *a, **k: [self._zoning_feature("TWN")])
        with caplog.at_level("INFO"):
            z = api.fetch_zoning(BBOX)
        assert z["zone_name"].iloc[0] == "TWN"
        assert "without an ordinance name" in caplog.text

    def test_ordinance_names_cover_the_industrial_and_agricultural_codes(self):
        # The districts a data-center screening turns on first.
        for code in ("A-1", "M-1", "M-2", "M/T", "PMR", "PMD", "PBD", "B-1"):
            assert DISTRICT_NAMES[code], code

    def test_no_features_is_none(self, monkeypatch):
        api = PrinceWilliamParcelAPI()
        monkeypatch.setattr(api, "_paged", lambda *a, **k: [])
        assert api.fetch_zoning(BBOX) is None


class TestLayerSources:
    def test_parcels_and_zoning_are_real_sources_wetlands_stays_national(self):
        src = PrinceWilliamParcelAPI().layer_sources()
        assert src["parcels"]["source_key"] == "pwc_tax_parcels"
        assert src["zoning"]["source_key"] == "pwc_zoning_districts"
        assert src["wetlands"]["source_key"] == "nwi_wetlands"
        assert src["nfhl"]["source_key"] is None
