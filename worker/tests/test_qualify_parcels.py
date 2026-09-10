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
from shapely.geometry import LineString, Point, box

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
        rules={},  # exercise the shipped DEFAULT_RULE_PARAMS
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
