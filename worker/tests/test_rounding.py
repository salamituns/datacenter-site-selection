"""
Python and Postgres must round the same way.

These figures are cross-checked against the database sooner or later, and
the two answers have to agree. This project has been bitten twice:

  1. an RTEP schedule-slip p90 that read 47 in Python and 48 in SQL, which
     is what `_round_half_away` was written for;
  2. two Loudoun screening cells at 70.00 x 0.995 = 69.65 exactly, where
     numpy's half-to-even wrote 69.6 and the generated column's SQL
     `round()` writes 69.7 — caught by the phase-2 gate query in
     docs/unrisked-composite-spec.md.

Postgres `round(numeric)` is half away from zero. Python's builtin
`round()` and numpy's `.round()` are half to even. They differ only on
exact halves, which is precisely why the disagreement survives casual
testing.
"""

import numpy as np
import pytest

from parcel_gates import _round_half_away


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.5, 1), (1.5, 2), (2.5, 3), (3.5, 4),   # SQL rounds every .5 up
        (-0.5, -1), (-1.5, -2), (-2.5, -3),        # and away from zero below it
        (47.5, 48),                                # the RTEP p90 that started it
        (0.4, 0), (0.6, 1), (-0.4, 0), (-0.6, -1),
        (0.0, 0), (12.0, 12), (-12.0, -12),
    ],
)
def test_matches_postgres_numeric_rounding(value, expected):
    assert _round_half_away(value) == expected


@pytest.mark.parametrize("half", [0.5, 2.5, 4.5, -0.5, -2.5, -4.5])
def test_differs_from_half_to_even_where_the_result_would_be_odd(half):
    """
    The behaviour is deliberate, so pin the divergence itself. If a future
    change makes these agree, `_round_half_away` has silently become
    banker's rounding and the SQL parity is gone.

    The two conventions only disagree when rounding away from zero lands on
    an odd number: 2.5 goes to 3 in SQL and to 2 under half-to-even. Where
    it lands on an even number they agree, which is what makes this class of
    bug so durable — most exact halves you happen to try look fine.
    """
    assert _round_half_away(half) != int(np.round(half))


@pytest.mark.parametrize("half", [1.5, 3.5, 47.5, -1.5, -3.5])
def test_agrees_with_half_to_even_where_the_result_would_be_even(half):
    """
    The other half of the same rule.

    47.5 is here deliberately: half-to-even and half-away both give 48, so
    the RTEP p90 bug was not a banker's-rounding bug at all — it was `int()`
    truncating to 47. Two different ways to disagree with SQL, and only one
    of them is visible from this comparison, which is why the truncation
    case is pinned separately below.
    """
    assert _round_half_away(half) == int(np.round(half))


def test_never_truncates_like_int():
    # int() truncates toward zero; that was the other half of the original bug.
    assert _round_half_away(-1.6) == -2
    assert int(-1.6) == -1
