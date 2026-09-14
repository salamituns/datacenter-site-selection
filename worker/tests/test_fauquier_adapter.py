"""
The two Fauquier-specific hazards, both found by probing the live service
before the adapter existed (docs/virginia-expansion-shortlist.md).

Offline: every test builds its own frames.
"""

from shapely.geometry import box, mapping

from fauquier_api import FauquierParcelAPI


# --- ACREAGE is a String, and '0' is not zero acres -----------------------

def test_blank_and_zero_acreage_concede_rather_than_fail():
    """
    The failure this guards: float('0') is a valid number, and zero acres
    FAILS the contiguous-acreage gate. A parcel whose acreage the county
    never recorded must read UNKNOWN, not FAIL.
    """
    a = FauquierParcelAPI._acres
    assert a("0") is None
    assert a(" ") is None
    assert a("") is None
    assert a(None) is None
    assert a("0.0") is None
    assert a("not a number") is None


def test_real_acreage_strings_parse():
    a = FauquierParcelAPI._acres
    assert a("0.777") == 0.777
    assert a("269.8537") == 269.8537
    assert a(" 42.5 ") == 42.5
    assert a(1234.5) == 1234.5


# --- co-extensive interests are one tract, not fifty sites ----------------

def _rows(entries):
    """entries: (pin, acres, (minx, miny, maxx, maxy))"""
    return {pin: {"pin": pin, "legal_acreage": acres, "geometry": box(*bounds)}
            for pin, acres, bounds in entries}


def test_divided_interests_in_one_tract_collapse_to_one_parcel():
    """
    Fauquier stamps the parent tract's acreage on every divided interest.
    Base 7809-78-6301 really carries 50 parcels each claiming 269.85 acres
    over one 263-acre tract: surveyed as published that is 13,493 acres of
    candidate land on 263 acres of ground, and every one clears the gate.
    """
    tract = (-77.80, 38.70, -77.79, 38.71)
    rows = _rows([(f"7809-78-6301-{i:03d}", 269.8537, tract) for i in range(5)])
    out = FauquierParcelAPI._collapse_co_extensive(dict(rows))
    assert len(out) == 1, "five interests in one tract must survey as one parcel"
    kept = next(iter(out.values()))
    assert kept["co_extensive_interests"] == 5
    assert kept["legal_acreage"] == 269.8537


def test_distinct_neighbours_sharing_an_acreage_are_left_alone():
    """
    The error that would be worse than the one above. Two genuinely separate
    parcels under one base, of equal size, must NOT be merged — their union
    is about the sum of them, not about one of them.
    """
    rows = _rows([
        ("6995-89-2285-001", 31.4113, (-77.80, 38.70, -77.79, 38.71)),
        ("6995-89-2285-002", 31.4113, (-77.78, 38.70, -77.77, 38.71)),
    ])
    out = FauquierParcelAPI._collapse_co_extensive(dict(rows))
    assert len(out) == 2, "disjoint neighbours are two parcels, not one"
    assert all("co_extensive_interests" not in r for r in out.values())


def test_parcels_under_different_bases_never_collapse():
    rows = _rows([
        ("7809-78-6301-001", 100.0, (-77.80, 38.70, -77.79, 38.71)),
        ("1234-56-7890-001", 100.0, (-77.80, 38.70, -77.79, 38.71)),
    ])
    out = FauquierParcelAPI._collapse_co_extensive(dict(rows))
    assert len(out) == 2, "a shared footprint under different bases is not one tract"


def test_a_lone_parcel_is_untouched():
    rows = _rows([("7809-78-6301-001", 269.85, (-77.80, 38.70, -77.79, 38.71))])
    out = FauquierParcelAPI._collapse_co_extensive(dict(rows))
    assert len(out) == 1
    assert "co_extensive_interests" not in next(iter(out.values()))
