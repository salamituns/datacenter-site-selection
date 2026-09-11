"""
The underwriting cost model — arithmetic, provenance, and refusals.

Everything in `underwriting` is modelled rather than observed, which is why
it lives apart from the evidence layers and why these tests check three
different things:

  * the arithmetic, because an estimate nobody can reproduce is not an
    estimate;
  * the provenance, because the module's stated rule is that an estimated
    metric never travels alone — it carries the assumption key and version
    that priced it, the formula, and the observed inputs it came from;
  * the refusals, because the failure that matters here is not a wrong
    number but a confident one. A site with unsampled slope must price at
    nothing rather than at an area-only figure that looks just as sure.

Assumption dicts are built inline rather than read from `cost_assumptions`,
so a repricing in the database is a business decision and not a test
failure. The values mirror the live rows: Loudoun VA at $0.805 per $100
over five years, Franklin OH at $1.50 over three, and site prep at $3,000
per acre clearing / $6.54 per cubic yard earthwork with a 100-acre pad cap.
"""

import math

import pytest

from underwriting import (
    CUFT_PER_CY,
    SQFT_PER_ACRE,
    _graded_cut_cy,
    rollback_tax_exposure,
    site_prep_cost,
)


def rollback_assumption(rate_per_100, years, jurisdiction="Loudoun County, VA",
                        statute="Code of Virginia 58.1-3237", excludes=None):
    return {
        "assumption_key": "land_use_rollback",
        "assumption_version": "v1",
        "basis": f"{jurisdiction} adopted rate and statutory recoupment period",
        "source_url": "https://example.invalid/statute",
        "source_org": jurisdiction,
        "params": {
            "tax_rate_per_100_usd": rate_per_100,
            "rollback_years": years,
            "statute": statute,
            "excludes": excludes if excludes is not None else ["statutory simple interest"],
        },
    }


VA_ROLLBACK = rollback_assumption(0.805, 5)
OH_ROLLBACK = rollback_assumption(
    1.5, 3, "Franklin County, OH", "Ohio Revised Code 5713.34",
    ["interest and penalties on the recoupment charge"],
)

SITE_PREP = {
    "assumption_key": "site_prep",
    "assumption_version": "v2",
    "basis": "non-authoritative pricing guides; placeholder unit costs",
    "source_url": "https://example.invalid/guide",
    "source_org": "pricing guide",
    "params": {
        "clearing_usd_per_acre": 3000,
        "earthwork_usd_per_cy": 6.54,
        "graded_pad_cap_acres": 100,
        "terrace_relief_ft": 12,
        "max_terraces": 4,
        "accuracy_low_pct": -50,
        "accuracy_high_pct": 100,
        "aace_class": 5,
    },
}


# ── roll-back tax exposure ────────────────────────────────────────────

class TestRollbackArithmetic:
    def test_matches_the_stated_formula(self):
        # 1,000,000 * (0.805/100) * 5
        got = rollback_tax_exposure(1_000_000.0, VA_ROLLBACK)
        assert got["value"] == pytest.approx(40_250.0)

    def test_annual_figure_is_reported_alongside_the_total(self):
        got = rollback_tax_exposure(1_000_000.0, VA_ROLLBACK)
        assert got["details"]["annual_deferred_tax_usd"] == pytest.approx(8_050.0)
        assert got["value"] == pytest.approx(
            got["details"]["annual_deferred_tax_usd"] * 5
        )

    def test_jurisdiction_changes_the_answer(self):
        """
        The reason assumptions are scoped rather than global: the same
        deferred value is a different liability in a different state.
        """
        va = rollback_tax_exposure(1_000_000.0, VA_ROLLBACK)["value"]
        oh = rollback_tax_exposure(1_000_000.0, OH_ROLLBACK)["value"]
        assert oh == pytest.approx(45_000.0)   # 1.5/100 * 3 years
        assert va != oh

    def test_scales_linearly_with_deferred_value(self):
        one = rollback_tax_exposure(500_000.0, VA_ROLLBACK)["value"]
        two = rollback_tax_exposure(1_000_000.0, VA_ROLLBACK)["value"]
        assert two == pytest.approx(one * 2)

    def test_zero_deferral_is_a_real_zero_not_a_refusal(self):
        # A parcel assessed at full fair market value has no exposure. That
        # is a finding, and must not be collapsed into "unknown".
        got = rollback_tax_exposure(0.0, VA_ROLLBACK)
        assert got is not None
        assert got["value"] == 0.0


class TestRollbackRefusals:
    def test_no_deferral_recorded_returns_none(self):
        assert rollback_tax_exposure(None, VA_ROLLBACK) is None

    def test_missing_assumption_returns_none_rather_than_guessing(self):
        # The failure mode the assumption ledger exists to prevent: pricing
        # something with a hard-coded rate because the row was absent.
        assert rollback_tax_exposure(1_000_000.0, None) is None


class TestRollbackProvenance:
    def test_carries_the_assumption_that_priced_it(self):
        d = rollback_tax_exposure(1_000_000.0, VA_ROLLBACK)["details"]
        assert d["assumption"] == "land_use_rollback"
        assert d["assumption_version"] == "v1"
        assert d["basis"]

    def test_carries_the_formula_and_its_inputs(self):
        d = rollback_tax_exposure(1_000_000.0, VA_ROLLBACK)["details"]
        assert "deferred_value" in d["formula"]
        assert d["inputs"]["deferred_value_usd"] == 1_000_000.0
        assert d["inputs"]["tax_rate_per_100_usd"] == 0.805
        assert d["inputs"]["rollback_years"] == 5

    def test_exclusions_and_statute_come_from_the_assumption_not_from_code(self):
        """
        Virginia adds a rezoning penalty; Ohio attaches a lien. If these were
        hard-coded, one jurisdiction would be described using the other's law.
        """
        va = rollback_tax_exposure(1.0, VA_ROLLBACK)["details"]
        oh = rollback_tax_exposure(1.0, OH_ROLLBACK)["details"]
        assert va["statute"] == "Code of Virginia 58.1-3237"
        assert oh["statute"] == "Ohio Revised Code 5713.34"
        assert va["excludes"] != oh["excludes"]

    def test_says_what_it_leaves_out(self):
        d = rollback_tax_exposure(1_000_000.0, VA_ROLLBACK)["details"]
        assert d["excludes"], "an estimate must state its exclusions"


# ── earthwork ─────────────────────────────────────────────────────────

class TestGradedCut:
    def test_flat_site_moves_no_earth(self):
        g = _graded_cut_cy(80.0, 0.0, 12.0, 4)
        assert g["cut_cubic_yards"] == 0.0
        assert g["terraces"] == 1

    def test_single_plane_formula_when_one_terrace_suffices(self):
        # Relief under one terrace's worth, so no division applies.
        pad, slope = 1.0, 1.0
        side = (pad * SQFT_PER_ACRE) ** 0.5
        expected = (slope / 100.0) * side ** 3 / 8.0 / CUFT_PER_CY
        g = _graded_cut_cy(pad, slope, 12.0, 4)
        assert g["terraces"] == 1
        assert g["cut_cubic_yards"] == pytest.approx(expected)

    def test_terracing_divides_the_earthwork(self):
        g = _graded_cut_cy(80.0, 4.0, 12.0, 99)
        side = (80.0 * SQFT_PER_ACRE) ** 0.5
        single_plane = (4.0 / 100.0) * side ** 3 / 8.0 / CUFT_PER_CY
        assert g["terraces"] > 1
        assert g["cut_cubic_yards"] == pytest.approx(single_plane / g["terraces"])

    def test_terrace_count_follows_the_relief(self):
        # An 80-acre pad on a 4% grade falls ~75ft; at 12ft a step that is
        # seven terraces wanted.
        g = _graded_cut_cy(80.0, 4.0, 12.0, 99)
        assert g["site_relief_ft"] == pytest.approx(
            (4.0 / 100.0) * (80.0 * SQFT_PER_ACRE) ** 0.5
        )
        assert g["terraces_wanted"] == math.ceil(g["site_relief_ft"] / 12.0)

    def test_cap_is_applied_and_declared(self):
        g = _graded_cut_cy(80.0, 4.0, 12.0, 4)
        assert g["terraces"] == 4
        assert g["terraces_wanted"] > 4
        assert g["terrace_capped"] is True

    def test_uncapped_result_does_not_claim_to_be_capped(self):
        g = _graded_cut_cy(10.0, 0.5, 12.0, 4)
        assert g["terrace_capped"] is False

    def test_past_the_cap_a_steeper_site_moves_more_earth(self):
        """
        The point of capping rather than terracing indefinitely: beyond the
        cap the estimate must stay sensitive to terrain, or every steep site
        would price like a flat one.
        """
        gentle = _graded_cut_cy(80.0, 4.0, 12.0, 4)
        steep = _graded_cut_cy(80.0, 12.0, 12.0, 4)
        assert gentle["terrace_capped"] and steep["terrace_capped"]
        assert steep["cut_cubic_yards"] > gentle["cut_cubic_yards"]


# ── site preparation ──────────────────────────────────────────────────

class TestSitePrepRefusals:
    def test_unsampled_slope_prices_nothing(self):
        """
        The refusal that matters most. Earthwork is most of the cost on any
        site with relief, so an area-only figure would understate a steep
        parcel while looking exactly as confident as a real one.
        """
        assert site_prep_cost(80.0, None, SITE_PREP) is None

    @pytest.mark.parametrize("acres", [None, 0, -5])
    def test_no_developable_area_prices_nothing(self, acres):
        assert site_prep_cost(acres, 4.0, SITE_PREP) is None

    def test_missing_assumption_prices_nothing(self):
        assert site_prep_cost(80.0, 4.0, None) is None


class TestSitePrepArithmetic:
    def test_reproduces_clearing_plus_earthwork(self):
        pad, slope = 50.0, 2.0
        g = _graded_cut_cy(pad, slope, 12.0, 4)
        expected_base = pad * 3000 + g["cut_cubic_yards"] * 6.54
        got = site_prep_cost(pad, slope, SITE_PREP)
        assert got["base"] == pytest.approx(expected_base, rel=1e-6)

    def test_applies_the_aace_class_5_band_not_an_invented_one(self):
        # 18R-97 gives Class 5 an accuracy of -50% / +100%.
        got = site_prep_cost(50.0, 2.0, SITE_PREP)
        assert got["low"] == pytest.approx(got["base"] * 0.5, rel=1e-6)
        assert got["high"] == pytest.approx(got["base"] * 2.0, rel=1e-6)

    def test_never_returns_a_point_estimate(self):
        got = site_prep_cost(50.0, 2.0, SITE_PREP)
        assert got["low"] < got["base"] < got["high"]

    def test_pad_is_capped_so_acreage_stops_buying_cost(self):
        big = site_prep_cost(500.0, 2.0, SITE_PREP)
        at_cap = site_prep_cost(100.0, 2.0, SITE_PREP)
        assert big["base"] == pytest.approx(at_cap["base"])
        assert big["details"]["inputs"]["graded_pad_acres"] == 100

    def test_terrain_changes_the_price_for_equal_acreage(self):
        """
        The claim the model is built to support: two sites of the same size
        and different terrain price differently, which a flat per-acre rate
        could never show.
        """
        flat = site_prep_cost(80.0, 0.5, SITE_PREP)
        steep = site_prep_cost(80.0, 12.0, SITE_PREP)
        assert steep["base"] > flat["base"]

    def test_a_flat_site_still_costs_clearing(self):
        got = site_prep_cost(80.0, 0.0, SITE_PREP)
        assert got["base"] == pytest.approx(80.0 * 3000)


class TestSitePrepProvenance:
    def test_names_the_standard_it_applies(self):
        d = site_prep_cost(50.0, 2.0, SITE_PREP)["details"]
        assert "18R-97" in d["method"]
        assert "Class 5" in d["method"]

    def test_carries_the_assumption_key_and_version(self):
        d = site_prep_cost(50.0, 2.0, SITE_PREP)["details"]
        assert d["assumption"] == "site_prep"
        assert d["assumption_version"] == "v2"

    def test_carries_the_observed_inputs_it_was_computed_from(self):
        d = site_prep_cost(80.0, 4.0, SITE_PREP)["details"]
        assert d["inputs"]["developable_acres"] == pytest.approx(80.0)
        assert d["inputs"]["graded_pad_acres"] == pytest.approx(80.0)

    def test_carries_a_formula_a_reader_can_take_apart(self):
        d = site_prep_cost(50.0, 2.0, SITE_PREP)["details"]
        assert "clearing" in d["formula"] and "earthwork" in d["formula"]

    def test_result_is_json_encodable(self):
        import json

        json.dumps(site_prep_cost(50.0, 2.0, SITE_PREP))
        json.dumps(rollback_tax_exposure(1_000_000.0, VA_ROLLBACK))


# ── provider attribution (water) ──────────────────────────────────────

class TestProviderAttribution:
    """
    Beside the statute test, for the same reason: a rationale that names
    the wrong authority describes one jurisdiction using another's facts.
    The water gate used to hard-code Loudoun Water, so wiring a second
    utility would have given Ohio parcels a rationale reading "Inside
    Loudoun Water's published service area" — the same class of error as
    describing Virginia with Ohio's statute. Two regions, two utilities,
    and neither output naming the other's.
    """

    @staticmethod
    def _layer(rows):
        """A normalized water layer (the water_evidence contract)."""
        import geopandas as gpd
        from shapely.geometry import box

        from parcel_gates import M2_PER_ACRE, PLANAR_CRS

        geoms, attrs = [], []
        for slot, r in enumerate(rows):
            side = (150.0 * M2_PER_ACRE) ** 0.5
            minx = slot * 4_000.0
            geoms.append(box(minx, 0, minx + side + 40, side + 40))
            attrs.append(r)
        gdf = gpd.GeoDataFrame(attrs, geometry=geoms, crs=PLANAR_CRS)
        return gdf.to_crs("EPSG:4326")

    @staticmethod
    def _parcels(n):
        import geopandas as gpd
        from shapely.geometry import box

        from parcel_gates import M2_PER_ACRE, PLANAR_CRS

        side = (150.0 * M2_PER_ACRE) ** 0.5
        return gpd.GeoDataFrame(
            {"pin": [f"P{i}" for i in range(n)],
             "legal_acreage": [150.0] * n,
             "geometry": [box(i * 4_000.0 + 20, 20,
                              i * 4_000.0 + side, side) for i in range(n)]},
            crs=PLANAR_CRS,
        ).to_crs("EPSG:4326")

    def _run(self, region_key, county, layer, n_parcels):
        from parcel_gates import qualify_parcels

        _, metrics, gates, _ = qualify_parcels(
            parcels_gdf=self._parcels(n_parcels), zoning_gdf=None,
            wetlands_gdf=None, nfhl_gdf=None, lines_gdf=None, subs_gdf=None,
            water_gdf=layer, region_key=region_key,
            rules={}, state_code=region_key.split("-")[0], county_name=county,
            snapshots={}, retrieve_time="2026-09-11T00:00:00+00:00",
        )
        self._last_gates = gates
        texts = [g["rationale"] for g in gates
                 if g["gate_key"] == "water_availability"]
        texts += [m["text_value"] for m in metrics
                  if m["metric_key"] in ("water_service_provider",
                                         "wastewater_service_provider")]
        return texts

    def test_loudoun_outputs_never_name_the_licking_utility(self):
        layer = self._layer([
            {"area_name": "Central System", "service_type": "Both",
             "comment": None, "provider": "Loudoun Water",
             "last_edited": "2025-11-02", "edited_basis": "service_edit_timestamp",
             "edited_note": None, "not_served": False},
            {"area_name": "NOT Served by LW", "service_type": "W",
             "comment": None, "provider": "Loudoun Water",
             "last_edited": "2025-11-02", "edited_basis": "service_edit_timestamp",
             "edited_note": None, "not_served": True},
        ])
        texts = self._run("VA-LOUDOUN", "Loudoun", layer, 2)
        assert any("Loudoun Water" in t for t in texts)
        assert not any(("Licking" in t) or ("SWLCWSD" in t)
                       or ("Pataskala" in t) for t in texts), texts

    def test_licking_outputs_never_name_loudoun_water(self):
        layer = self._layer([
            # Row-level provider: the district's own polygon.
            {"area_name": "SWLCWSD", "service_type": "W",
             "comment": None, "provider": "Licking Regional Water District (formerly SWLCWSD)",
             "last_edited": "2021-06", "edited_basis": "layer_vintage",
             "edited_note": "the layer's own name (Water_Service_2021, "
                            "June 2021); the service exposes no edit timestamp",
             "not_served": False},
            # Row-level provider: the city's polygon — never attributed to
            # the district just because the district publishes the layer.
            {"area_name": "Pataskala Utility Department", "service_type": "W",
             "comment": None, "provider": "Pataskala Utility Department",
             "last_edited": "2021-06", "edited_basis": "layer_vintage",
             "edited_note": "the layer's own name (Water_Service_2021, "
                            "June 2021); the service exposes no edit timestamp",
             "not_served": False},
        ])
        texts = self._run("OH-LICKING", "Licking", layer, 2)
        assert not any("Loudoun" in t for t in texts), texts
        # The row-level provider appears, and the two parcels carry
        # different utilities from the same layer.
        assert any("Licking Regional Water District" in t for t in texts)
        assert any("Pataskala Utility Department" in t for t in texts)
        # The vintage is stated, never "edited None": the dated clause
        # must carry the layer's own explanation.
        assert any("boundary dated 2021-06" in t for t in texts)
        assert not any("edited None" in t for t in texts), texts

    def test_an_absent_comment_is_none_not_an_empty_string(self):
        # The no-new-connections branch reads that text; "" would read as
        # a utility that said nothing only by accident. A None comment
        # must not trigger the CONDITIONAL branch or render in the text.
        layer = self._layer([
            {"area_name": "SWLCWSD", "service_type": "W",
             "comment": None, "provider": "Licking Regional Water District (formerly SWLCWSD)",
             "last_edited": "2021-06", "edited_basis": "layer_vintage",
             "edited_note": "vintage from the layer name", "not_served": False},
        ])
        texts = self._run("OH-LICKING", "Licking", layer, 1)
        gate_rows = self._last_gates
        wg = [g for g in gate_rows if g["gate_key"] == "water_availability"]
        assert wg and all(g["status"] == "PASS" for g in wg), wg
        assert not any('states: ""' in t or 'states: "None"' in t for t in texts), texts
