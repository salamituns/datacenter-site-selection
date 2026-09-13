"""
The region model is the engine's identity layer: region_key is what promote
swaps on, so a defect here does not produce a wrong number, it produces a
county silently overwriting another county's parcels.

These tests run against the cached Census extract, so they need the cache to
have been built once (any pipeline run does it). They are skipped rather than
failed when it is absent, because an offline test run should not turn into a
network test run -- the rest of the suite is deliberately offline.
"""

import pytest

import region_registry as rr

pytestmark = pytest.mark.skipif(
    not rr._cache_path().exists(),
    reason="Census county cache not built; run the pipeline once to populate it",
)


# The regions already published. Their keys and FIPS codes are load-bearing:
# changing one orphans every parcel, metric and decision scoped to it.
PUBLISHED = {
    "VA-LOUDOUN": ("51107", "Loudoun", "VA"),
    "VA-PRINCEWILLIAM": ("51153", "Prince William", "VA"),
    "OH-FRANKLIN": ("39049", "Franklin", "OH"),
    "OH-LICKING": ("39089", "Licking", "OH"),
    "TX-TAYLOR": ("48441", "Taylor", "TX"),
    "OR-MORROW": ("41049", "Morrow", "OR"),
}


@pytest.mark.parametrize("key,expected", sorted(PUBLISHED.items()))
def test_published_regions_keep_their_identity(key, expected):
    fips, county, state = expected
    region = rr.resolve(key)
    assert region is not None, f"{key} no longer resolves"
    assert region.region_key == key
    assert region.fips == fips
    assert region.county == county
    assert region.state == state


def test_region_keys_are_unique_nationally():
    """
    The guard that matters most. Two county-equivalents sharing a region_key
    would overwrite each other on promote with no error raised anywhere.
    """
    df = rr._counties()
    dupes = sorted(set(df.region_key[df.region_key.duplicated(keep=False)]))
    assert dupes == [], f"region_key collides for {dupes}"


def test_independent_cities_are_distinct_from_their_county():
    """
    Virginia's independent cities are county-equivalents that share a name
    with the county beside them -- the case that made a name-only slug unsafe.
    """
    pairs = [
        ("VA-FAIRFAX", "51059", "VA-FAIRFAXCITY", "51600"),
        ("VA-FRANKLIN", "51067", "VA-FRANKLINCITY", "51620"),
        ("VA-RICHMOND", "51159", "VA-RICHMONDCITY", "51760"),
        ("VA-ROANOKE", "51161", "VA-ROANOKECITY", "51770"),
        ("MD-BALTIMORE", "24005", "MD-BALTIMORECITY", "24510"),
        ("MO-STLOUIS", "29189", "MO-STLOUISCITY", "29510"),
    ]
    for county_key, county_fips, city_key, city_fips in pairs:
        assert rr.resolve(county_key).fips == county_fips, county_key
        assert rr.resolve(city_key).fips == city_fips, city_key


def test_resolve_returns_the_canonical_key_not_the_callers_spelling():
    """
    A tolerated spelling must not become an identity. Publishing under the
    caller's spelling would create a second region for the same county on the
    next canonical run instead of replacing the first.
    """
    region = rr.resolve("VA-ALEXANDRIA")          # bare, unambiguous city
    assert region.fips == "51510"
    assert region.region_key == "VA-ALEXANDRIACITY"
    # and the survey window / operator lookups follow the canonical key
    assert rr.resolve("va-loudoun").region_key == "VA-LOUDOUN"


def test_bare_name_does_not_silently_resolve_an_ambiguous_city():
    """VA-FAIRFAX is the county; the city must be asked for by name."""
    assert rr.resolve("VA-FAIRFAX").fips == "51059"


def test_unknown_region_is_none_not_an_exception():
    assert rr.resolve("XX-NOWHERE") is None
    assert rr.resolve("") is None
    assert rr.resolve(None) is None


def test_licking_keeps_its_deliberate_window():
    """
    The one region that surveys less than its county does so on purpose, and
    the reason travels with it. Everything else gets the county's own extent.
    """
    licking = rr.resolve("OH-LICKING")
    assert licking.is_windowed
    assert "corridor" in licking.survey_window_reason
    assert licking.bbox == (-82.75, 39.95, -82.40, 40.25)

    loudoun = rr.resolve("VA-LOUDOUN")
    assert not loudoun.is_windowed
    assert loudoun.survey_window_reason is None


def test_derived_bbox_covers_the_county_the_hand_typed_one_missed():
    """
    The defect this module was written for. Loudoun's hand-typed box stopped
    at -77.85 west and 39.25 north while the county runs to -77.96 and 39.32,
    so 12.8% of it was never surveyed.

    The derived box is deliberately NOT a superset of the old one. The old box
    also ran east to -77.25 where the county ends at -77.32, and north-east of
    that line is Fairfax and Prince William -- so it was simultaneously too
    small on two sides and too large on a third. Being wrong in both directions
    at once is exactly what a typed constant does and a derived one cannot.
    """
    old_w, _, old_e, old_n = (-77.85, 38.75, -77.25, 39.25)
    new = rr.resolve("VA-LOUDOUN").bbox
    assert new[0] < old_w, "must reach further west, where county was missed"
    assert new[3] > old_n, "must reach further north, where county was missed"
    assert new[2] < old_e, "must stop east of the old box, which overran"


def test_grid_operator_is_none_rather_than_guessed():
    """
    RTO footprints do not follow state lines, so an unmapped county must
    report no operator. Defaulting would label Montana as PJM.
    """
    assert rr.resolve("VA-LOUDOUN").grid_operator == "PJM Interconnection"
    assert rr.resolve("TX-TAYLOR").grid_operator == "ERCOT"
    assert rr.resolve("MT-CUSTER").grid_operator is None


def test_county_fips_replaces_the_hand_maintained_map():
    """The five entries the hand-written COUNTY_FIPS carried, derived."""
    hand = {"VA-LOUDOUN": "51107", "VA-PRINCEWILLIAM": "51153",
            "OH-FRANKLIN": "39049", "OH-LICKING": "39089",
            "TX-TAYLOR": "48441"}
    for key, fips in hand.items():
        assert rr.county_fips(key) == fips
    assert rr.county_fips("XX-NOWHERE") is None


def test_all_regions_is_the_national_set_and_is_ordered():
    everything = list(rr.all_regions())
    assert len(everything) > 3000
    keys = [r.region_key for r in everything]
    assert keys == sorted(keys), "ordering must be stable for reproducible runs"
    assert len(set(keys)) == len(keys)


def test_all_regions_filters_by_state():
    ohio = list(rr.all_regions(["OH"]))
    assert len(ohio) == 88, "Ohio has 88 counties"
    assert {r.state for r in ohio} == {"OH"}
    assert "OH-LICKING" in {r.region_key for r in ohio}


def test_slug_matches_the_published_convention():
    assert rr.slug("VA", "Prince William") == "VA-PRINCEWILLIAM"
    assert rr.slug("oh", "Licking") == "OH-LICKING"
    assert rr.slug("MO", "St. Louis") == "MO-STLOUIS"
    assert rr.slug("MO", "St. Louis", "25") == "MO-STLOUISCITY"
    assert rr.slug("MO", "St. Louis", "06") == "MO-STLOUIS"
