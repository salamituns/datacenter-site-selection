"""
Delaware publishes township zoning as sixteen separate services with sixteen
different schemas — each is a join of polygons to a district table, and the
join prefixes every field with its source name.

The normaliser matches on the suffix rather than hard-coding sixteen field
names, so a service renamed upstream still resolves instead of silently
returning a township with no districts.
"""

from central_ohio_api import CentralOhioParcelAPI, DELAWARE_ZONING_SERVICES


def _meta(*names):
    return {"fields": [{"name": n} for n in names]}


def test_the_common_shape_resolves():
    code, label = CentralOhioParcelAPI._zoning_fields(
        _meta("OBJECTID", "Scioto_Zoning_ZONID", "Scioto_Zoning_ZONING",
              "Scioto_Zoning_DSC_ZONE", "Zoning__TOWNSHIP"))
    assert code == "Scioto_Zoning_ZONING"
    assert label == "Scioto_Zoning_DSC_ZONE"


def test_a_differently_prefixed_service_resolves_the_same_way():
    """Berkshire's prefix is the service name, not the township name."""
    code, label = CentralOhioParcelAPI._zoning_fields(
        _meta("berkshirezon_ZONID", "berkshirezon_ZONING",
              "berkshirezon_DSC_ZONE", "Zoning2__Zoning_District"))
    assert code == "berkshirezon_ZONING"
    assert label == "berkshirezon_DSC_ZONE"


def test_the_joined_district_column_is_not_mistaken_for_the_code():
    """
    Zoning__Zoning_District and Zoning2__Zoning_District are the joined
    table's columns. Picking one as the code field would work by accident on
    some services and return row ids on others.
    """
    code, _ = CentralOhioParcelAPI._zoning_fields(
        _meta("Zoning__Zoning_District", "Troy_Zoning_ZONING"))
    assert code == "Troy_Zoning_ZONING"


def test_the_joined_column_is_the_fallback_label():
    _, label = CentralOhioParcelAPI._zoning_fields(
        _meta("Foo_ZONING", "Zoning2__Zoning_District"))
    assert label == "Zoning2__Zoning_District"


def test_a_service_with_no_code_field_resolves_to_none():
    """Absent is better than wrong: the caller skips the township loudly."""
    code, _ = CentralOhioParcelAPI._zoning_fields(_meta("OBJECTID", "Shape"))
    assert code is None


def test_every_township_is_registered_once():
    names = [t for t, _ in DELAWARE_ZONING_SERVICES]
    assert len(names) == len(set(names))
    assert len(names) == 16
    # Thompson, Radnor and Marlboro share the county code and must NOT appear
    # as townships of their own — that would imply three separate surveys.
    for absent in ("Thompson township", "Radnor township", "Marlboro township"):
        assert absent not in names
    assert "Delaware County code" in names


def test_layer_ids_are_carried_not_assumed():
    """
    Porter is layer 382, Oxford 383, the county service 385 — published out of
    one enterprise map document. Assuming /0 would silently query the wrong
    layer or fail.
    """
    paths = dict(DELAWARE_ZONING_SERVICES)
    assert paths["Porter township"].endswith("/382")
    assert paths["Oxford township"].endswith("/383")
    assert paths["Delaware County code"].endswith("/385")
