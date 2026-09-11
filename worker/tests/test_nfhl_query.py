"""
_paged_query's geometry_precision — the NFHL serializer workaround.

At least one NFHL feature (observed in Prince William County, VA,
2026-09-11) carries coordinate precision that makes FEMA's GeoJSON
serializer 500 on every query returning that feature — deterministically,
independent of paging depth — so the flood tiler's subdivision can never
outgrow it and one feature concedes the floodway gate for a whole county.
geometryPrecision=6 (≈0.1 m, below the data's own accuracy; it rounds the
serialized output, not the source geometries) makes the same query return
200. These tests pin the parameter into every page of a paged NFHL fetch
with a faked session, so the workaround cannot silently drop out.
"""

import overlay_layers
from overlay_layers import _paged_query


def _page(features, exceeded=False):
    return {"features": features, "exceededTransferLimit": exceeded}


def _feature(oid):
    return {"type": "Feature", "id": oid,
            "properties": {"OBJECTID": oid},
            "geometry": {"type": "Polygon", "coordinates": [
                [[0, 0], [1, 0], [1, 1], [0, 0]]]}}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    """Replays one payload per call, recording every page's params."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return _FakeResponse(self._payloads.pop(0))


def test_geometry_precision_sent_on_every_page():
    session = _FakeSession([
        _page([_feature(1), _feature(2)], exceeded=True),
        _page([_feature(3)]),  # short page ends the fetch
    ])
    out = _paged_query(
        session, "https://example.gov/query", "0,0,1,1",
        out_fields="OBJECTID", page_size=2, geometry_precision=6,
    )
    assert [f["id"] for f in out] == [1, 2, 3]
    assert len(session.calls) == 2
    for params in session.calls:
        assert params["geometryPrecision"] == "6"


def test_geometry_precision_omitted_by_default():
    session = _FakeSession([_page([_feature(1)])])
    _paged_query(session, "https://example.gov/query", "0,0,1,1",
                 out_fields="OBJECTID")
    assert "geometryPrecision" not in session.calls[0]


def test_nfhl_fetcher_passes_precision_downstream():
    # The NFHL call site is the one that needs it; if the wiring between
    # fetch_nfhl_floodzones' tiler and _paged_query loses the parameter,
    # Prince William's floodway gate concedes UNKNOWN again.
    import inspect

    src = inspect.getsource(overlay_layers._nfhl_tiled_query)
    assert "geometry_precision=6" in src, (
        "fetch_nfhl_floodzones' tiled query must send geometryPrecision=6"
    )
