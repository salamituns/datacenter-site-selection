"""
Rules are evidence, and evidence states how old it is.

Loudoun's use table was named `2023-ord+2025-zoam` and listed IP, GI and
MR-HI as by-right. ZOAM-2024-0001 had removed exactly that in March 2025.
The rule claimed an amendment it did not reflect and decided 119 parcels for
months before anyone read the ordinance again.

No version-drift check would have caught it: the corrected rule and the
republish landed together, so nothing was ever out of step with itself. What
was missing is that `constraint_rules` was the only evidence in the engine
with no retrieved-at — every metric records when its source was read, while
the rules deciding those metrics recorded only when the row was inserted.

These pin the two mechanisms that replaced that gap.
"""

import logging

import pytest

from runs import _log_rule_currency, _rows_to_rules


def row(gate_key, version, reviewed_at=None, reviewed_against=None):
    return {
        "id": f"id-{gate_key}-{version}",
        "gate_key": gate_key,
        "rule_version": version,
        "params": {"x": 1},
        "reviewed_at": reviewed_at,
        "reviewed_against": reviewed_against,
    }


class TestRowsToRules:
    def test_carries_review_provenance_through(self):
        rules = _rows_to_rules([
            row("zoning_dc_use", "2026-ord-reviewed", "2026-09-11",
                "Loudoun Zoning Ordinance as amended by ZOAM-2024-0001")])
        r = rules["zoning_dc_use"]
        assert r["reviewed_at"] == "2026-09-11"
        assert "ZOAM-2024-0001" in r["reviewed_against"]

    def test_a_rule_with_no_review_carries_none_not_a_placeholder(self):
        # The absence must stay legible. A default date here would be the
        # same lie the rule version itself told.
        rules = _rows_to_rules([row("slope", "v1")])
        assert rules["slope"]["reviewed_at"] is None

    def test_rule_id_is_stringified_for_the_gate_rows(self):
        rules = _rows_to_rules([row("slope", "v1")])
        assert isinstance(rules["slope"]["id"], str)


class TestCurrencyLogging:
    def test_unreviewed_rules_are_warned_about_by_name(self, caplog):
        rules = _rows_to_rules([
            row("zoning_dc_use", "v2", "2026-09-11", "ordinance"),
            row("slope", "v1"),
            row("wetlands", "v1"),
        ])
        with caplog.at_level(logging.WARNING):
            _log_rule_currency("Loudoun County, VA", rules)
        warnings = [r.getMessage() for r in caplog.records
                    if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        assert "slope" in warnings[0] and "wetlands" in warnings[0]
        # The reviewed one must not be reported as unreviewed.
        assert "zoning_dc_use" not in warnings[0]

    def test_review_dates_are_reported_when_present(self, caplog):
        rules = _rows_to_rules([row("zoning_dc_use", "v2", "2026-09-11", "ord")])
        with caplog.at_level(logging.INFO):
            _log_rule_currency("Loudoun County, VA", rules)
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "2026-09-11" in msgs

    def test_fully_reviewed_jurisdiction_raises_no_warning(self, caplog):
        rules = _rows_to_rules([
            row("zoning_dc_use", "v2", "2026-09-11", "ord"),
            row("slope", "v1", "2026-09-01", "3DEP"),
        ])
        with caplog.at_level(logging.WARNING):
            _log_rule_currency("Loudoun County, VA", rules)
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    def test_no_rules_at_all_is_silent_not_a_crash(self, caplog):
        # A jurisdiction whose rules could not be read already fails loudly
        # in qualify_parcels; this must not add a second confusing warning.
        with caplog.at_level(logging.WARNING):
            _log_rule_currency("Nowhere County, ZZ", {})
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


class TestInertRules:
    """
    A rule row whose params the gate never reads decides nothing.

    "Rules are data, not code" is the claim constraint_rules exists to make
    good on, and this failure breaks it silently: the gate finds no key,
    takes its built-in default, and returns a perfectly reasonable verdict
    under a threshold nobody wrote down. Nine rows across three counties were
    in that state — the floodway rows said fail_pct 25 while the gate read
    floodway_fail_pct and applied 0.5.

    The values happened to be the safer ones, which is exactly why it
    survived: the verdicts were right and the stated reasons were fiction.
    """

    def test_a_rule_missing_its_governing_param_is_named(self, caplog):
        from runs import _warn_inert_rules
        rules = _rows_to_rules([
            # The real shape of the defect: floodway params the gate cannot use.
            {"id": "1", "gate_key": "floodway", "rule_version": "v1",
             "params": {"fail_pct": 25, "conditional_pct": 5},
             "reviewed_at": None, "reviewed_against": None}])
        with caplog.at_level(logging.WARNING):
            _warn_inert_rules("Franklin County, OH", rules)
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "floodway" in msgs and "floodway_fail_pct" in msgs

    def test_a_correctly_keyed_rule_raises_nothing(self, caplog):
        from runs import _warn_inert_rules
        rules = _rows_to_rules([
            {"id": "1", "gate_key": "floodway", "rule_version": "v2",
             "params": {"floodway_fail_pct": 0.5, "floodplain_conditional": True},
             "reviewed_at": "2026-09-12", "reviewed_against": "44 CFR 60.3(d)(3)"}])
        with caplog.at_level(logging.WARNING):
            _warn_inert_rules("Franklin County, OH", rules)
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    def test_every_gate_the_engine_decides_has_a_governing_param_declared(self):
        """
        The map must cover the gates, or a gate can go inert unwatched — the
        blind spot would be invisible in exactly the way the original was.
        """
        from parcel_gates import DEFAULT_RULE_PARAMS
        from runs import GATE_GOVERNING_PARAM
        assert set(DEFAULT_RULE_PARAMS) <= set(GATE_GOVERNING_PARAM), (
            "gates with no declared governing param: "
            f"{set(DEFAULT_RULE_PARAMS) - set(GATE_GOVERNING_PARAM)}")

    def test_each_declared_param_exists_in_that_gate_s_defaults(self):
        """
        And the declared key must be one the gate really reads. A typo here
        would report every rule as inert, which is the same silence in
        reverse.
        """
        from parcel_gates import DEFAULT_RULE_PARAMS
        from runs import GATE_GOVERNING_PARAM
        for gate_key, param in GATE_GOVERNING_PARAM.items():
            defaults = DEFAULT_RULE_PARAMS.get(gate_key)
            if defaults is None:
                continue
            assert param in defaults, (
                f"{gate_key}: '{param}' is not a key parcel_gates defaults")

    def test_an_unknown_gate_key_is_ignored_rather_than_flagged(self, caplog):
        from runs import _warn_inert_rules
        rules = _rows_to_rules([
            {"id": "1", "gate_key": "some_future_gate", "rule_version": "v1",
             "params": {"whatever": 1}, "reviewed_at": None,
             "reviewed_against": None}])
        with caplog.at_level(logging.WARNING):
            _warn_inert_rules("Nowhere County, ZZ", rules)
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
