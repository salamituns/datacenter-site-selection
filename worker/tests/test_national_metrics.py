"""
The one thing that must not regress: a layer that fails to fetch leaves its
keys absent, never zero. "No wetland here" and "nobody looked" are different
facts, and a 0.0 would collapse them.
"""

import geopandas as gpd
from shapely.geometry import box

import national_metrics


def _cells():
    return gpd.GeoDataFrame(
        {"geometry": [box(-83.2, 40.0, -83.1, 40.1),
                      box(-83.1, 40.0, -83.0, 40.1)]},
        crs="EPSG:4326")


def test_failed_layers_leave_keys_absent_not_zero(monkeypatch):
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

    out = national_metrics.measure(_cells(), -83.2, 40.0, -83.0, 40.1, "OH")
    assert out == [{}, {}], "a failed layer must contribute no key at all"


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

    out = national_metrics.measure(_cells(), -83.2, 40.0, -83.0, 40.1, "OH")
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

    out = national_metrics.measure(_cells(), -83.2, 40.0, -83.0, 40.1, "OH")
    for cell in out:
        for key, value in cell.items():
            assert key.endswith(("_pct", "_km")), key
            assert value is None or isinstance(value, (int, float)), key
