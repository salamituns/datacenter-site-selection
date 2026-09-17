"""
How the screening runner picks a batch — and how it picks a recovery batch.

--incomplete exists because honest degradation must be recoverable: a county
that published UNKNOWN while a layer was unreachable should be re-run once
the layer answers, and the list of such counties must come from the
published runs, not a retry file that can drift or be forgotten.
"""

import pytest

import pjm_screening as ps
import region_registry as rr

pytestmark = pytest.mark.skipif(
    not rr._pjm_cache().exists(),
    reason="PJM footprint cache not built; call pjm_footprint() once",
)


def test_a_run_with_a_missing_layer_is_incomplete():
    assert ps._recorded_missing_layers(
        {"layers": {"wetlands": "present", "padus": "missing"}})


def test_a_run_with_every_layer_present_is_not_incomplete():
    assert not ps._recorded_missing_layers(
        {"layers": {"wetlands": "present", "padus": "present"}})


def test_a_run_from_before_the_map_existed_is_not_incomplete():
    """
    No layers key predates the record; treating it as degraded would put
    every legacy county on the recovery list forever. The coverage guard,
    not recovery, is what handles such runs at promote time.
    """
    assert not ps._recorded_missing_layers({"grid_parcels": 330})
    assert not ps._recorded_missing_layers(None)


def test_incomplete_mode_selects_degraded_counties_not_unscreened_ones(monkeypatch):
    degraded = {r for r in rr.pjm_screening_regions()
                if r.startswith("OH")}
    monkeypatch.setattr(ps, "incomplete_regions", lambda: degraded)
    monkeypatch.setattr(ps, "published_regions",
                        lambda: {"ZZ-NEVER"} | degraded)

    batch = ps.next_batch(500, incomplete=True)
    assert batch == sorted(degraded), \
        "recovery must re-run exactly the degraded counties, in state order"


def test_incomplete_ignores_redo_and_published_state(monkeypatch):
    """
    --incomplete replaces the criterion: a county with a full layer set
    never appears however --redo is set, and an unscreened county never
    appears either — recovery is not a re-sweep.
    """
    degraded = {r for r in rr.pjm_screening_regions()
                if r.startswith("VA")}
    monkeypatch.setattr(ps, "incomplete_regions", lambda: degraded)
    monkeypatch.setattr(ps, "published_regions", lambda: set())

    for redo in (False, True):
        batch = ps.next_batch(500, redo=redo, incomplete=True)
        assert batch == sorted(degraded)


def test_default_mode_still_skips_published_counties(monkeypatch):
    monkeypatch.setattr(ps, "published_regions",
                        lambda: set(rr.pjm_screening_regions()))
    monkeypatch.setattr(ps, "incomplete_regions", lambda: {"OH-FRANKLIN"})

    assert ps.next_batch(10) == []
    # and --incomplete does not inherit that skip: degraded counties are
    # already published, so the published check must not apply to them
    monkeypatch.setattr(ps, "published_regions", lambda: set())
    assert ps.next_batch(10, incomplete=True) == ["OH-FRANKLIN"]


def test_state_filter_applies_to_recovery_too(monkeypatch):
    degraded = {r for r in rr.pjm_screening_regions()}
    monkeypatch.setattr(ps, "incomplete_regions", lambda: degraded)
    batch = ps.next_batch(500, state="IL", incomplete=True)
    assert batch and all(k.startswith("IL-") for k in batch)


# ---------------------------------------------------------------------------
# Recovery is scoped to what was published, not to the sweep
# ---------------------------------------------------------------------------
#
# next_batch used to start from the footprint and intersect the degraded set,
# which made "is in the PJM footprint" a silent precondition for being
# recoverable. It went unnoticed because the test above draws its degraded
# fixture FROM the footprint, so the intersection it should have caught could
# not fail. Meanwhile the only degraded region in the live database was
# OR-MORROW, outside PJM: incomplete_regions() named it and the runner
# answered "Nothing to do".


def test_a_degraded_region_outside_the_footprint_is_still_recovered(monkeypatch):
    outside = "OR-MORROW"
    assert outside not in set(rr.pjm_screening_regions()), (
        "fixture must sit outside the footprint or this test proves nothing")
    monkeypatch.setattr(ps, "incomplete_regions", lambda: {outside})
    monkeypatch.setattr(ps, "published_regions", lambda: set())

    assert ps.next_batch(10, incomplete=True) == [outside]


def test_recovery_still_honours_a_state_filter(monkeypatch):
    monkeypatch.setattr(ps, "incomplete_regions", lambda: {"OR-MORROW"})
    monkeypatch.setattr(ps, "published_regions", lambda: set())

    assert ps.next_batch(10, state="OR", incomplete=True) == ["OR-MORROW"]
    assert ps.next_batch(10, state="VA", incomplete=True) == []


def test_an_ordinary_batch_stays_inside_the_footprint(monkeypatch):
    # Widening recovery must not widen the sweep: a region outside the
    # footprint has no business in a normal screening batch.
    monkeypatch.setattr(ps, "incomplete_regions", lambda: {"OR-MORROW"})
    monkeypatch.setattr(ps, "published_regions", lambda: set())

    batch = ps.next_batch(50)
    assert "OR-MORROW" not in batch
    assert set(batch) <= set(rr.pjm_screening_regions())
