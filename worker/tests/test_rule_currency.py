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
