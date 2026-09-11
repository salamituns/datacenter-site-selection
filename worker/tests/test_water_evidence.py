"""
Water provider evidence — the normalisation contract.

Every polygon the gate sees comes through `fetch_water_service_areas`, so
the properties that matter downstream must hold no matter which utility's
service answered:

  * an absent comment is None, never "" (the no-new-connections branch
    reads that text);
  * the provider is row-level where the layer encodes the operator — a
    joint district/city layer must not attribute the city's parcels to
    the district;
  * the date always appears: a service's edit timestamp, or the layer's
    recorded vintage when it exposes none — never a silent null.

The HTTP session is faked, so these tests check the contract, not the
network. The real endpoints are exercised by the pipeline dry-run.
"""

import pytest

import water_evidence
from water_evidence import fetch_water_service_areas

BBOX = (-83.0, 39.8, -82.4, 40.1)


def _poly_geojson():
    return {"type": "Polygon", "coordinates": [[
        [-83.0, 39.8], [-82.9, 39.8], [-82.9, 39.9], [-83.0, 39.9],
        [-83.0, 39.8]]]}


def _feature(props):
    return {"type": "Feature", "properties": props,
            "geometry": _poly_geojson()}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    """Replays a queue of payloads, recording the params of each call."""

    responses = []  # set per-test before the factory is used
    calls = []

    def __init__(self):
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        _FakeSession.calls.append({"url": url, "params": params})
        payload = _FakeSession.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return _FakeResponse(payload)


@pytest.fixture()
def fake_http(monkeypatch):
    _FakeSession.responses = []
    _FakeSession.calls = []
    monkeypatch.setattr(water_evidence.requests, "Session", _FakeSession)
    return _FakeSession


class TestLoudounNormalization:
    def test_fields_map_and_empty_comment_is_none(self, fake_http):
        fake_http.responses = [{
            "features": [
                _feature({"AreaName": "Central System",
                          "ServiceType": "Both",
                          "Comment": "",
                          "last_edited_date": 1730515200000}),
                _feature({"AreaName": "NOT Served by LW",
                          "ServiceType": "W",
                          "Comment": None,
                          "last_edited_date": 1730515200000}),
            ],
        }]
        gdf = fetch_water_service_areas("VA-LOUDOUN", *BBOX)
        assert len(gdf) == 2
        central = gdf[gdf.area_name == "Central System"].iloc[0]
        assert central["comment"] is None, "empty string must normalise to None"
        assert central["provider"] == "Loudoun Water"
        assert central["service_type"] == "Both"
        assert central["last_edited"] == "2024-11-02"
        assert central["edited_basis"] == "service_edit_timestamp"
        assert central["edited_note"] is None
        assert not central["not_served"]
        ns = gdf[gdf.area_name == "NOT Served by LW"].iloc[0]
        assert bool(ns["not_served"]) is True

    def test_paging_follows_exceeded_transfer_limit(self, fake_http):
        page = {"features": [_feature({"AreaName": f"A{i}",
                                       "ServiceType": "W",
                                       "Comment": None,
                                       "last_edited_date": 1730515200000})
                             for i in range(100)],
                "exceededTransferLimit": True}
        tail = {"features": [_feature({"AreaName": "A100",
                                       "ServiceType": "W",
                                       "Comment": None,
                                       "last_edited_date": 1730515200000})]}
        fake_http.responses = [page, tail]
        gdf = fetch_water_service_areas("VA-LOUDOUN", *BBOX)
        assert len(gdf) == 101
        assert [c["params"]["resultOffset"] for c in fake_http.calls] == [0, 100]


class TestLickingNormalization:
    @staticmethod
    def _pages():
        # Water layer (Name only), then wastewater layer (Name only).
        return [
            {"features": [
                _feature({"Name": "SWLCWSD"}),
                _feature({"Name": "Pataskala Utility Department"}),
            ]},
            {"features": [
                _feature({"Name": "Joint"}),
            ]},
        ]

    def test_provider_is_row_level_and_dated_by_vintage(self, fake_http):
        fake_http.responses = self._pages()
        gdf = fetch_water_service_areas("OH-LICKING", *BBOX)
        assert len(gdf) == 3
        swl = gdf[gdf.area_name == "SWLCWSD"].iloc[0]
        pat = gdf[gdf.area_name == "Pataskala Utility Department"].iloc[0]
        joint = gdf[gdf.area_name == "Joint"].iloc[0]
        # Row-level attribution: the district's layer, the city's polygon.
        assert swl["provider"] == "Licking Regional Water District (formerly SWLCWSD)"
        assert pat["provider"] == "Pataskala Utility Department"
        assert "joint" in joint["provider"].lower()
        # The layer encodes no service-type column; each layer's constant.
        assert swl["service_type"] == "W"
        assert joint["service_type"] == "WW"
        # No edit timestamp exists — the vintage is stated, never null.
        for row in (swl, pat, joint):
            assert row["last_edited"] == "2021-06"
            assert row["edited_basis"] == "layer_vintage"
            assert "Water_Service_2021" in row["edited_note"] or \
                "no edit timestamp" in row["edited_note"]
            assert row["comment"] is None
            assert not row["not_served"]

    def test_both_layer_endpoints_are_queried(self, fake_http):
        fake_http.responses = self._pages()
        fetch_water_service_areas("OH-LICKING", *BBOX)
        urls = [c["url"] for c in fake_http.calls]
        assert any("Water_Service_2021_view" in u for u in urls)
        assert any("Waste_Water_Service_2021" in u for u in urls)


class TestAvailability:
    def test_unconfigured_region_returns_none_without_network(self, fake_http):
        # Prince William has no entry yet — UNKNOWN, and no endpoint is
        # invented to fill the gap.
        assert fetch_water_service_areas("VA-PRINCEWILLIAM", *BBOX) is None
        assert fake_http.calls == []

    def test_failed_layer_returns_none_not_empty(self, fake_http):
        # A fetch error on either layer must read as unavailable (the
        # gate records UNKNOWN), never as an empty in-bbox boundary.
        fake_http.responses = [RuntimeError("boom")]
        assert fetch_water_service_areas("OH-LICKING", *BBOX) is None

    def test_empty_bbox_returns_none(self, fake_http):
        fake_http.responses = [{"features": []}]
        assert fetch_water_service_areas("VA-LOUDOUN", *BBOX) is None
