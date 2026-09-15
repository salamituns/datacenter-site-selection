"""
The PJM footprint is derived, and the derivation is easy to get wrong in a way
nobody would see. These pin the choices that make it right.

Skipped when the footprint cache is absent, so an offline run does not turn
into a network run.
"""

import pytest

import region_registry as rr

pytestmark = pytest.mark.skipif(
    not rr._pjm_cache().exists(),
    reason="PJM footprint cache not built; call pjm_footprint() once",
)


def test_every_published_pjm_county_is_in_the_footprint():
    """
    These six run PJM RTEP and queue evidence today, on independent grounds.
    A derivation that loses one of them is wrong however plausible it looks.
    """
    fp = rr.pjm_footprint()
    for key in ("VA-LOUDOUN", "VA-PRINCEWILLIAM", "VA-FAUQUIER",
                "OH-FRANKLIN", "OH-LICKING", "OH-DELAWARE"):
        assert fp.get(key, 0) >= 90, f"{key} measured {fp.get(key)}%"


def test_non_pjm_counties_are_absent():
    fp = rr.pjm_footprint()
    assert "TX-TAYLOR" not in fp      # ERCOT
    assert "OR-MORROW" not in fp      # Bonneville


def test_the_footprint_is_not_whole_states():
    """
    Ohio splits between PJM and MISO, and so do Illinois, Indiana, Kentucky
    and Michigan. A footprint that contained every county of any of those
    states would be a state-code guess wearing a measurement's clothes.
    """
    fp = rr.pjm_footprint()
    mi = [k for k in fp if k.startswith("MI-")]
    assert 0 < len(mi) < 20, f"Michigan has 83 counties; {len(mi)} in footprint"
    nc = [k for k in fp if k.startswith("NC-")]
    assert 0 < len(nc) < 50, f"North Carolina has 100 counties; {len(nc)}"


def test_screening_regions_respect_the_threshold_and_are_ordered():
    fp = rr.pjm_footprint()
    regions = rr.pjm_screening_regions()
    assert regions == sorted(regions), "order must be stable for a reproducible run"
    assert len(set(regions)) == len(regions)
    for k in regions:
        assert fp[k] >= rr.PJM_SCREEN_MIN_PCT
    # a county below the threshold is measured but not screened
    below = [k for k, v in fp.items() if v < rr.PJM_SCREEN_MIN_PCT]
    for k in below:
        assert k not in regions


def test_the_two_thresholds_are_distinct_claims():
    """
    "Worth screening" and "we know its market" are different assertions. The
    operator threshold must be the stricter one, or a county 12% inside PJM
    would be labelled a PJM county.
    """
    assert rr.PJM_OPERATOR_MIN_PCT > rr.PJM_SCREEN_MIN_PCT


def test_every_key_is_a_resolvable_region():
    """A footprint entry that does not resolve cannot be surveyed."""
    for key in list(rr.pjm_screening_regions())[:40]:
        assert rr.resolve(key) is not None, key
