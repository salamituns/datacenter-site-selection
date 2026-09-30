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

    def get_json(self, url, params=None, **kw):
        return self.answers.get(url)


def test_web_map_sentinel_even_when_state_program_verifies(monkeypatch):
    # WV's statewide layer verifies, the county's web maps find nothing:
    # the region still needs its web_map row, or every re-run redoes it
    wv_url = cadastre_census.SELF_HOSTED_STATE_PROGRAMS["WV"][0][0]
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

        def get_json(self, url, params=None, **kw):
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


def test_coverage_points_avoid_water():
    # a county whose east half is a sound: no point may land in it
    import geopandas as gpd
    from shapely.geometry import Point, box
    county = box(-76.2, 35.5, -75.6, 36.0)
    sound = (gpd.GeoSeries([box(-75.9, 35.4, -75.5, 36.1)], crs="EPSG:4326")
             .to_crs("EPSG:5070").iloc[0])
    pts = cadastre_census.coverage_points(county, water=sound)
    assert len(pts) == cadastre_census.COVERAGE_POINTS
    projected = gpd.GeoSeries([Point(p) for p in pts],
                              crs="EPSG:4326").to_crs("EPSG:5070")
    margin = sound.buffer(cadastre_census.WATER_MARGIN_M)
    assert not any(margin.contains(p) for p in projected)
    # without water the grid does reach the sound half
    dry_blind = gpd.GeoSeries(
        [Point(p) for p in cadastre_census.coverage_points(county)],
        crs="EPSG:4326").to_crs("EPSG:5070")
    assert any(sound.contains(p) for p in dry_blind)


def test_all_water_county_keeps_its_outline():
    import geopandas as gpd
    from shapely.geometry import box
    county = box(-76.2, 35.5, -75.6, 36.0)
    everything = (gpd.GeoSeries([box(-77, 35, -75, 37)], crs="EPSG:4326")
                  .to_crs("EPSG:5070").iloc[0])
    assert len(cadastre_census.coverage_points(county, water=everything)) \
        == cadastre_census.COVERAGE_POINTS


def test_service_error_in_a_200_is_no_answer(monkeypatch):
    # ArcGIS Server's "service not found" arrives as HTTP 200
    class Resp:
        status_code = 200

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body
    monkeypatch.setattr(cadastre_census, "REQUEST_PAUSE", 0)
    s = cadastre_census._ThrottledSession()
    missing = {"error": {"code": 404,
                         "message": "Service parcels/MapServer not found "}}
    monkeypatch.setattr(s._session, "get", lambda *a, **k: Resp(missing))
    assert s.get_json("https://g.gov/rest/services/parcels/MapServer") is None
    ok = {"layers": [], "error_count": 0}
    monkeypatch.setattr(s._session, "get", lambda *a, **k: Resp(ok))
    assert s.get_json("https://g.gov/rest/services/x/MapServer") == ok


# ── the targeted pass ─────────────────────────────────────────────────────

def test_services_root():
    r = cadastre_census._services_root
    assert (r("https://maps.lexingtonky.gov/lfucggis/rest/services/parcels/MapServer/0")
            == "https://maps.lexingtonky.gov/lfucggis/rest/services")
    assert r("https://example.gov/something/else") is None


def test_directory_crawl_finds_renamed_parcel_service():
    # Lexington: the web maps say parcels/MapServer, the directory says
    # property/MapServer — the directory is the server's current word
    root = "https://maps.lexingtonky.gov/lfucggis/rest/services"
    session = _FakeSession({
        root: {"folders": ["Utilities"], "services": [
            {"name": "aerial_mostrecent", "type": "MapServer"},
            {"name": "property", "type": "MapServer"},
            {"name": "zoning", "type": "MapServer"},
            {"name": "Tax_Parcels", "type": "FeatureServer"},
            {"name": "parcels_geocoder", "type": "GeocodeServer"},
        ]},
        root + "/Utilities": {"services": [
            {"name": "Utilities/Parcel_Lookup", "type": "MapServer"}]},
    })
    found = cadastre_census.crawl_host_directory(
        session, root + "/parcels/MapServer/0")
    assert [n for n, _ in found] == ["property", "Tax_Parcels",
                                     "Utilities/Parcel_Lookup"]
    assert found[0][1] == root + "/property/MapServer"


def test_directory_crawl_needs_an_arcgis_server():
    assert cadastre_census.crawl_host_directory(
        _FakeSession({}), "https://example.gov/parcels.json") == []


def test_area_water_falls_back_to_prior_vintage(monkeypatch, tmp_path):
    # Gloucester, VA: the 2024 file answers with the WAF's HTML page, the
    # 2023 file with a zip — the prior vintage must be used, not skipped
    import io
    import zipfile
    import geopandas as gpd
    from shapely.geometry import box
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gpd.GeoDataFrame(geometry=[box(-76.5, 37.3, -76.4, 37.4)],
                     crs="EPSG:4269").to_file(shp_dir / "w.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in shp_dir.iterdir():
            zf.write(f, f.name)

    class Resp:
        def __init__(self, content, ctype):
            self.status_code, self.content = 200, content
            self.headers = {"content-type": ctype}
    asked = []

    def fake_get(url, **kw):
        asked.append(url)
        if "2024" in url:
            return Resp(b"<html><title>Request Rejected</title></html>",
                        "text/html")
        return Resp(buf.getvalue(), "application/zip")
    monkeypatch.setattr(cadastre_census.requests, "get", fake_get)
    monkeypatch.setattr(cadastre_census, "AREAWATER_CACHE_DIR",
                        tmp_path / "cache")
    import region_registry
    monkeypatch.setattr(region_registry, "county_fips", lambda key: "99999")
    water = cadastre_census.county_water("VA-TESTCOUNTY")
    assert not water.is_empty
    assert [u.split("/")[5] for u in asked] == ["TIGER2024", "TIGER2023"]
    assert (tmp_path / "cache" / "99999.gpkg").exists()


# ── Kentucky: the catalog, the abbreviation, the regional pool ────────────

def test_catalog_matches_the_county_exactly():
    session = _FakeSession({cadastre_census.AGOL_SEARCH_URL: {"results": [
        {"title": "Parcels - KY - Boyle County", "owner": "GDITAdmin",
         "id": "a1", "url": "https://maps2.bgadd.org/arcgis/rest/services/"
                            "Boyle/BoyleParcelBoundary/MapServer/0"},
        # the search is fuzzy: a neighbour's entry must not answer
        {"title": "Parcels - KY - Boyle and Mercer Joint", "owner": "GDITAdmin",
         "id": "a2", "url": "https://x.gov/rest/services/J/MapServer/0"},
        {"title": "Parcels - KY - Boyd County", "owner": "GDITAdmin",
         "id": "a3", "url": "https://y.gov/rest/services/B/MapServer/0"},
    ]}})
    cadastre_census._CATALOG_CACHE.clear()
    found = cadastre_census.catalog_urls(session, "Boyle", "KY")
    assert [t for t, _, _ in found] == ["Parcels - KY - Boyle County"]
    cadastre_census._CATALOG_CACHE.clear()


def test_catalog_matches_across_spelling():
    # the Census says LaSalle, the catalog "La Salle County"
    session = _FakeSession({cadastre_census.AGOL_SEARCH_URL: {"results": [
        {"title": "Parcels - IL - La Salle County", "owner": "GDITAdmin",
         "id": "l1", "url": "https://gis.lasallecounty.org/arcgis/rest/"
                            "services/TaxParcels/MapServer/0"},
        {"title": "Parcels - IL - Jo Daviess County", "owner": "GDITAdmin",
         "id": "j1", "url": "https://jd.gov/rest/services/P/MapServer/0"},
    ]}})
    cadastre_census._CATALOG_CACHE.clear()
    assert [i["id"] for _, _, i in
            cadastre_census.catalog_urls(session, "LaSalle", "IL")] == ["l1"]
    assert [i["id"] for _, _, i in
            cadastre_census.catalog_urls(session, "Jo Daviess", "IL")] == ["j1"]
    cadastre_census._CATALOG_CACHE.clear()


def test_pool_answers_only_for_services_named_for_the_county():
    root = "https://maps2.bgadd.org/arcgis/rest/services"
    session = _FakeSession({
        root: {"folders": ["Boyle", "Garrard"], "services": []},
        root + "/Boyle": {"services": [
            {"name": "Boyle/BoyleParcelBoundary", "type": "MapServer"}]},
        root + "/Garrard": {"services": [
            {"name": "Garrard/GarrardPVA", "type": "MapServer"},
            {"name": "Garrard/GarrardRoads", "type": "MapServer"}]},
    })
    cadastre_census._DIRECTORY_CACHE.clear()
    got = cadastre_census.pooled_host_services(session, "Garrard", [root])
    assert [n for n, _, _ in got] == ["Garrard/GarrardPVA"]
    # the directory was read once and cached for the next county
    assert root.lower() in cadastre_census._DIRECTORY_CACHE
    assert [n for n, _, _ in cadastre_census.pooled_host_services(
        session, "Boyle", [root])] == ["Boyle/BoyleParcelBoundary"]
    cadastre_census._DIRECTORY_CACHE.clear()


def test_abbreviated_search_keeps_the_first_pass_floor():
    session = _FakeSession({cadastre_census.AGOL_SEARCH_URL: {"results": [
        {"title": "Ky_PVA_Hardin_Parcels", "owner": "kevin.hogue_kygeonet",
         "type": "Feature Service", "tags": [], "id": "h1",
         "url": "https://kygisserver.ky.gov/arcgis/rest/services/"
                "WGS84WM_Services/Ky_PVA_Hardin_Parcels_WGS84WM/MapServer"},
        # nationwide commercial layer: no county token, rejected as before
        {"title": "Regrid USA Nationwide Parcel Boundaries",
         "owner": "data_regrid", "type": "Feature Service", "tags": [],
         "id": "r1", "url": "https://z.arcgis.com/rest/services/R/FeatureServer"},
    ]}})
    got = cadastre_census.abbreviated_search(session, "Hardin", "KY")
    assert [i["id"] for i in got] == ["h1"]


def test_complete_parcel_layer_before_its_subsets():
    # Boone County, KY: thirteen parcel layers, the subsets listed first
    svc = {"layers": [
        {"id": 7, "name": "Airport Owned Parcels (outline)",
         "geometryType": "esriGeometryPolygon"},
        {"id": 8, "name": "Airport Owned Parcels (shaded)",
         "geometryType": "esriGeometryPolygon"},
        {"id": 18, "name": "HOA Parcels", "geometryType": "esriGeometryPolygon"},
        {"id": 12, "name": "Tax Districts (thick outline)",
         "geometryType": "esriGeometryPolygon"},
        {"id": 32, "name": "All Parcel Types",
         "geometryType": "esriGeometryPolygon"},
        {"id": 0, "name": "Tax Parcels", "geometryType": "esriGeometryPolygon"},
    ]}
    assert [l["id"] for l in cadastre_census.choose_layers(svc)] == [32, 0]


def test_layer_rank_orders_complete_tax_subset_other():
    r = cadastre_census.layer_rank
    assert r("Tax Parcels") == 0
    assert r("Parcels") == 0
    assert r("Cadastre") == 1
    assert r("Residential Parcels") == 2
    assert r("Zip Codes") == 3


def test_catalog_keeps_county_and_city_apart():
    session = _FakeSession({cadastre_census.AGOL_SEARCH_URL: {"results": [
        {"title": "Parcels - VA - Richmond City", "owner": "GDITAdmin",
         "id": "city", "url": "https://c.gov/rest/services/P/MapServer/0"},
        {"title": "Parcels - VA - Richmond County", "owner": "GDITAdmin",
         "id": "county", "url": "https://k.gov/rest/services/P/MapServer/0"},
    ]}})
    cadastre_census._CATALOG_CACHE.clear()
    assert [i["id"] for _, _, i in
            cadastre_census.catalog_urls(session, "Richmond", "VA")] == ["county"]
    cadastre_census._CATALOG_CACHE.clear()


def test_every_row_stamps_its_own_check_time():
    # an upsert must refresh checked_at; the column default only fires
    # on insert, and re-verified rows kept their first-pass date
    row = cadastre_census._row("OH-WOOD", "OH", "Wood", "state_program",
                               "t", "o", None, "https://x.gov/rest/services/P/MapServer", 0)
    assert "checked_at" in row and row["checked_at"].startswith("20")
