"""
End-to-end gate verdicts over a synthetic county.

`qualify_parcels` is the function every gate verdict flows through, and the
one place a subtle regression is most expensive: a wrong answer here is a
wrong recommendation about real land, carried into cost, schedule and risk
downstream.

The county below is synthetic rather than recorded so that each parcel's
correct verdict is known by construction — a parcel is built to sit 40% in
a wetland, or on a 30% slope, or in a residential zone — and the assertion
is the rule applied to that fact, not a value copied from a previous run.
A recorded fixture would pin whatever the code did on the day it was
recorded, including any bug.

Parcels are constructed in EPSG:32618, the same UTM zone the gates measure
in, so stated acreages are exact rather than approximately reprojected.
"""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box, MultiPolygon

from parcel_gates import M2_PER_ACRE, PLANAR_CRS, qualify_parcels

# A patch of UTM 18N inside Loudoun County.
ORIGIN_X, ORIGIN_Y = 280_000.0, 4_330_000.0
SPACING = 4_000.0  # metres between parcel centres — far enough not to abut


def square(acres: float, slot: int):
    """A square parcel of exactly `acres`, isolated in its own slot."""
    side = (acres * M2_PER_ACRE) ** 0.5
    cx = ORIGIN_X + slot * SPACING
    cy = ORIGIN_Y
    return box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)


def strip_over(geom, fraction: float):
    """A band covering `fraction` of `geom`, anchored on its western edge."""
    minx, miny, maxx, maxy = geom.bounds
    return box(minx, miny, minx + (maxx - minx) * fraction, maxy)


# ── the county ────────────────────────────────────────────────────────
# slot: pin, acres, zone, and what makes it interesting.
PARCELS = [
    ("CLEAN", 150.0, "PDGI"),        # by-right, large, unencumbered
    ("MIDSIZE", 50.0, "PDGI"),       # between the acreage thresholds
    ("SMALL", 10.0, "PDGI"),         # below the conditional floor
    ("WET", 150.0, "PDGI"),          # 40% wetland
    ("WETLIGHT", 150.0, "PDGI"),     # 10% wetland
    ("FLOODWAY", 150.0, "PDGI"),     # 5% regulatory floodway
    ("PROTECTED", 150.0, "PDGI"),    # 20% PAD-US
    ("STEEP", 150.0, "PDGI"),        # 30% max slope
    ("HOUSES", 150.0, "R1"),         # prohibited zone
    ("TOWN", 150.0, "TOWNS"),        # town jurisdiction
    ("NOSLOPE", 150.0, "PDGI"),      # no 3DEP sample for this parcel
]


@pytest.fixture(scope="module")
def result():
    geoms = {pin: square(acres, i) for i, (pin, acres, _) in enumerate(PARCELS)}

    parcels = gpd.GeoDataFrame(
        {
            "pin": [p for p, _, _ in PARCELS],
            "legal_acreage": [a for _, a, _ in PARCELS],
            "geometry": [geoms[p] for p, _, _ in PARCELS],
        },
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")

    zoning = gpd.GeoDataFrame(
        {
            "zone": [z for _, _, z in PARCELS],
            "zone_name": [f"{z} district" for _, _, z in PARCELS],
            "ordinance": ["2023"] * len(PARCELS),
            # Slightly larger than the parcel so the overlay is unambiguous.
            "geometry": [geoms[p].buffer(50) for p, _, _ in PARCELS],
        },
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")

    wetlands = gpd.GeoDataFrame(
        {"geometry": [strip_over(geoms["WET"], 0.40),
                      strip_over(geoms["WETLIGHT"], 0.10)]},
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")

    nfhl = gpd.GeoDataFrame(
        {
            "zone_subty": ["FLOODWAY"],
            "fld_zone": ["AE"],
            "geometry": [strip_over(geoms["FLOODWAY"], 0.05)],
        },
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")

    padus = gpd.GeoDataFrame(
        {"geometry": [strip_over(geoms["PROTECTED"], 0.20)]}, crs=PLANAR_CRS
    ).to_crs("EPSG:4326")

    # A transmission line and substation near the clean parcel, and a road
    # running the length of the county a short distance north of everything.
    lines = gpd.GeoDataFrame(
        {"geometry": [LineString([(ORIGIN_X - 5_000, ORIGIN_Y + 800),
                                  (ORIGIN_X + 60_000, ORIGIN_Y + 800)])]},
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")
    subs = gpd.GeoDataFrame(
        {"geometry": [Point(ORIGIN_X, ORIGIN_Y + 1_000)]}, crs=PLANAR_CRS
    ).to_crs("EPSG:4326")
    roads = gpd.GeoDataFrame(
        {
            "road_class": ["primary"],
            "geometry": [LineString([(ORIGIN_X - 5_000, ORIGIN_Y + 600),
                                     (ORIGIN_X + 60_000, ORIGIN_Y + 600)])],
        },
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")

    # (max, median, n_samples, retrieved_at) — NOSLOPE is deliberately absent.
    idx = {pin: i for i, (pin, _, _) in enumerate(PARCELS)}
    slopes = {
        i: (30.0, 12.0, 900, None) if pin == "STEEP" else (4.0, 2.0, 900, None)
        for pin, i in idx.items()
        if pin != "NOSLOPE"
    }

    records, metrics, gates, stats = qualify_parcels(
        parcels_gdf=parcels,
        zoning_gdf=zoning,
        wetlands_gdf=wetlands,
        nfhl_gdf=nfhl,
        lines_gdf=lines,
        subs_gdf=subs,
        # The synthetic county states its own use table rather than
        # borrowing one: the engine refuses a zoning layer with no
        # zoning_dc_use row precisely because the built-in default used to
        # be Loudoun's, and a borrowed verdict is what these tests exist
        # to make impossible. Other gates still exercise the shipped
        # DEFAULT_RULE_PARAMS.
        rules={"zoning_dc_use": {"params": {
            "by_right": ["PDGI"],
            "special_exception": [],
            "prohibited": ["R1"],
            "unknown_jurisdiction": ["TOWNS"],
        }}},
        state_code="VA",
        county_name="Loudoun",
        snapshots={},
        retrieve_time="2026-09-10T00:00:00+00:00",
        roads_gdf=roads,
        padus_gdf=padus,
        slopes=slopes,
    )
    return {
        "records": records,
        "metrics": metrics,
        "gates": pd.DataFrame(gates),
        "stats": stats,
    }


def verdict(result, pin: str, gate: str) -> str:
    g = result["gates"]
    row = g[(g["parcel_key"] == f"VA-LOUDOUN-{pin}") & (g["gate_key"] == gate)]
    assert len(row) == 1, f"expected exactly one {gate} verdict for {pin}, got {len(row)}"
    return row["status"].iloc[0]


class TestShape:
    def test_every_parcel_is_recorded(self, result):
        assert len(result["records"]) == len(PARCELS)
        assert result["stats"]["parcels_qualified"] == len(PARCELS)

    def test_every_parcel_gets_every_gate_exactly_once(self, result):
        g = result["gates"]
        per_parcel = g.groupby("parcel_key")["gate_key"].nunique()
        assert per_parcel.nunique() == 1, "parcels disagree on how many gates they have"
        assert not g.duplicated(["parcel_key", "gate_key"]).any()

    def test_no_gate_status_is_invented(self, result):
        # The database CHECK constraint allows exactly these.
        assert set(result["gates"]["status"]) <= {
            "PASS", "CONDITIONAL", "FAIL", "UNKNOWN"
        }

    def test_gis_acreage_is_measured_not_copied_from_the_stated_value(self, result):
        by_pin = {r["source_parcel_id"]: r for r in result["records"]}
        assert by_pin["CLEAN"]["gis_acreage"] == pytest.approx(150.0, rel=1e-3)
        assert by_pin["SMALL"]["gis_acreage"] == pytest.approx(10.0, rel=1e-3)


class TestAcreageGate:
    @pytest.mark.parametrize(
        ("pin", "expected"),
        [("CLEAN", "PASS"), ("MIDSIZE", "CONDITIONAL"), ("SMALL", "FAIL")],
    )
    def test_thresholds(self, result, pin, expected):
        # DEFAULT_RULE_PARAMS: pass >= 100 acres, conditional >= 25.
        assert verdict(result, pin, "contiguous_acreage") == expected


class TestOverlapGates:
    def test_heavy_wetland_fails(self, result):
        # 40% > the 30% fail threshold.
        assert verdict(result, "WET", "wetlands") == "FAIL"

    def test_light_wetland_is_conditional_not_fatal(self, result):
        # 10% is over the 5% conditional threshold, under the 30% fail one.
        assert verdict(result, "WETLIGHT", "wetlands") == "CONDITIONAL"

    def test_clean_parcel_passes_wetlands(self, result):
        assert verdict(result, "CLEAN", "wetlands") == "PASS"

    def test_regulatory_floodway_fails(self, result):
        # 5% is well over the 0.5% floodway threshold.
        assert verdict(result, "FLOODWAY", "floodway") == "FAIL"

    def test_protected_land_fails(self, result):
        assert verdict(result, "PROTECTED", "protected_land") == "FAIL"

    def test_overlap_percentages_are_reported_on_the_verdict(self, result):
        g = result["gates"]
        row = g[(g["parcel_key"] == "VA-LOUDOUN-WET") & (g["gate_key"] == "wetlands")]
        assert row["affected_area_pct"].iloc[0] == pytest.approx(40.0, abs=0.5)

    def test_an_unaffected_parcel_is_not_charged_a_neighbours_overlap(self, result):
        # The bug an unindexed or mis-keyed overlap would produce.
        assert verdict(result, "CLEAN", "protected_land") == "PASS"
        assert verdict(result, "CLEAN", "floodway") == "PASS"


class TestSlopeGate:
    def test_steep_parcel_fails(self, result):
        assert verdict(result, "STEEP", "slope") == "FAIL"

    def test_gentle_parcel_passes(self, result):
        assert verdict(result, "CLEAN", "slope") == "PASS"

    def test_unsampled_parcel_is_unknown_not_passed(self, result):
        # The rule that matters most: absent evidence never earns a PASS.
        assert verdict(result, "NOSLOPE", "slope") == "UNKNOWN"


class TestZoningGate:
    def test_by_right_district_passes(self, result):
        assert verdict(result, "CLEAN", "zoning_dc_use") == "PASS"

    def test_prohibited_district_fails(self, result):
        assert verdict(result, "HOUSES", "zoning_dc_use") == "FAIL"

    def test_town_jurisdiction_is_unknown(self, result):
        # Towns are governed by their own ordinance, which this layer does
        # not carry — so the honest answer is that we do not know.
        assert verdict(result, "TOWN", "zoning_dc_use") == "UNKNOWN"


class TestAbsentEvidenceNeverPasses:
    """
    Every layer the caller did not supply must land as UNKNOWN, never as a
    favourable default. These layers were all omitted from the fixture.
    """

    @pytest.mark.parametrize("gate", ["power_capacity", "water_availability"])
    def test_missing_layer_yields_unknown_for_every_parcel(self, result, gate):
        statuses = set(
            result["gates"].loc[result["gates"]["gate_key"] == gate, "status"]
        )
        assert statuses == {"UNKNOWN"}, f"{gate} without evidence returned {statuses}"

    def test_stats_report_the_missing_layers_honestly(self, result):
        assert result["stats"]["water_layer"] == "missing"
        assert result["stats"]["utility_layer"] == "missing"
        assert result["stats"]["padus_layer"] == "present"
        assert result["stats"]["nfhl_layer"] == "present"


class TestMetricsAreSerialisable:
    def test_no_nan_reaches_the_metric_rows(self, result):
        import math

        for m in result["metrics"]:
            v = m["value"]
            assert v is None or not (math.isnan(v) or math.isinf(v)), m

    def test_metric_payloads_encode_as_json(self, result):
        import json

        json.dumps(result["metrics"])  # details is written to jsonb verbatim

    def test_every_metric_carries_a_retrieval_time(self, result):
        assert all(m["retrieved_at"] for m in result["metrics"])


class TestZoningRuleRefusal:
    """
    A zoning layer with no zoning_dc_use row for its own jurisdiction is a
    refusal, not a fallback. The built-in default was Loudoun's use table;
    a county whose codes collide with it (an unhyphenated R4 where the
    ordinance writes R-4) would get a confident verdict citing one
    county's ordinance while the decision came from another's table. The
    refusal is what makes that path unreachable.
    """

    def _county(self, zone="R4"):
        acres = 150.0
        side = (acres * M2_PER_ACRE) ** 0.5
        parcels = gpd.GeoDataFrame(
            {"pin": ["P1"], "legal_acreage": [acres],
             "geometry": [box(0, 0, side, side)]},
            crs=PLANAR_CRS,
        ).to_crs("EPSG:4326")
        zoning = gpd.GeoDataFrame(
            {"zone": [zone], "zone_name": [f"{zone} district"],
             "ordinance": ["2026"], "geometry": [box(-10, -10, side + 10, side + 10)]},
            crs=PLANAR_CRS,
        ).to_crs("EPSG:4326")
        return parcels, zoning

    def _qualify(self, parcels, zoning, rules):
        return qualify_parcels(
            parcels_gdf=parcels, zoning_gdf=zoning,
            wetlands_gdf=None, nfhl_gdf=None, lines_gdf=None, subs_gdf=None,
            rules=rules, state_code="VA", county_name="Prince William",
            snapshots={}, retrieve_time="2026-09-11T00:00:00+00:00",
        )

    def test_zoning_layer_without_a_rule_row_is_refused(self):
        parcels, zoning = self._county()
        with pytest.raises(ValueError, match="zoning_dc_use"):
            self._qualify(parcels, zoning, rules={})

    def test_zoning_layer_with_its_own_rule_row_proceeds(self):
        # The row exists, the district is prohibited by the county's own
        # table, and the verdict is the county's — not a borrowed one.
        parcels, zoning = self._county()
        _, _, gates, _ = self._qualify(
            parcels, zoning,
            rules={"zoning_dc_use": {"params": {
                "by_right": [], "special_exception": [],
                "prohibited": ["R4"], "unknown_jurisdiction": [],
            }}},
        )
        zoning_rows = [g for g in gates if g["gate_key"] == "zoning_dc_use"]
        assert len(zoning_rows) == 1
        assert zoning_rows[0]["status"] == "FAIL"
        assert "Prince William" in zoning_rows[0]["rationale"] or \
            "ordinance" in zoning_rows[0]["rationale"]

    def test_absent_zoning_layer_needs_no_rule(self):
        # Franklin's shape: the adapter returns zoning: None by
        # construction, so there is nothing to decide and no row required.
        parcels, _ = self._county()
        _, _, gates, _ = self._qualify(parcels, None, rules={})
        zoning_rows = [g for g in gates if g["gate_key"] == "zoning_dc_use"]
        assert len(zoning_rows) == 1
        assert zoning_rows[0]["status"] == "UNKNOWN"


# ── a township-scoped county: base + overlay layers (Licking's shape) ──
# Jersey Township publishes overlays as separate features ON TOP of a
# base district and flags them (ZoningOverlay = 'Y'). The gate must read
# the BASE as the parcel's district and carry the overlay as context the
# rule row classifies — never let the overlay win the dominance contest
# and silently lose the base.
def overlay_county():
    """Parcels with a base district each, plus overlay features stacked
    on some of them, in the Licking adapter's column shape."""
    pins = ["BASE-RR", "RR-IEW", "RR-MUDOD", "C1-GRANVILLE", "C1-WHO",
            "PUD-CPOW", "BASE-M1", "RR-SLIVER", "RR-TC", "RR-MUDOD-TC"]
    geoms = {pin: square(150.0, i) for i, pin in enumerate(pins)}
    parcels = gpd.GeoDataFrame(
        {"pin": pins, "legal_acreage": [150.0] * len(pins),
         "geometry": [geoms[p] for p in pins]},
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")

    def feature(zone, name, township, overlay, geom):
        return {"zone": zone, "zone_name": name, "ordinance":
                f"{township} Township Zoning Resolution (2026)",
                "township": township, "overlay": overlay, "geometry": geom}

    rows = []
    # Bases: slightly larger than the parcel so dominance is unambiguous.
    for pin, zone, name, twp in [
        ("BASE-RR", "RR", "Rural Residential", "Jersey"),
        ("RR-IEW", "RR", "Rural Residential", "Jersey"),
        ("RR-MUDOD", "RR", "Rural Residential", "Jersey"),
        ("C1-GRANVILLE", "C-1", "Conservation", "Granville"),
        ("C1-WHO", "C-1", "Conservation", "St. Albans"),
        ("PUD-CPOW", "PUD", "Planned Unit Development", "Jersey"),
        ("BASE-M1", "M-1", "Light Manufacturing", "Jersey"),
        ("RR-SLIVER", "RR", "Rural Residential", "Jersey"),
        ("RR-TC", "RR", "Rural Residential", "Liberty"),
        ("RR-MUDOD-TC", "RR", "Rural Residential", "Liberty"),
    ]:
        rows.append(feature(zone, name, twp, "N", geoms[pin].buffer(50)))
    # Overlays: published ON TOP of the base, flagged 'Y', and larger
    # than the base feature — so if the gate let the overlay win the
    # dominance contest, the base would be lost. That is the bug the
    # base-first read exists to prevent.
    for pin, zone, name in [
        ("RR-IEW", "IE-W", "Innovation Employment Overlay"),
        ("RR-MUDOD", "MUDOD", "Mixed Use Development Overlay"),
        ("PUD-CPOW", "CPO-W", "Commercial Professional Office Overlay"),
        ("PUD-CPOW", "IE-W", "Innovation Employment Overlay"),
        ("RR-MUDOD-TC", "MUDOD", "Mixed Use Development Overlay"),
        ("RR-TC", "TC", "Transportation Corridor Overlay"),
        ("RR-MUDOD-TC", "TC", "Transportation Corridor Overlay"),
    ]:
        rows.append(feature(zone, name, "Liberty", "Y", geoms[pin].buffer(200)))
    # A boundary sliver: a mapped overlay code covering only 3% of the
    # parcel — measured against Licking's live layer, corridor edges
    # clip real parcels at 0.9-13.9%. It must not participate.
    rows.append(feature("MCOB", "Mixed Commercial Overlay B", "Jersey", "Y",
                        strip_over(geoms["RR-SLIVER"], 0.03)))

    zoning = gpd.GeoDataFrame(rows, crs=PLANAR_CRS).to_crs("EPSG:4326")
    rules = {"zoning_dc_use": {"params": {
        "by_right": ["M-1"],
        "special_exception": ["PUD"],
        "prohibited": ["RR"],
        "unknown_jurisdiction": [],
        # C-1 is scoped: a real finding per township, never a flat row.
        "district_classes": {"C-1|Granville": "prohibited"},
        # A mapped overlay decides the combination; an unreviewed one
        # holds the verdict at UNKNOWN.
        "overlay_classes": {"IE-W": "special_exception", "CPO-W": "prohibited",
                            "MCOB": "special_exception"},
        # Liberty's TC (§811) and FP (§810) set development standards
        # only — the reviewed text says the base district's uses stand.
        "standards_only_overlays": ["TC", "FP"],
        "standards_only_reasons": {
            "TC": "Liberty Twp. Res. §811: 'Any permitted use allowed in "
                  "the underlying zoning district'",
        },
    }}}
    return parcels, zoning, rules


def qualify_overlay_county(places_gdf=None, extra_rules=None):
    parcels, zoning, rules = overlay_county()
    if extra_rules:
        rules = {k: {**v, **extra_rules.get(k, {})} for k, v in rules.items()}
    _, _, gates, _ = qualify_parcels(
        parcels_gdf=parcels, zoning_gdf=zoning,
        wetlands_gdf=None, nfhl_gdf=None, lines_gdf=None, subs_gdf=None,
        rules=rules, state_code="OH", county_name="Licking",
        snapshots={}, retrieve_time="2026-09-12T00:00:00+00:00",
        places_gdf=places_gdf,
    )
    return {(g["parcel_key"], g["gate_key"]): g for g in gates}


class TestBaseOverlayRead:
    def zoning_verdict(self, gates, pin):
        return gates[(f"OH-LICKING-{pin}", "zoning_dc_use")]

    def test_base_district_is_read_not_the_overlay(self):
        # RR + IE-W: the district on the verdict is the base RR, and the
        # overlay rides along as context — the overlay feature is larger
        # and would have won a plain dominance contest.
        gates = qualify_overlay_county()
        g = self.zoning_verdict(gates, "RR-IEW")
        assert g["status"] == "CONDITIONAL"  # IE-W is a mapped overlay
        assert g["details"]["zone"] == "RR"
        assert "IE-W" in g["details"]["overlays"]
        assert g["details"]["township"] == "Jersey"
        assert g["details"]["deciding_overlays"] == ["IE-W"]

    def test_overlay_without_base_still_records_a_district(self):
        # Not constructible from this county's shapes, but the plain
        # single-feature case must keep working: base only, no overlay.
        gates = qualify_overlay_county()
        g = self.zoning_verdict(gates, "BASE-RR")
        assert g["status"] == "FAIL"
        assert g["details"]["zone"] == "RR"
        assert "overlays" not in g["details"]

    def test_unreviewed_overlay_holds_unknown_not_the_base_class(self):
        # RR is flat-prohibited, but MUDOD has no reviewed overlay class:
        # the base's FAIL must not stand in for a combination nobody
        # reviewed.
        gates = qualify_overlay_county()
        g = self.zoning_verdict(gates, "RR-MUDOD")
        assert g["status"] == "UNKNOWN"
        assert "MUDOD" in g["rationale"]
        assert g["details"]["unreviewed_overlays"] == ["MUDOD"]

    def test_township_scoped_code_outranks_the_flat_lists(self):
        gates = qualify_overlay_county()
        # Granville's C-1 is scoped prohibited — decided by its own row.
        assert self.zoning_verdict(gates, "C1-GRANVILLE")["status"] == "FAIL"
        # The same code in a township with no scoped row stays UNKNOWN —
        # a colliding code is never decided by another township's entry.
        g = self.zoning_verdict(gates, "C1-WHO")
        assert g["status"] == "UNKNOWN"
        assert g["details"]["zone"] == "C-1"
        assert g["details"]["township"] == "St. Albans"

    def test_mapped_overlay_decides_over_a_decided_base(self):
        # PUD is flat special_exception; the parcel carries CPO-W
        # (prohibited) AND IE-W (special_exception). The overlay modifies
        # the base, and where mapped overlays disagree the MOST
        # restrictive wins — the min() form shipped inverted in the
        # first overlay release and read this combination CONDITIONAL.
        gates = qualify_overlay_county()
        g = self.zoning_verdict(gates, "PUD-CPOW")
        assert g["status"] == "FAIL"
        assert g["details"]["deciding_overlays"] == ["CPO-W"]
        assert "IE-W" in g["details"]["overlays"]  # context, not deciding

    def test_a_parcel_without_overlays_keeps_the_plain_reading(self):
        gates = qualify_overlay_county()
        assert self.zoning_verdict(gates, "BASE-M1")["status"] == "PASS"


class TestOverlayFloorAndStandardsOnly:
    """The two overlay-participation rules measured against Licking's
    live layer: a boundary sliver (0.9-13.9% of real parcels) must not
    hold an otherwise-decided verdict, and an overlay the reviewed
    ordinance text says does not modify uses never decides or holds."""

    def zoning_verdict(self, gates, pin):
        return gates[(f"OH-LICKING-{pin}", "zoning_dc_use")]

    def test_a_sliver_overlay_does_not_participate(self):
        # MCOB is a MAPPED overlay (special_exception) — without the
        # floor this parcel would read CONDITIONAL. It covers 3% of the
        # parcel: boundary noise, and the base RR's FAIL stands.
        gates = qualify_overlay_county()
        g = self.zoning_verdict(gates, "RR-SLIVER")
        assert g["status"] == "FAIL"
        assert g["details"]["zone"] == "RR"
        assert "overlays" not in g["details"]

    def test_a_meaningful_overlay_records_its_share(self):
        gates = qualify_overlay_county()
        g = self.zoning_verdict(gates, "RR-IEW")
        assert g["status"] == "CONDITIONAL"
        assert g["details"]["overlay_shares"]["IE-W"] == pytest.approx(
            100.0, abs=0.5)

    def test_a_standards_only_overlay_lets_the_base_decide(self):
        # Liberty's TC covers this parcel entirely, but §811 defers uses
        # to the underlying district: RR prohibits, and the verdict says
        # so with the citation — not UNKNOWN, and not silently ignoring
        # the overlay either.
        gates = qualify_overlay_county()
        g = self.zoning_verdict(gates, "RR-TC")
        assert g["status"] == "FAIL"
        assert g["details"]["zone"] == "RR"
        assert "TC" in g["details"]["standards_only_overlays"]
        assert "§811" in g["details"]["standards_only_overlays"]["TC"]
        assert "does not modify the base district" in g["rationale"]

    def test_standards_only_context_rides_along_a_held_verdict(self):
        # MUDOD (unreviewed) still holds the parcel at UNKNOWN — but the
        # rationale names only MUDOD as what is unreviewed, and TC rides
        # along as context rather than joining the hold.
        gates = qualify_overlay_county()
        g = self.zoning_verdict(gates, "RR-MUDOD-TC")
        assert g["status"] == "UNKNOWN"
        assert "MUDOD" in g["rationale"]
        assert g["details"]["unreviewed_overlays"] == ["MUDOD"]
        assert "TC" in g["details"]["standards_only_overlays"]


# ── a no-zoning county: the Texas rule, gated on municipal limits ─────
def taylor_county():
    """Two parcels, no zoning layer at all (a Texas county's shape), one
    inside an incorporated place and one outside it."""
    inside, outside = square(150.0, 0), square(150.0, 1)
    parcels = gpd.GeoDataFrame(
        {"pin": ["IN-CITY", "RURAL"], "legal_acreage": [150.0, 150.0],
         "geometry": [inside, outside]},
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")
    places = gpd.GeoDataFrame(
        {"place_geoid": ["4847796"], "place_name": ["Merkel town"],
         "place_basename": ["Merkel"], "place_lsad": ["43"],
         "geometry": [inside.buffer(50)]},
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")
    rules = {"zoning_dc_use": {"params": {
        "by_right": [], "special_exception": [], "prohibited": [],
        "unknown_jurisdiction": [],
        "no_county_zoning": {
            "status": "CONDITIONAL",
            "rationale": ("No county zoning applies: Texas counties have "
                          "no general zoning authority over unincorporated "
                          "land (Local Government Code ch. 231)."),
        },
    }}}
    return parcels, places, rules


def qualify_taylor(places_gdf="use-county-places", rules=None):
    parcels, places, default_rules = taylor_county()
    if places_gdf == "use-county-places":
        places_gdf = places
    _, metrics, gates, _ = qualify_parcels(
        parcels_gdf=parcels, zoning_gdf=None,
        wetlands_gdf=None, nfhl_gdf=None, lines_gdf=None, subs_gdf=None,
        rules=default_rules if rules is None else rules,
        state_code="TX", county_name="Taylor",
        snapshots={}, retrieve_time="2026-09-12T00:00:00+00:00",
        places_gdf=places_gdf,
    )
    return {(g["parcel_key"], g["gate_key"]): g for g in gates}, metrics


class TestNoCountyZoningRule:
    def test_outside_every_place_reads_conditional_with_the_statute(self):
        gates, _ = qualify_taylor()
        g = gates[("TX-TAYLOR-RURAL", "zoning_dc_use")]
        assert g["status"] == "CONDITIONAL"
        assert "ch. 231" in g["rationale"]
        assert g["details"]["municipal_limits"].startswith("outside every")

    def test_inside_a_place_stays_unknown_and_names_it(self):
        gates, metrics = qualify_taylor()
        g = gates[("TX-TAYLOR-IN-CITY", "zoning_dc_use")]
        assert g["status"] == "UNKNOWN"
        assert "Merkel" in g["rationale"]
        assert g["details"]["incorporated_place"] == "Merkel town"
        # The finding is a metric, not just rationale text.
        m = [m for m in metrics if m["metric_key"] == "incorporated_place"
             and m["parcel_key"] == "TX-TAYLOR-IN-CITY"]
        assert len(m) == 1 and m[0]["text_value"] == "Merkel town"

    def test_unavailable_places_layer_holds_the_rule_back(self):
        # Silence is not confirmation of unincorporated status.
        gates, _ = qualify_taylor(places_gdf=None)
        for pin in ("IN-CITY", "RURAL"):
            g = gates[(f"TX-TAYLOR-{pin}", "zoning_dc_use")]
            assert g["status"] == "UNKNOWN"
            assert "incorporated-places layer is unavailable" in g["rationale"]

    def test_no_rule_and_no_layer_is_the_plain_unknown(self):
        parcels, _, _ = taylor_county()
        _, _, gates, _ = qualify_parcels(
            parcels_gdf=parcels, zoning_gdf=None,
            wetlands_gdf=None, nfhl_gdf=None, lines_gdf=None, subs_gdf=None,
            rules={}, state_code="TX", county_name="Taylor",
            snapshots={}, retrieve_time="2026-09-12T00:00:00+00:00",
        )
        g = [g for g in gates if g["gate_key"] == "zoning_dc_use"][0]
        assert g["status"] == "UNKNOWN"
        assert "No zoning district overlap" in g["rationale"]

    def test_the_rule_never_fires_when_a_zoning_layer_exists(self):
        # A layer that misses a parcel is the municipal-gap case, not the
        # no-county-zoning case: the rule must not reach it.
        parcels, _, rules = taylor_county()
        zoning = gpd.GeoDataFrame(
            {"zone": ["RR"], "zone_name": ["Rural Residential"],
             "ordinance": ["2026"],
             "geometry": [square(150.0, 2).buffer(50)]},  # covers neither
            crs=PLANAR_CRS,
        ).to_crs("EPSG:4326")
        _, _, gates, _ = qualify_parcels(
            parcels_gdf=parcels, zoning_gdf=zoning,
            wetlands_gdf=None, nfhl_gdf=None, lines_gdf=None, subs_gdf=None,
            rules=rules, state_code="TX", county_name="Taylor",
            snapshots={}, retrieve_time="2026-09-12T00:00:00+00:00",
        )
        for g in gates:
            if g["gate_key"] == "zoning_dc_use":
                assert g["status"] == "UNKNOWN"
                assert "No zoning district overlap" in g["rationale"]


# ── a moratorium county: three governing levels, run-date evaluation ──
# The fixture mirrors the real Licking evidence: a county checked clear,
# a pending city ballot measure, and an adopted township ban — plus a
# parcel in a statistical MCD (an election district) that must NOT be
# treated as a governing township.
def moratorium_county():
    pins = ["RURAL", "IN-CITY", "BANNED", "CLEAR", "GROVE"]
    geoms = {pin: square(150.0, i) for i, pin in enumerate(pins)}
    # A small parcel annexed into the city: wholly inside the Pataskala
    # place polygon, but majority-inside a governing township's MCD —
    # the Grove City-in-Jackson shape. A township's instruments stop at
    # municipal limits, so what governs this parcel is the city, not the
    # township whose MCD contains it. Placed east of the city-MCD
    # buffer (IN-CITY + 50 m) but inside the place buffer (+ 200 m).
    minx, miny, _maxx, _maxy = geoms["IN-CITY"].bounds
    side = (4.0 * M2_PER_ACRE) ** 0.5
    geoms["ANNEXED"] = box(minx + 832.0, miny + 318.0,
                           minx + 832.0 + side, miny + 318.0 + side)
    pins = pins + ["ANNEXED"]
    parcels = gpd.GeoDataFrame(
        {"pin": pins,
         "legal_acreage": [150.0] * (len(pins) - 1) + [4.0],
         "geometry": [geoms[p] for p in pins]},
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")
    places = gpd.GeoDataFrame(
        {"place_geoid": ["3939256"], "place_name": ["Pataskala city"],
         "place_basename": ["Pataskala"], "place_lsad": ["25"],
         "geometry": [geoms["IN-CITY"].buffer(200)]},
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")
    subdivisions = gpd.GeoDataFrame(
        [
            # A functioning Ohio township — a governing jurisdiction.
            {"sub_geoid": "3908939102", "sub_name": "Jersey township",
             "sub_lsad": "44", "sub_funcstat": "A",
             "geometry": geoms["RURAL"].buffer(50)},
            {"sub_geoid": "3908969456", "sub_name": "St. Albans township",
             "sub_lsad": "44", "sub_funcstat": "A",
             "geometry": geoms["BANNED"].buffer(50)},
            # A city that is its own MCD — governed at the place level.
            {"sub_geoid": "3908961112", "sub_name": "Pataskala city",
             "sub_lsad": "25", "sub_funcstat": "F",
             "geometry": geoms["IN-CITY"].buffer(50)},
            # A statistical MCD — never a governing jurisdiction.
            {"sub_geoid": "5100301234", "sub_name": "Catoctin district",
             "sub_lsad": "27", "sub_funcstat": "N",
             "geometry": geoms["CLEAR"].buffer(50)},
            # A governing township whose moratorium covers its
            # unincorporated land only — and one parcel of it (ANNEXED)
            # sits inside a city. The MCD is governing; whether it
            # governs THAT parcel is a different question the gate
            # answers by place.
            {"sub_geoid": "3908941186", "sub_name": "Jackson township",
             "sub_lsad": "44", "sub_funcstat": "A",
             "geometry": MultiPolygon(
                 [geoms["ANNEXED"].buffer(80),
                  geoms["GROVE"].buffer(50)])},
        ],
        crs=PLANAR_CRS,
    ).to_crs("EPSG:4326")
    return parcels, places, subdivisions


def base_restrictions():
    """The real Licking rows, shape-faithful (statuses and citations)."""
    def row(**over):
        r = {
            "state_code": "OH", "county_name": "Licking",
            "place_name": None, "subdivision_name": None,
            "status": "none_found", "instrument": None,
            "adopting_body": None, "adopted_date": None,
            "effective_date": None, "expires_date": None, "scope": None,
            "source_url": None,
            "basis": "No county-level data-centre moratorium.",
            "reviewed_at": "2026-09-12",
            "sources_checked": "Licking County commissioners record",
        }
        r.update(over)
        return r

    return [
        row(),
        row(place_name="Pataskala city", status="pending",
            instrument="Citizen-initiated ballot measure to prohibit "
                       "large data centers",
            adopting_body="City of Pataskala electorate",
            scope="large data centers within city limits"),
        row(subdivision_name="St. Albans township", status="adopted",
            instrument="Zoning text amendment removing data processing "
                       "services from conditionally permitted uses",
            adopting_body="St. Albans Township Board of Trustees",
            adopted_date="2026-03-10", effective_date="2026-03-10",
            scope="all data-centre uses township-wide"),
    ]


def qualify_moratorium(restrictions="default", places_gdf="use",
                       subdivisions_gdf="use"):
    parcels, places, subdivisions = moratorium_county()
    if restrictions == "default":
        restrictions = base_restrictions()
    if places_gdf == "use":
        places_gdf = places
    if subdivisions_gdf == "use":
        subdivisions_gdf = subdivisions
    _, metrics, gates, _ = qualify_parcels(
        parcels_gdf=parcels, zoning_gdf=None,
        wetlands_gdf=None, nfhl_gdf=None, lines_gdf=None, subs_gdf=None,
        rules={}, state_code="OH", county_name="Licking",
        snapshots={}, retrieve_time="2026-09-12T00:00:00+00:00",
        places_gdf=places_gdf, subdivisions_gdf=subdivisions_gdf,
        restrictions=restrictions,
    )
    return {(g["parcel_key"], g["gate_key"]): g for g in gates}, metrics


class TestMoratoriumGate:
    def verdict(self, gates, pin):
        return gates[(f"OH-LICKING-{pin}", "moratorium_status")]

    def metric(self, metrics, pin, key):
        return [m for m in metrics
                if m["metric_key"] == key
                and m["parcel_key"] == f"OH-LICKING-{pin}"]

    def test_an_unreviewed_township_reads_unknown_not_pass(self):
        # The county is checked clear, but the parcel's township has no
        # row: a county none_found speaks only for the county, and a
        # jurisdiction nobody has reviewed reads UNKNOWN, never PASS.
        gates, _ = qualify_moratorium()
        g = self.verdict(gates, "RURAL")
        assert g["status"] == "UNKNOWN"
        assert "Jersey township" in g["rationale"]
        assert "no reviewed restriction record" in g["rationale"]
        assert g["details"]["levels"]["township"]["status"] == "unreviewed"
        assert g["details"]["levels"]["county"]["status"] == "none_found"

    def test_a_pending_measure_reads_conditional_citing_the_instrument(self):
        gates, metrics = qualify_moratorium()
        g = self.verdict(gates, "IN-CITY")
        assert g["status"] == "CONDITIONAL"
        assert "City of Pataskala electorate" in g["rationale"]
        assert "ballot measure" in g["rationale"]
        # Evaluated against the run's own date, recorded so the verdict
        # can be re-derived.
        assert g["details"]["evaluation_date"] == "2026-09-12"
        assert g["details"]["levels"]["place"]["status"] == "pending"
        # The city MCD is not a township: governed at the place level.
        assert "township" not in g["details"]["levels"]
        m = self.metric(metrics, "IN-CITY", "county_subdivision")
        assert m and m[0]["text_value"] == "Pataskala city"

    def test_an_adopted_ban_fails_citing_the_instrument(self):
        gates, _ = qualify_moratorium()
        g = self.verdict(gates, "BANNED")
        assert g["status"] == "FAIL"
        assert "St. Albans Township Board of Trustees" in g["rationale"]
        assert "2026-03-10" in g["rationale"]
        assert "no expiry recorded" in g["rationale"]
        assert g["details"]["instrument"].startswith("Zoning text amendment")

    def test_every_level_checked_clear_reads_pass(self):
        # The election district is a statistical MCD, not a governing
        # township, so the county's checked-clear row is the whole story.
        gates, _ = qualify_moratorium()
        g = self.verdict(gates, "CLEAR")
        assert g["status"] == "PASS"
        assert "reviewed 2026-09-12" in g["rationale"]
        assert "checked-clear" in g["rationale"]
        assert "township" not in g["details"]["levels"]

    def test_unavailable_evidence_holds_unknown_never_clears(self):
        gates, _ = qualify_moratorium(restrictions=None)
        for pin in ("RURAL", "IN-CITY", "BANNED", "CLEAR"):
            g = self.verdict(gates, pin)
            assert g["status"] == "UNKNOWN"
            assert "unavailable" in g["rationale"]

    def test_no_rows_for_the_state_reads_unknown(self):
        gates, _ = qualify_moratorium(restrictions=[])
        for pin in ("RURAL", "CLEAR"):
            assert self.verdict(gates, pin)["status"] == "UNKNOWN"

    def test_a_lapsed_moratorium_reopens_as_conditional(self):
        # The calendar is part of the verdict: expired on the run date,
        # the pause no longer fails the parcel — but the history stays
        # visible as a political-risk signal.
        rows = [dict(r) for r in base_restrictions()]
        rows[0].update(status="adopted",
                       instrument="Emergency ordinance 26-026, a 12-month "
                                  "pause on data-centre applications",
                       adopting_body="Board of County Commissioners",
                       adopted_date="2025-09-01", effective_date="2025-09-01",
                       expires_date="2026-09-01")
        gates, _ = qualify_moratorium(restrictions=rows)
        g = self.verdict(gates, "CLEAR")
        assert g["status"] == "CONDITIONAL"
        assert "has lapsed" in g["rationale"]
        assert "2026-09-01" in g["rationale"]

    def test_adopted_but_not_yet_effective_reads_conditional(self):
        rows = [dict(r) for r in base_restrictions()]
        rows[0].update(status="adopted",
                       instrument="Ordinance 27-001, a data-centre pause",
                       adopting_body="Board of County Commissioners",
                       adopted_date="2026-09-10",
                       effective_date="2026-10-01")
        gates, _ = qualify_moratorium(restrictions=rows)
        g = self.verdict(gates, "CLEAR")
        assert g["status"] == "CONDITIONAL"
        assert "not yet effective" in g["rationale"]
        assert "2026-10-01" in g["rationale"]

    def test_an_unverified_claim_holds_unknown(self):
        # Neither fails the parcel on an untraced claim nor clears it.
        rows = [dict(r) for r in base_restrictions()]
        rows[0].update(status="unverified",
                       instrument="Reported 12-month county pause",
                       basis="Could not be traced to the county's record.")
        gates, _ = qualify_moratorium(restrictions=rows)
        g = self.verdict(gates, "CLEAR")
        assert g["status"] == "UNKNOWN"
        assert "UNVERIFIED" in g["rationale"]

    def test_the_township_metric_is_persisted_beside_the_place(self):
        gates, metrics = qualify_moratorium()
        m = self.metric(metrics, "RURAL", "county_subdivision")
        assert m and m[0]["text_value"] == "Jersey township"
        assert m[0]["details"]["lsadc"] == "44"
        assert m[0]["evidence_class"] == "observed"
        # And the incorporated place metric still lands beside it.
        assert self.metric(metrics, "IN-CITY", "incorporated_place")

    def test_a_missing_subdivision_layer_holds_unincorporated_parcels(self):
        # No MCD layer: an unincorporated parcel's township is unreadable,
        # and silence must not read as "no township" — it reads UNKNOWN.
        # A parcel inside a place is governed by the municipality, so the
        # place's pending measure still decides it.
        gates, _ = qualify_moratorium(subdivisions_gdf=None)
        g = self.verdict(gates, "RURAL")
        assert g["status"] == "UNKNOWN"
        assert "subdivision layer unavailable" in g["rationale"]
        assert self.verdict(gates, "IN-CITY")["status"] == "CONDITIONAL"

    def test_a_township_row_does_not_reach_inside_municipal_limits(self):
        # Jackson Township's own letter: its limits "do not control land
        # once it is annexed into the city." A parcel inside a place is
        # governed by the municipality — an adopted, in-force township
        # moratorium must not fail it, and the township level is not
        # even carried. The unincorporated parcel in the same township
        # still fails on the township's own instrument. Found on the
        # real Franklin republish: 34 Grove City / Urbancrest parcels
        # inside Jackson township read FAIL before this rule.
        rows = [dict(r) for r in base_restrictions()]
        rows.append({
            "state_code": "OH", "county_name": "Licking",
            "place_name": None, "subdivision_name": "Jackson township",
            "status": "adopted",
            "instrument": "One-year moratorium on new data center "
                          "developments within the unincorporated "
                          "portions of the township",
            "adopting_body": "Jackson Township Board of Trustees",
            "adopted_date": "2026-05-12", "effective_date": "2026-05-12",
            "expires_date": "2027-05-12",
            "scope": "new data-centre development, unincorporated "
                     "portions only",
            "source_url": "https://jacksontwpfranklinoh.gov/",
            "basis": "The trustees' own community letter, corroborated "
                     "by the Dispatch.",
            "reviewed_at": "2026-09-12",
            "sources_checked": "township letter; Columbus Dispatch",
        })
        gates, _ = qualify_moratorium(restrictions=rows)
        # The annexed parcel: the city's pending ballot measure decides
        # it, not the township whose MCD contains it.
        g = self.verdict(gates, "ANNEXED")
        assert g["status"] == "CONDITIONAL"
        assert "township" not in g["details"]["levels"]
        assert g["details"]["levels"]["place"]["status"] == "pending"
        # Its neighbour outside the city fails on the township's own
        # instrument, cited.
        g2 = self.verdict(gates, "GROVE")
        assert g2["status"] == "FAIL"
        assert "Jackson Township Board of Trustees" in g2["rationale"]
        assert g2["details"]["levels"]["township"]["status"] == "adopted"


class TestParcelSpecificApprovalOutranksDistrict:
    """
    An approved ZMAP/SPEX/ZCPA for a data-centre use beats the district.

    Loudoun's ZOAM-2024-0001 ended by-right data centres in IP, GI and MR-HI,
    which is correct and now reflected in the use tables. It also meant the
    engine told seven parcels they needed a Special Exception the Board had
    already granted — one of them holding an approved SPEX in the engine's
    own curated records. A district classification is a rule about a category
    the land belongs to; an approval is the governing body permitting this
    use on this land.
    """

    def qualify(self, evidence):
        geoms = {pin: square(acres, i) for i, (pin, acres, _) in enumerate(PARCELS)}
        parcels = gpd.GeoDataFrame(
            {"pin": [p for p, _, _ in PARCELS],
             "legal_acreage": [a for _, a, _ in PARCELS],
             "geometry": [geoms[p] for p, _, _ in PARCELS]},
            crs=PLANAR_CRS).to_crs("EPSG:4326")
        zoning = gpd.GeoDataFrame(
            {"zone": [z for _, _, z in PARCELS],
             "zone_name": [f"{z} district" for _, _, z in PARCELS],
             "ordinance": ["2023"] * len(PARCELS),
             "geometry": [geoms[p].buffer(50) for p, _, _ in PARCELS]},
            crs=PLANAR_CRS).to_crs("EPSG:4326")
        _, _, gates, _ = qualify_parcels(
            parcels_gdf=parcels, zoning_gdf=zoning,
            wetlands_gdf=None, nfhl_gdf=None, lines_gdf=None, subs_gdf=None,
            # HOUSES sits in a district data centres may not occupy; CLEAN in
            # one requiring a Special Exception.
            rules={"zoning_dc_use": {"params": {
                "by_right": [], "special_exception": ["PDGI"],
                "prohibited": ["R1"], "unknown_jurisdiction": ["TOWNS"]}}},
            state_code="VA", county_name="Loudoun", snapshots={},
            retrieve_time="2026-09-11T00:00:00+00:00",
            parcel_evidence=evidence,
        )
        return pd.DataFrame(gates)

    def verdict_for(self, gates, pin):
        row = gates[(gates["parcel_key"] == f"VA-LOUDOUN-{pin}")
                    & (gates["gate_key"] == "zoning_dc_use")]
        return row["status"].iloc[0], row["details"].iloc[0]

    def test_approval_turns_special_exception_into_pass(self):
        gates = self.qualify({"VA-LOUDOUN-CLEAN": [{
            "application_number": "SPEX-2019-0028", "application_type": "SPEX",
            "approval_date": "2020-09-01", "authorizes_dc_use": True,
            "source_url": "https://example.invalid/spex"}]})
        status, details = self.verdict_for(gates, "CLEAN")
        assert status == "PASS"
        assert details["approvals"] == ["SPEX-2019-0028"]
        # The district it overrode is recorded, so the override is legible.
        assert details["district_would_have_read"] == "special_exception"

    def test_without_an_approval_the_district_still_decides(self):
        gates = self.qualify(None)
        assert self.verdict_for(gates, "CLEAN")[0] == "CONDITIONAL"

    def test_power_only_evidence_grants_nothing(self):
        """
        The reason the flag is explicit. power_parcel_evidence is curated for
        the power gate and may hold a filing that establishes no land-use
        right at all; inferring one from the application type would eventually
        hand out a zoning PASS the record never gave.
        """
        gates = self.qualify({"VA-LOUDOUN-CLEAN": [{
            "application_number": "ZMAP-9999-0001", "application_type": "ZMAP",
            "approval_date": "2024-01-01", "authorizes_dc_use": False}]})
        assert self.verdict_for(gates, "CLEAN")[0] == "CONDITIONAL"

    def test_an_approval_does_not_rescue_a_prohibited_district_silently(self):
        # It still reads PASS — that is the rule — but the details must say
        # which district it overrode, so nobody reads it as an unqualified
        # by-right permission.
        gates = self.qualify({"VA-LOUDOUN-HOUSES": [{
            "application_number": "ZCPA-2023-0005", "application_type": "ZCPA",
            "approval_date": "2025-03-18", "authorizes_dc_use": True}]})
        status, details = self.verdict_for(gates, "HOUSES")
        assert status == "PASS"
        assert details["district_would_have_read"] == "prohibited"

    def test_the_most_recent_approval_is_cited(self):
        gates = self.qualify({"VA-LOUDOUN-CLEAN": [
            {"application_number": "ZMAP-2008-0017", "application_type": "ZMAP",
             "approval_date": "2011-07-12", "authorizes_dc_use": True},
            {"application_number": "SPEX-2025-0031", "application_type": "SPEX",
             "approval_date": "2026-06-16", "authorizes_dc_use": True}]})
        status, details = self.verdict_for(gates, "CLEAN")
        assert status == "PASS"
        assert details["approval_date"] == "2026-06-16"
        assert set(details["approvals"]) == {"ZMAP-2008-0017", "SPEX-2025-0031"}


class TestTownshipWideClass:
    """
    Some amendments leave a use unauthorised anywhere in a resolution.

    Harrison Township's 2026-07-06 public hearing struck the proposed
    "Data Centers" conditional use from Article 16.2 and its Article 3
    definitions before adoption, so the use is listed in no district of the
    township. Expressing that as a list of `CODE|Harrison` entries would
    assert the list is complete — and a district absent from today's survey
    would fall through to the flat special_exception list, offering a special
    exception the trustees had declined to create. That is precisely what
    happened: 4 PUD parcels read CONDITIONAL while the moratorium gate read
    FAIL on the same instrument.
    """

    def qualify(self, rules, township):
        geoms = {pin: square(acres, i) for i, (pin, acres, _) in enumerate(PARCELS)}
        parcels = gpd.GeoDataFrame(
            {"pin": [p for p, _, _ in PARCELS],
             "legal_acreage": [a for _, a, _ in PARCELS],
             "geometry": [geoms[p] for p, _, _ in PARCELS]},
            crs=PLANAR_CRS).to_crs("EPSG:4326")
        zoning = gpd.GeoDataFrame(
            {"zone": [z for _, _, z in PARCELS],
             "zone_name": [f"{z} district" for _, _, z in PARCELS],
             "ordinance": ["2026"] * len(PARCELS),
             "township": [township] * len(PARCELS),
             "geometry": [geoms[p].buffer(50) for p, _, _ in PARCELS]},
            crs=PLANAR_CRS).to_crs("EPSG:4326")
        _, _, gates, _ = qualify_parcels(
            parcels_gdf=parcels, zoning_gdf=zoning, wetlands_gdf=None,
            nfhl_gdf=None, lines_gdf=None, subs_gdf=None, rules=rules,
            state_code="OH", county_name="Licking", snapshots={},
            retrieve_time="2026-09-12T00:00:00+00:00")
        g = pd.DataFrame(gates)
        return g[g["gate_key"] == "zoning_dc_use"]

    # PDGI stands in for a district the flat lists would allow.
    BASE = {"zoning_dc_use": {"params": {
        "by_right": [], "special_exception": ["PDGI"],
        "prohibited": ["R1"], "unknown_jurisdiction": ["TOWNS"]}}}

    def with_township_classes(self, mapping):
        import copy
        rules = copy.deepcopy(self.BASE)
        rules["zoning_dc_use"]["params"]["township_classes"] = mapping
        return rules

    def test_township_wide_class_prohibits_a_district_the_flat_list_allows(self):
        z = self.qualify(self.with_township_classes({"Harrison": "prohibited"}),
                         "Harrison")
        # Every PDGI parcel would otherwise be CONDITIONAL.
        assert set(z[z["status"] != "UNKNOWN"]["status"]) == {"FAIL"}

    def test_a_district_not_enumerated_anywhere_is_still_caught(self):
        """The reason this is township-level: completeness cannot be asserted."""
        z = self.qualify(self.with_township_classes({"Harrison": "prohibited"}),
                         "Harrison")
        row = z[z["parcel_key"] == "OH-LICKING-CLEAN"]
        assert row["status"].iloc[0] == "FAIL"
        assert row["details"].iloc[0]["township_wide"] == "Harrison"

    def test_another_township_is_untouched(self):
        # A township-wide ban binds one township, not its county.
        z = self.qualify(self.with_township_classes({"Harrison": "prohibited"}),
                         "Liberty")
        row = z[z["parcel_key"] == "OH-LICKING-CLEAN"]
        assert row["status"].iloc[0] == "CONDITIONAL"

    def test_without_the_mapping_the_district_falls_through(self):
        # The defect itself, pinned: no township class, so the flat
        # special_exception list answers and offers an exception that the
        # township removed.
        z = self.qualify(self.BASE, "Harrison")
        row = z[z["parcel_key"] == "OH-LICKING-CLEAN"]
        assert row["status"].iloc[0] == "CONDITIONAL"
