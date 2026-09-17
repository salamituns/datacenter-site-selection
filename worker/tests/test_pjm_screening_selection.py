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
