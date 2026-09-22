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
