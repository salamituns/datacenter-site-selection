"""
The one thing that must not regress: a layer that fails to fetch leaves its
keys absent, never zero. "No wetland here" and "nobody looked" are different
facts, and a 0.0 would collapse them. Since the coverage guard landed, the
second thing that must not regress: the availability map records the
"nobody looked" half as a missing layer, under the parcel tier's names, so
promote can refuse a publish that would silently drop it.
"""

import geopandas as gpd
from shapely.geometry import box

import national_metrics


def _cells():
    return gpd.GeoDataFrame(
        {"geometry": [box(-83.2, 40.0, -83.1, 40.1),
                      box(-83.1, 40.0, -83.0, 40.1)]},
        crs="EPSG:4326")


def _all_layers_missing(monkeypatch):
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_nwi_wetlands", lambda *a, **k: (None, ""))
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_nfhl_floodzones", lambda *a, **k: (None, ""))
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_padus", lambda *a, **k: None)
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_tiger_roads", lambda *a, **k: None)
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "sample_3dep_slopes", lambda *a, **k: None)


def test_failed_layers_leave_keys_absent_not_zero(monkeypatch):
    _all_layers_missing(monkeypatch)

    out, _layers = national_metrics.measure(_cells(), -83.2, 40.0, -83.0, 40.1, "OH")
    assert out == [{}, {}], "a failed layer must contribute no key at all"


def test_missing_layers_are_recorded_missing_under_parcel_tier_names(monkeypatch):
    """
    The availability map carries every layer this tier knows about, marked
    by whether it answered — a missing layer is a recorded fact, not an
    absent key. The names are the parcel tier's (wetlands, slope, not nwi,
    3dep) so the promote guard compares like with like when a county
    changes tier.
    """
    _all_layers_missing(monkeypatch)

    _out, layers = national_metrics.measure(_cells(), -83.2, 40.0, -83.0, 40.1, "OH")
    assert layers == {
        "wetlands": "missing",
        "nfhl": "missing",
        "padus": "missing",
        "roads": "missing",
        "slope": "missing",
    }


def test_present_layers_are_recorded_present(monkeypatch):
    """One layer answering and four failing reads as 1 present, 4 missing."""
    half = gpd.GeoDataFrame(
        {"geometry": [box(-83.2, 40.0, -83.15, 40.1)]}, crs="EPSG:4326")
    _all_layers_missing(monkeypatch)
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_padus", lambda *a, **k: half)

    _out, layers = national_metrics.measure(_cells(), -83.2, 40.0, -83.0, 40.1, "OH")
    assert layers["padus"] == "present"
    assert layers["wetlands"] == "missing"
    assert layers["slope"] == "missing"


def test_measurements_are_percentages_of_the_cell(monkeypatch):
    """A layer covering half of each cell reads ~50%, not an area."""
    half = gpd.GeoDataFrame(
        {"geometry": [box(-83.2, 40.0, -83.15, 40.1),
                      box(-83.1, 40.0, -83.05, 40.1)]},
        crs="EPSG:4326")
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_nwi_wetlands", lambda *a, **k: (half, ""))
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_nfhl_floodzones", lambda *a, **k: (None, ""))
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_padus", lambda *a, **k: None)
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_tiger_roads", lambda *a, **k: None)
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "sample_3dep_slopes", lambda *a, **k: None)

    out, _layers = national_metrics.measure(_cells(), -83.2, 40.0, -83.0, 40.1, "OH")
    assert len(out) == 2
    for cell in out:
        assert 45.0 < cell["wetland_pct"] < 55.0
        assert set(cell) == {"wetland_pct"}


def test_no_verdict_keys_are_ever_emitted(monkeypatch):
    """
    Measurements, not verdicts. Nothing here may look like a gate status --
    that is the whole point of the national tier.
    """
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_nwi_wetlands", lambda *a, **k: (_cells(), ""))
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_nfhl_floodzones", lambda *a, **k: (None, ""))
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_padus", lambda *a, **k: None)
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "fetch_tiger_roads", lambda *a, **k: None)
    monkeypatch.setattr(national_metrics.overlay_layers,
                        "sample_3dep_slopes", lambda *a, **k: None)

    out, _layers = national_metrics.measure(_cells(), -83.2, 40.0, -83.0, 40.1, "OH")
    for cell in out:
        for key, value in cell.items():
            assert key.endswith(("_pct", "_km")), key
            assert value is None or isinstance(value, (int, float)), key
