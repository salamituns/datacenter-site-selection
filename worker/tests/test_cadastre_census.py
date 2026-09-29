"""
The census's two judgement calls, kept honest: what counts as a relevant
search hit, and which layers of a service are worth recording. A search
index is public and fuzzy — anyone can publish anything — so the filter
is the difference between a queue of county parcel services and a queue
of noise. The regression that must not happen: a nationwide commercial
layer or a neighbouring county's service scoring as a hit for a county
it does not cover.
"""

import cadastre_census


def _hit(title, owner="someone", type_="Feature Service", tags=None):
    return {"title": title, "owner": owner, "type": type_,
            "tags": tags or [], "id": "abc123"}


def test_service_types_only():
    # a Web Map named "Parcels" is a view of a layer, not a layer
    assert cadastre_census.score_candidate(
        _hit("Adams County Parcels", type_="Web Map"),
        "Adams", "Indiana") is None


def test_parcel_word_required():
    assert cadastre_census.score_candidate(
        _hit("Adams County Land Records"), "Adams", "Indiana") is None


def test_tags_can_carry_the_parcel_word():
    hit = _hit("Adams County CAMA", tags=["parcels", "cadastral"])
    assert cadastre_census.score_candidate(hit, "Adams", "Indiana") is not None


def test_county_identity_required():
    # the nationwide commercial layer — must never score for one county
    assert cadastre_census.score_candidate(
        _hit("Regrid USA Nationwide Parcel Boundaries", owner="data_regrid"),
        "Adams", "Indiana") is None
    # a neighbouring county's service, same state
    assert cadastre_census.score_candidate(
        _hit("Allen County Parcels", owner="allengis"),
        "Adams", "Indiana") is None


def test_title_beats_owner_beats_state():
    title_hit = cadastre_census.score_candidate(
        _hit("Adams County Parcels"), "Adams", "Indiana")
    owner_hit = cadastre_census.score_candidate(
        _hit("Tax Parcels", owner="adamscountygis"), "Adams", "Indiana")
    assert title_hit is not None and owner_hit is not None
    assert title_hit > owner_hit


def test_choose_layers_prefers_named_polygons():
    svc = {"layers": [
        {"id": 0, "name": "Street Centerlines",
         "geometryType": "esriGeometryPolyline"},
        {"id": 1, "name": "Tax Parcels", "geometryType": "esriGeometryPolygon"},
        {"id": 2, "name": "Vacant Land", "geometryType": "esriGeometryPolygon"},
        {"id": 3, "name": "Subdivisions", "geometryType": "esriGeometryPolygon"},
    ]}
    chosen = cadastre_census.choose_layers(svc)
    assert [l["id"] for l in chosen] == [1, 2]  # named first, cap at two


def test_choose_layers_empty_when_no_polygons():
    svc = {"layers": [{"id": 0, "name": "Parcels",
                       "geometryType": "esriGeometryPolyline"}]}
    assert cadastre_census.choose_layers(svc) == []


def test_sentinel_row_is_distinct_per_region():
    # the none_found sentinel must not collide with a real source row,
    # and must itself be idempotent on re-run
    row = cadastre_census._row("IN-ADAMS", "IN", "Adams", "county_search",
                               "(no public parcel service found)", "(search)",
                               None, cadastre_census.SENTINEL_SERVICE_URL,
                               cadastre_census.SENTINEL_LAYER_ID,
                               evidence="none_found")
    assert row["evidence_class"] == "none_found"
    assert row["service_url"] == "(none)" and row["layer_id"] == -1


# ── the second pass: web maps → self-hosted services ─────────────────────
#
# Cases below are layers seen in real web maps on 2026-09-28, while the
# technique was being probed against Loudoun, Licking, Fayette KY and WV.

def test_self_hosted_is_anything_but_agol_hosting():
    assert cadastre_census.is_self_hosted(
        "https://logis.loudoun.gov/gis/rest/services/COL/LandRecords/MapServer/5")
    assert cadastre_census.is_self_hosted(
        "https://maps.lexingtonky.gov/lfucggis/rest/services/parcels/MapServer/0")
    # a student's re-upload of Licking's parcels — the first pass's
    # territory, and not the county's own publication
    assert not cadastre_census.is_self_hosted(
        "https://services8.arcgis.com/EtYD1cRq8Hkljjf7/arcgis/rest/services/"
        "Licking_County_WFL1/FeatureServer/4")
    assert not cadastre_census.is_self_hosted(
        "https://tiles.arcgis.com/tiles/abc/arcgis/rest/services/x/MapServer")
    assert not cadastre_census.is_self_hosted("")


def test_parcel_layers_by_title_or_path():
    yes = cadastre_census.is_parcel_layer
    assert yes("Parcel Boundaries",
               "https://logis.loudoun.gov/gis/rest/services/COL/LandRecords/MapServer/5")
    # the title says nothing, the path does
    assert yes("parcels - Parcel",
               "https://maps.lexingtonky.gov/lfucggis/rest/services/parcels/MapServer/0")
    assert yes("Layer 3",
               "https://gis.example.gov/arcgis/rest/services/TaxParcels/MapServer/0")


def test_not_parcel_layers():
    no = lambda t, u: not cadastre_census.is_parcel_layer(t, u)
    # the false positive the probe hit: a survey grid, not ownership
    assert no("BLM Public Land Survey System (PLSS)",
              "https://gis.blm.gov/arcgis/rest/services/Cadastral/"
              "BLM_Natl_PLSS_CadNSDI/MapServer")
    assert no("Zoning Districts",
              "https://gis.example.gov/arcgis/rest/services/Zoning/MapServer/2")
    assert no("Tax Districts",
              "https://gis.example.gov/arcgis/rest/services/Boundaries/MapServer/1")


def test_web_map_layers_walk_groups_and_skip_hosted():
    web_map = {"operationalLayers": [
        {"title": "Roads", "url": "https://gis.example.gov/rest/services/Roads/MapServer/0"},
        {"title": "Land Records", "layerType": "GroupLayer", "layers": [
            {"title": "Parcels",
             "url": "https://gis.example.gov/rest/services/LandRecords/MapServer/5"},
        ]},
        {"title": "Parcels (copy)",
         "url": "https://services8.arcgis.com/x/arcgis/rest/services/P/FeatureServer/0"},
    ]}
    assert cadastre_census.web_map_layer_urls(web_map) == [
        ("Parcels", "https://gis.example.gov/rest/services/LandRecords/MapServer/5")]


def test_normalised_url_merges_case_variants():
    n = cadastre_census._normalise_layer_url
    assert (n("https://LOGIS.loudoun.gov/gis/rest/services/COL/LandRecords/MapServer/5/")
            == n("https://logis.loudoun.gov/gis/rest/services/COL/LandRecords/MapServer/5"))


class _FakeSession:
    """Answers the second pass's requests from a dict of URL → JSON."""

    def __init__(self, answers):
        self.answers = answers

    def get_json(self, url, params=None):
        return self.answers.get(url)


def test_web_map_sentinel_even_when_state_program_verifies(monkeypatch):
    # WV's statewide layer verifies, the county's web maps find nothing:
    # the region still needs its web_map row, or every re-run redoes it
    wv_url = cadastre_census.SELF_HOSTED_STATE_PROGRAMS["WV"][0]
    session = _FakeSession({
        wv_url: {"name": "WVParcels", "geometryType": "esriGeometryPolygon",
                 "maxRecordCount": 2000},
        wv_url + "/query": {"count": 77667},
        cadastre_census.AGOL_SEARCH_URL: {"results": []},
    })
    rows = cadastre_census.census_region_web_maps(
        session, "WV-BERKELEY", "Berkeley County", "WV",
        (-78.23, 39.28, -77.82, 39.60))
    by_via = {r["discovered_via"]: r for r in rows}
    assert by_via["state_program"]["evidence_class"] == "verified"
    assert by_via["state_program"]["record_count"] == 77667
    assert by_via["web_map"]["evidence_class"] == "none_found"
    assert by_via["web_map"]["service_url"] == cadastre_census.WEB_MAP_SENTINEL_URL


# ── outline coverage ──────────────────────────────────────────────────────

def test_coverage_points_fall_inside_the_inset_outline():
    import geopandas as gpd
    from shapely.geometry import Point, box
    county = box(-78.2, 39.3, -77.8, 39.6)
    pts = cadastre_census.coverage_points(county)
    assert len(pts) == cadastre_census.COVERAGE_POINTS
    inner = (gpd.GeoSeries([county], crs="EPSG:4326").to_crs("EPSG:5070")
             .iloc[0].buffer(-cadastre_census.COVERAGE_INSET_M))
    projected = gpd.GeoSeries([Point(p) for p in pts],
                              crs="EPSG:4326").to_crs("EPSG:5070")
    assert all(inner.contains(p) for p in projected)
    # deterministic: a re-check asks the same points
    assert pts == cadastre_census.coverage_points(county)


def test_coverage_is_share_of_answered_points():
    class S:
        def __init__(self, answers):
            self.answers = iter(answers)

        def get_json(self, url, params=None):
            return next(self.answers)
    pts = [(0.0, 0.0)] * 4
    hit, miss = {"count": 3}, {"count": 0}
    assert cadastre_census.outline_coverage(S([hit, hit, hit, miss]), "u", pts) == (0.75, 4)
    # one refusal among four: measured on the three that answered
    assert cadastre_census.outline_coverage(S([hit, None, miss, miss]), "u", pts) == (0.333, 3)
    # most refused: not measured, never a zero
    assert cadastre_census.outline_coverage(S([hit, None, None, None]), "u", pts) == (None, 1)


def test_row_query_url_handles_root_and_layer_urls():
    q = cadastre_census._row_query_url
    assert q({"service_url": "https://g.gov/rest/services/P/MapServer/0",
              "layer_id": 0}) == "https://g.gov/rest/services/P/MapServer/0/query"
    assert q({"service_url": "https://g.gov/rest/services/P/MapServer",
              "layer_id": 2}) == "https://g.gov/rest/services/P/MapServer/2/query"
