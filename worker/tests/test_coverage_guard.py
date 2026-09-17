"""
The coverage guard's worker side: the map both tiers record before promote.

The database refuses a publish that would drop a layer the live generation
had (migration release28), but the guard can only compare what the worker
actually wrote onto the run row. These tests pin the two halves of that:
the map's shape, and the pre-promote write that puts it there.
"""

from typing import Any, Dict, List, Optional

import pytest

import pipeline
import runs


class _Resp:
    def __init__(self, data: Any):
        self.data = data

    def execute(self) -> "_Resp":
        # supabase-py returns a builder whose .execute() yields the payload;
        # returning self covers both the table chain and the rpc call.
        return self


class _Table:
    """Chainable stand-in for the supabase table builder, recording calls."""

    def __init__(self, state: Dict[str, Any]):
        self.state = state
        self._ops: List[Dict[str, Any]] = []

    def select(self, _col: str) -> "_Table":
        return self

    def eq(self, col: str, val: Any) -> "_Table":
        self._ops.append({"op": "eq", "col": col, "val": val})
        return self

    def update(self, payload: Dict[str, Any]) -> "_Table":
        self.state["updates"].append(payload)
        self._ops.append({"op": "update", "payload": payload})
        return self

    def single(self) -> "_Table":
        return self

    def execute(self) -> _Resp:
        return _Resp(self.state.get("row"))


class _Client:
    def __init__(self, row: Optional[Dict[str, Any]] = None):
        self.tables: Dict[str, _Table] = {}
        self.state = {"row": row, "updates": []}

    def table(self, name: str) -> _Table:
        if name not in self.tables:
            self.tables[name] = _Table(self.state)
        return self.tables[name]

    def rpc(self, fn: str, params: Dict[str, Any]) -> _Resp:
        self.state.setdefault("rpcs", []).append({"fn": fn, "params": params})
        return _Resp({"region": "TEST"})


def _parcel_stats() -> Dict[str, Any]:
    # The shape qualify_parcels returns: categorical *_layer keys alongside
    # counts. water_layer_edited is deliberately included — it ends in
    # "_edited", not "_layer", and describes how a layer was read, not
    # whether it answered.
    return {
        "parcels_qualified": 7,
        "wetlands_layer": "present",
        "nfhl_layer": "missing",
        "padus_layer": "present",
        "roads_layer": "present",
        "places_layer": "present",
        "subdivisions_layer": "present",
        "restrictions_layer": "present",
        "slope_layer": "missing",
        "utility_layer": "present",
        "rtep_layer": "present",
        "queue_layer": "present",
        "county_applications_layer": "present",
        "water_layer": "present",
        "water_layer_edited": False,
        "zoning_coverage_pct": 0.81,
    }


def test_layer_availability_keeps_only_the_star_layer_keys():
    layers = pipeline._layer_availability(_parcel_stats())
    assert layers == {
        "wetlands": "present", "nfhl": "missing", "padus": "present",
        "roads": "present", "places": "present", "subdivisions": "present",
        "restrictions": "present", "slope": "missing", "utility": "present",
        "rtep": "present", "queue": "present",
        "county_applications": "present", "water": "present",
    }


def test_layer_availability_names_match_the_screening_tier():
    """
    The screening tier records wetlands, nfhl, padus, roads, slope. The
    parcel tier must use the same names, or a county that gains a cadastral
    adapter reads as losing its screening layers to a rename and the
    promote guard refuses a correct publish.
    """
    layers = pipeline._layer_availability(_parcel_stats())
    for name in ("wetlands", "nfhl", "padus", "roads", "slope"):
        assert name in layers, f"parcel tier lost the name {name!r}"


def test_record_layers_merges_into_existing_stats_and_preserves_them():
    client = _Client(row={"stats": {"pipeline_version": "v41",
                                    "zoning_coverage_pct": 0.81}})
    run = runs.IngestionRun(client, region_code="OH-FRANKLIN",
                            pipeline_version="v41")
    run.run_id = "11111111-1111-1111-1111-111111111111"

    run.record_layers({"wetlands": "present", "padus": "missing"})

    assert len(client.state["updates"]) == 1
    written = client.state["updates"][0]["stats"]
    # A merge, not a clobber: the counts promote merges at the end are
    # written beside the map, not replaced by it.
    assert written["pipeline_version"] == "v41"
    assert written["zoning_coverage_pct"] == 0.81
    assert written["layers"] == {"wetlands": "present", "padus": "missing"}


def test_record_layers_writes_when_stats_was_null():
    client = _Client(row={"stats": None})
    run = runs.IngestionRun(client, region_code="OR-MORROW",
                            pipeline_version="v41")
    run.run_id = "22222222-2222-2222-2222-222222222222"

    run.record_layers({"slope": "missing"})
    assert client.state["updates"][0]["stats"]["layers"] == {"slope": "missing"}


def test_record_layers_requires_a_started_run():
    run = runs.IngestionRun(_Client(), region_code="VA-LOUDOUN",
                            pipeline_version="v41")
    with pytest.raises(RuntimeError):
        run.record_layers({"wetlands": "present"})


def test_promote_passes_the_override_param_explicitly():
    """
    The default is False and the database defaults it too, but the call
    sends it anyway: a worker that silently stopped passing the override
    would turn an operator's deliberate decision into a refused publish
    with nothing in the logs naming the cause.
    """
    client = _Client()
    run = runs.IngestionRun(client, region_code="TX-TAYLOR",
                            pipeline_version="v41")
    run.run_id = "33333333-3333-3333-3333-333333333333"

    run.promote()
    run.promote(allow_coverage_regression=True)

    rpcs = client.state["rpcs"]
    assert rpcs[0]["params"] == {
        "p_run_id": run.run_id, "p_allow_coverage_regression": False}
    assert rpcs[1]["params"] == {
        "p_run_id": run.run_id, "p_allow_coverage_regression": True}
