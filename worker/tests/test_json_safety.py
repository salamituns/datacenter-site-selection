"""
NaN must never reach the JSON encoder.

This is the defect this pipeline has shipped most often — three separate
times, in three different places, each after a complete and otherwise
successful run:

  1. parcel record and metric values,
  2. `int(column.max())` on an all-NaN region log line,
  3. three interconnection fields where only one was guarded.

The root cause is the same every time. pandas yields NaN wherever a source
had nothing, NaN is a float rather than None so `x is None` waves it
through, and `float('nan')` serialises to a bare `NaN` token that is not
valid JSON. The publish then dies at the very end, having done all the work.
"""

import math

import numpy as np
import pandas as pd
import pytest

from parcel_gates import _json_safe, _num


class TestNum:
    def test_none_stays_none(self):
        assert _num(None) is None

    @pytest.mark.parametrize(
        "value",
        [float("nan"), np.nan, float("inf"), float("-inf"), np.float64("nan")],
        ids=["float-nan", "np-nan", "inf", "-inf", "np-float64-nan"],
    )
    def test_non_finite_becomes_none(self, value):
        assert _num(value) is None

    def test_pandas_missing_becomes_none(self):
        # The actual shape the bug arrived in: a column with a gap.
        s = pd.Series([1.5, None, 3.0])
        assert _num(s.iloc[1]) is None
        assert _num(s.iloc[0]) == 1.5

    def test_nan_is_not_none_which_is_the_whole_problem(self):
        # Pinning the premise, so the guard is never "simplified" back into
        # an `is None` check.
        assert np.nan is not None
        assert math.isnan(float(np.nan))

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0, 0.0), (0.0, 0.0), (-12.5, -12.5), ("3.25", 3.25), (np.float64(7), 7.0)],
    )
    def test_real_values_survive(self, value, expected):
        assert _num(value) == expected

    def test_zero_is_kept_not_treated_as_missing(self):
        # Zero is a finding ("nothing here"), absence is a gap. Collapsing
        # them is a separate bug this project has also had to fix.
        assert _num(0) == 0.0
        assert _num(0) is not None

    @pytest.mark.parametrize("value", ["", "abc", object(), [], {}])
    def test_unparseable_becomes_none(self, value):
        assert _num(value) is None


class TestJsonSafe:
    def test_nan_inside_a_dict(self):
        assert _json_safe({"assessed": float("nan")}) == {"assessed": None}

    def test_nan_nested_deeply(self):
        payload = {"roll": {"years": [{"value": float("nan")}, {"value": 2.0}]}}
        assert _json_safe(payload) == {
            "roll": {"years": [{"value": None}, {"value": 2.0}]}
        }

    def test_tuples_become_lists(self):
        # jsonb has no tuple; leaving one through fails at encode time.
        assert _json_safe(("a", float("inf"))) == ["a", None]

    def test_non_float_values_pass_through_untouched(self):
        payload = {"basis": "GIS geometry", "n": 4, "ok": True, "missing": None}
        assert _json_safe(payload) == payload

    def test_output_is_actually_encodable(self):
        # The real contract. Everything above is a proxy for this.
        import json

        payload = {
            "assessed": float("nan"),
            "rows": [float("inf"), 1.0, None],
            "nested": {"deep": {"v": float("-inf")}},
        }
        encoded = json.dumps(_json_safe(payload))
        assert "NaN" not in encoded
        assert "Infinity" not in encoded
        json.loads(encoded)  # round-trips
