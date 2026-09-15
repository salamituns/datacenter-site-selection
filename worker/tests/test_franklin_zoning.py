"""
Franklin's zoning fetch, and the two traps it has to survive.

This adapter asserted for a long time that Franklin published no zoning at
all. It publishes a county layer covering the ten townships that adopted the
county resolution, plus layers for five of the seven that zone themselves.
"""

from franklin_api import (FranklinParcelAPI, FRANKLIN_ZONING_SERVICES,
                          FRANKLIN_COUNTY_CODE_LABEL,
                          FRANKLIN_COUNTY_CODE_TOWNSHIPS,
                          SELF_ZONING_WITHOUT_A_LAYER, NON_DISTRICT_VALUES)


def _meta(*names):
    return {"fields": [{"name": n} for n in names]}


def test_zoning_is_preferred_over_zone48():
    """
    Both fields exist on the county layer and on Blendon's, and Blendon's
    ZONE48 is empty — every row '' or 'None'. Taking the first plausible
    field returns a township with no districts and no error, which reads as
    "nothing published" rather than "wrong column".
    """
    assert FranklinParcelAPI._zoning_field(
        _meta("OBJECTID", "ZONE48", "ZONING", "NOTES")) == "ZONING"


def test_field_case_varies_between_townships():
    """Prairie and Perry write ZONING; Plain and Washington write Zoning."""
    assert FranklinParcelAPI._zoning_field(_meta("PID", "Zoning")) == "Zoning"
    assert FranklinParcelAPI._zoning_field(_meta("PID", "ZONING")) == "ZONING"


def test_zone48_alone_is_not_accepted():
    """
    ZONE48 is empty on every layer it has been seen on. A layer carrying only
    ZONE48 therefore resolves to None and is dropped loudly, rather than
    returning a township full of blank districts that reads as "nothing
    published". Absent beats silently wrong.
    """
    assert FranklinParcelAPI._zoning_field(_meta("OBJECTID", "ZONE48")) is None


def test_no_zoning_field_resolves_to_none():
    """Absent beats wrong: the caller drops that township loudly."""
    assert FranklinParcelAPI._zoning_field(_meta("OBJECTID", "Shape")) is None


def test_not_in_jurisdiction_is_not_a_district():
    """
    The county layer's own marker for land it does not zone — a municipality,
    or one of the seven townships that zone themselves. Mapping it as a
    district would invent a classification for land the county disclaims.
    """
    assert "NOT IN JURISDICTION" in NON_DISTRICT_VALUES
    assert "NONE" in NON_DISTRICT_VALUES
    assert "" in NON_DISTRICT_VALUES


def test_the_ten_county_code_townships_are_recorded():
    assert len(FRANKLIN_COUNTY_CODE_TOWNSHIPS) == 10
    for t in ("Pleasant", "Madison", "Brown", "Truro"):
        assert t in FRANKLIN_COUNTY_CODE_TOWNSHIPS


def test_the_county_layer_is_labelled_for_its_instrument_not_a_township():
    """
    Ten townships read it in common. Labelling its polygons with one
    township's name would imply the other nine were surveyed separately.
    """
    labels = [t for t, _ in FRANKLIN_ZONING_SERVICES]
    assert FRANKLIN_COUNTY_CODE_LABEL in labels
    for t in FRANKLIN_COUNTY_CODE_TOWNSHIPS:
        assert f"{t} township" not in labels


def test_the_townships_without_a_layer_are_named():
    """"Not published" and "not looked for" are different facts."""
    assert set(SELF_ZONING_WITHOUT_A_LAYER) == {"Jackson", "Jefferson"}
    labels = [t for t, _ in FRANKLIN_ZONING_SERVICES]
    for t in SELF_ZONING_WITHOUT_A_LAYER:
        assert f"{t} township" not in labels
