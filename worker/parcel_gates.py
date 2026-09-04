"""
Parcel qualification — metrics, gates, and provenance-tagged rows.

Separates the four criterion kinds the decision model needs:
  * hard gates       (zoning use, floodway, wetlands, acreage) → PASS /
                      CONDITIONAL / FAIL / UNKNOWN
  * scored factors   (distances) → metric values, not gates
  * verification     (slope, protected land, roads) → UNKNOWN until the
                      evidence layer lands — never a favorable default
  * informational    (zoning vintage, assembly potential)

Every emitted metric row carries its evidence class (observed / derived /
estimated / manual) and the source snapshot that produced it. Missing
layers produce UNKNOWN gates with an explicit rationale, never silence.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parcel_gates")

M2_PER_ACRE = 4046.8564224
# Local planar CRS for Loudoun County (UTM 18N) — area and distance math.
PLANAR_CRS = "EPSG:32618"
JURISDICTION = "Loudoun County, VA"
RULE_VERSIONS = {
    "zoning_dc_use": "2023-ord+2025-zoam",
    "contiguous_acreage": "v1",
    "floodway": "v1",
    "wetlands": "v1",
    "protected_land": "v1",
    "slope": "v1",
    "road_access": "v1",
}
# Dry-run defaults — identical to the seeded constraint_rules (release0_
# provenance migration). Live runs always read the rules from the database.
DEFAULT_RULE_PARAMS: Dict[str, Dict[str, Any]] = {
    "zoning_dc_use": {
        "by_right": ["PDGI", "PDIP", "GI", "IP", "MRHI"],
        "special_exception": ["CLI", "PDRDP", "PDCH"],
        "prohibited": ["A10", "A3", "AR1", "AR2", "CR1", "CR2", "CR3", "CR4", "RC",
                        "R1", "R2", "R3", "R4", "R8", "R16", "R24", "SCN8", "SCN16",
                        "SCN24", "PDH3", "PDH4", "PDH6", "PDAAAR", "PDRV", "PDCCRC",
                        "PDSC", "C1", "GB", "CCCC", "CCNC", "CCSC", "OP", "PDOP",
                        "TRC", "TC", "TR1LF", "TR1UBF", "TR2", "TR3LBR", "TR3LF",
                        "TR3UBF", "TR10", "PUD-1", "JLMA1", "JLMA2", "JLMA3", "JLMA20"],
        "unknown_jurisdiction": ["TOWNS"],
    },
    "contiguous_acreage": {"min_pass_acres": 100, "min_conditional_acres": 25},
    "floodway": {"floodway_fail_pct": 0.5, "floodplain_conditional": True},
    "wetlands": {"conditional_pct": 5, "fail_pct": 30},
    "protected_land": {"fail_pct": 0.5},
    "slope": {"max_fail_pct": 25, "median_conditional_pct": 8},
    "road_access": {"conditional_miles": 2, "fail_miles": 5},
}


def _to_multi_wkt(geom) -> str:
    """WKT for the MultiPolygon column (single polygons wrapped)."""
    if geom.geom_type == "Polygon":
        geom = MultiPolygon([geom])
    elif geom.geom_type != "MultiPolygon":
        raise ValueError(f"unexpected parcel geometry type {geom.geom_type}")
    return f"SRID=4326;{geom.wkt}"


def _union(gdf: Optional[gpd.GeoDataFrame]) -> Optional[Any]:
    if gdf is None or len(gdf) == 0:
        return None
    return gdf.geometry.unary_union


def _overlap_fraction(parcel_geom, layer_union, parcel_area_m2: float) -> float:
    """Share (0-100%) of the parcel covered by the layer union."""
    if layer_union is None or parcel_area_m2 <= 0:
        return 0.0
    inter = parcel_geom.intersection(layer_union)
    if inter.is_empty:
        return 0.0
    return float(min(100.0, (inter.area / parcel_area_m2) * 100.0))


def qualify_parcels(
    parcels_gdf: gpd.GeoDataFrame,
    zoning_gdf: Optional[gpd.GeoDataFrame],
    wetlands_gdf: Optional[gpd.GeoDataFrame],
    nfhl_gdf: Optional[gpd.GeoDataFrame],
    lines_gdf: Optional[gpd.GeoDataFrame],
    subs_gdf: Optional[gpd.GeoDataFrame],
    rules: Dict[str, Dict[str, Any]],
    state_code: str,
    county_name: str,
    snapshots: Dict[str, Optional[str]],
    retrieve_time: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Computes metrics and gates for every fetched parcel. Returns
    (parcel_records, metric_rows, gate_rows, stats) ready for staging.
    """
    n = len(parcels_gdf)
    logger.info("Qualifying %d Loudoun parcels…", n)

    planar = parcels_gdf.to_crs(PLANAR_CRS)
    parcel_area_m2 = planar.geometry.area

    # Layer unions in the planar CRS for overlap math
    wetlands_union = _union(wetlands_gdf.to_crs(PLANAR_CRS)) if wetlands_gdf is not None else None
    floodway_union = (
        _union(nfhl_gdf[nfhl_gdf["zone_subty"] == "FLOODWAY"].to_crs(PLANAR_CRS))
        if nfhl_gdf is not None else None
    )
    floodplain_union = (
        _union(nfhl_gdf[
            (nfhl_gdf["zone_subty"] != "FLOODWAY")
            & nfhl_gdf["fld_zone"].str.upper().str.match(r"^(A|AE|AH|AO|A[0-9])")
        ].to_crs(PLANAR_CRS))
        if nfhl_gdf is not None else None
    )

    # Zoning: dominant district per parcel (largest intersection area)
    zone_of: Dict[int, Dict[str, Any]] = {}
    zoning_coverage = None
    if zoning_gdf is not None and len(zoning_gdf) > 0:
        try:
            inter = gpd.overlay(
                parcels_gdf[["geometry"]].reset_index(names="pidx"),
                zoning_gdf[["zone", "zone_name", "ordinance", "geometry"]],
                how="intersection",
            )
            if len(inter) > 0:
                inter["area"] = inter.geometry.to_crs(PLANAR_CRS).area
                best = inter.sort_values("area", ascending=False) \
                    .drop_duplicates("pidx").set_index("pidx")
                zone_of = {i: row for i, row in best.iterrows()}
                zoning_coverage = float(parcels_gdf.index.isin(best.index).mean() * 100)
        except Exception as e:  # noqa: BLE001
            logger.warning("Zoning overlay failed: %s", e)

    # Power proximity (real HIFLD only — no synthetic distances ever)
    line_dist_mi: Optional[pd.Series] = None
    sub_dist_mi: Optional[pd.Series] = None
    if lines_gdf is not None and len(lines_gdf) > 0:
        line_dist_mi = gpd.sjoin_nearest(
            planar[["geometry"]], lines_gdf.to_crs(PLANAR_CRS)[["geometry"]],
            how="left", distance_col="dist_m"
        )["dist_m"].groupby(level=0).min() / 1609.344
    if subs_gdf is not None and len(subs_gdf) > 0:
        sub_dist_mi = gpd.sjoin_nearest(
            planar[["geometry"]], subs_gdf.to_crs(PLANAR_CRS)[["geometry"]],
            how="left", distance_col="dist_m"
        )["dist_m"].groupby(level=0).min() / 1609.344

    # Assembly potential: abutting parcels above the source-acreage floor
    assembly: Dict[int, Tuple[int, float]] = {}
    try:
        touches = gpd.sjoin(
            parcels_gdf[["geometry"]], parcels_gdf[["legal_acreage", "geometry"]],
            predicate="touches", how="left"
        )
        # drop self-pairs
        touches = touches[touches.index != touches.index_right]
        grp = touches.groupby(level=0)
        assembly = {
            i: (int(len(g)), float(pd.to_numeric(g["legal_acreage"], errors="coerce").fillna(0).sum()))
            for i, g in grp
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("Assembly adjacency join failed: %s", e)

    dc_map = rules.get("zoning_dc_use", {}).get("params", DEFAULT_RULE_PARAMS["zoning_dc_use"])
    acre_rule = rules.get("contiguous_acreage", {}).get("params", DEFAULT_RULE_PARAMS["contiguous_acreage"])
    flood_rule = rules.get("floodway", {}).get("params", DEFAULT_RULE_PARAMS["floodway"])
    wet_rule = rules.get("wetlands", {}).get("params", DEFAULT_RULE_PARAMS["wetlands"])
    rule_ids = {k: v.get("id") for k, v in rules.items()}

    parcel_records: List[Dict[str, Any]] = []
    metric_rows: List[Dict[str, Any]] = []
    gate_rows: List[Dict[str, Any]] = []

    def metric(pin: str, key: str, value=None, text_value=None, unit=None,
               evidence="observed", layer="parcels", details=None) -> None:
        metric_rows.append({
            "parcel_key": pin,
            "metric_key": key,
            "value": None if value is None else round(float(value), 4),
            "text_value": text_value,
            "unit": unit,
            "evidence_class": evidence,
            "source_snapshot_id": snapshots.get(layer),
            "retrieved_at": retrieve_time,
            "details": details or {},
        })

    def gate(pin: str, key: str, status: str, rationale: str,
             affected=None, details=None) -> None:
        gate_rows.append({
            "parcel_key": pin,
            "gate_key": key,
            "status": status,
            "affected_area_pct": None if affected is None else round(float(affected), 3),
            "rationale": rationale,
            "rule_id": rule_ids.get(key),
            "details": details or {},
        })

    for i, row in parcels_gdf.iterrows():
        pin = f"{state_code}-{county_name.upper().replace(' ', '-')}-{row['pin']}"
        geom = row.geometry
        area_m2 = float(parcel_area_m2.loc[i])
        gis_acreage = area_m2 / M2_PER_ACRE
        legal_acreage = row.get("legal_acreage")

        parcel_records.append({
            "parcel_key": pin,
            "source_parcel_id": str(row["pin"]),
            "state_code": state_code,
            "county_name": county_name,
            "geom": _to_multi_wkt(geom),
            "gis_acreage": round(gis_acreage, 3),
            "legal_acreage": None if legal_acreage is None else round(float(legal_acreage), 3),
        })

        # ── metrics ───────────────────────────────────────────────────
        metric(pin, "total_acreage", gis_acreage, unit="acres", evidence="derived",
               layer="parcels", details={"basis": "GIS geometry", "legal_acreage": legal_acreage})

        wet_pct = _overlap_fraction(planar.geometry.loc[i], wetlands_union, area_m2)
        fw_pct = _overlap_fraction(planar.geometry.loc[i], floodway_union, area_m2)
        fp_pct = _overlap_fraction(planar.geometry.loc[i], floodplain_union, area_m2)

        if wetlands_gdf is not None:
            metric(pin, "wetland_pct", wet_pct, unit="percent", evidence="derived", layer="wetlands")
        if nfhl_gdf is not None:
            metric(pin, "floodway_pct", fw_pct, unit="percent", evidence="derived", layer="nfhl")
            metric(pin, "floodplain_pct", fp_pct, unit="percent", evidence="derived", layer="nfhl")

        zr = zone_of.get(i)
        if zr is not None:
            zone_code = str(zr["zone"])
            metric(pin, "zoning_district", None, text_value=zone_code, layer="zoning",
                   details={"zone_name": zr["zone_name"]})
            metric(pin, "zoning_ordinance_vintage", None, text_value=str(zr["ordinance"]),
                   layer="zoning", evidence="observed")

            if zone_code in dc_map.get("by_right", []):
                dc_status = "by_right"
            elif zone_code in dc_map.get("special_exception", []):
                dc_status = "special_exception"
            elif zone_code in dc_map.get("unknown_jurisdiction", []):
                dc_status = "unknown_jurisdiction"
            elif zone_code in dc_map.get("prohibited", []):
                dc_status = "prohibited"
            else:
                dc_status = "unmapped"
            metric(pin, "dc_use_status", None, text_value=dc_status, evidence="manual",
                   layer="zoning", details={
                       "zone": zone_code,
                       "basis": "constraint_rules mapping 2023-ord+2025-zoam (screening, pending ordinance review)",
                   })

        if line_dist_mi is not None and i in line_dist_mi.index:
            metric(pin, "distance_to_transmission_miles", line_dist_mi.loc[i],
                   unit="miles", evidence="derived", layer="power_lines")
        if sub_dist_mi is not None and i in sub_dist_mi.index:
            metric(pin, "distance_to_substation_miles", sub_dist_mi.loc[i],
                   unit="miles", evidence="derived", layer="substations")

        if i in assembly:
            count, acreage = assembly[i]
            metric(pin, "assembly_adjoining_count", count, unit="count",
                   evidence="derived", layer="parcels")
            metric(pin, "assembly_total_acreage", gis_acreage + acreage, unit="acres",
                   evidence="derived", layer="parcels",
                   details={"adjoining_acreage": round(acreage, 3)})

        # developable acreage (derived): minus wetland + floodway overlap
        developable = gis_acreage * (1.0 - (wet_pct + fw_pct) / 100.0)
        metric(pin, "contiguous_developable_acreage", max(developable, 0.0), unit="acres",
               evidence="derived", layer="parcels",
               details={"wetland_pct": round(wet_pct, 3), "floodway_pct": round(fw_pct, 3)})

        # ── gates ─────────────────────────────────────────────────────
        # Zoning / data-center use
        if zr is None:
            gate(pin, "zoning_dc_use", "UNKNOWN",
                 "No zoning district overlap found — the authoritative zoning map "
                 "does not cover this parcel (unincorporated/town gap or boundary "
                 "sliver). Use status remains UNKNOWN until reviewed.",
                 details={"zoning_layer": "present" if zoning_gdf is not None else "missing"})
        else:
            zone_code = str(zr["zone"])
            if dc_status == "by_right":
                gate(pin, "zoning_dc_use", "PASS",
                     f"Zoned {zone_code} ({zr['zone_name']}) — data centers are a "
                     f"by-right principal use in industrial districts under the "
                     f"{zr['ordinance']} ordinance (screening mapping).",
                     details={"zone": zone_code, "ordinance": str(zr["ordinance"])})
            elif dc_status == "special_exception":
                gate(pin, "zoning_dc_use", "CONDITIONAL",
                     f"Zoned {zone_code} ({zr['zone_name']}) — data centers require a "
                     f"Special Exception under the {zr['ordinance']} ordinance.",
                     details={"zone": zone_code, "ordinance": str(zr["ordinance"])})
            elif dc_status == "prohibited":
                gate(pin, "zoning_dc_use", "FAIL",
                     f"Zoned {zone_code} ({zr['zone_name']}) — data centers are not a "
                     f"permitted use in this district under the {zr['ordinance']} ordinance.",
                     details={"zone": zone_code, "ordinance": str(zr["ordinance"])})
            elif dc_status == "unknown_jurisdiction":
                gate(pin, "zoning_dc_use", "UNKNOWN",
                     f"Zoned {zone_code} — inside an incorporated town with its own "
                     f"zoning ordinance; county mapping does not apply.",
                     details={"zone": zone_code})
            else:
                gate(pin, "zoning_dc_use", "UNKNOWN",
                     f"Zoned {zone_code} ({zr['zone_name']}) — district is not in the "
                     f"reviewed mapping; use status remains UNKNOWN until the "
                     f"ordinance use table is checked.",
                     details={"zone": zone_code})

        # Contiguous developable acreage
        if developable >= acre_rule.get("min_pass_acres", 100):
            gate(pin, "contiguous_acreage", "PASS",
                 f"{developable:.1f} contiguous developable acres (>= "
                 f"{acre_rule.get('min_pass_acres', 100)} required).",
                 affected=0.0)
        elif developable >= acre_rule.get("min_conditional_acres", 25):
            gate(pin, "contiguous_acreage", "CONDITIONAL",
                 f"{developable:.1f} contiguous developable acres — below the "
                 f"{acre_rule.get('min_pass_acres', 100)}-acre campus floor; assembly "
                 f"with adjoining parcels required.",
                 affected=(1 - developable / max(gis_acreage, 1e-9)) * 100)
        else:
            gate(pin, "contiguous_acreage", "FAIL",
                 f"Only {developable:.1f} contiguous developable acres — below the "
                 f"{acre_rule.get('min_conditional_acres', 25)}-acre minimum.",
                 affected=(1 - developable / max(gis_acreage, 1e-9)) * 100)

        # Floodway / floodplain
        if nfhl_gdf is None:
            gate(pin, "floodway", "UNKNOWN",
                 "FEMA flood hazard zones unavailable for this run — "
                 "flood status unverified.")
        elif fw_pct > flood_rule.get("floodway_fail_pct", 0.5):
            gate(pin, "floodway", "FAIL",
                 f"{fw_pct:.1f}% of the parcel lies inside the regulatory floodway.",
                 affected=fw_pct)
        elif fp_pct > flood_rule.get("floodway_fail_pct", 0.5):
            gate(pin, "floodway", "CONDITIONAL",
                 f"{fp_pct:.1f}% of the parcel lies in the 100-year floodplain "
                 f"(outside the floodway) — elevation/floodproofing study required.",
                 affected=fp_pct)
        else:
            gate(pin, "floodway", "PASS",
                 "Outside the regulatory floodway and 100-year floodplain "
                 "per FEMA flood hazard zones (county FEMAFlood mirror).")

        # Wetlands
        if wetlands_gdf is None:
            gate(pin, "wetlands", "UNKNOWN",
                 "NWI wetlands layer unavailable for this run — wetland "
                 "coverage unverified (field delineation still required later).")
        elif wet_pct > wet_rule.get("fail_pct", 30):
            gate(pin, "wetlands", "FAIL",
                 f"{wet_pct:.1f}% wetland coverage (NWI) exceeds the "
                 f"{wet_rule.get('fail_pct', 30)}% screening limit.",
                 affected=wet_pct)
        elif wet_pct > wet_rule.get("conditional_pct", 5):
            gate(pin, "wetlands", "CONDITIONAL",
                 f"{wet_pct:.1f}% wetland coverage (NWI) — Army Corps delineation "
                 f"and permitting path required.",
                 affected=wet_pct)
        else:
            gate(pin, "wetlands", "PASS",
                 f"{wet_pct:.1f}% wetland coverage (NWI) — below the "
                 f"{wet_rule.get('conditional_pct', 5)}% screening threshold.")

        # Verification-required layers: explicit UNKNOWN until evidence lands
        gate(pin, "slope", "UNKNOWN",
             "3DEP slope derivation pending — terrain suitability unverified.")
        gate(pin, "protected_land", "UNKNOWN",
             "PAD-US protected-areas overlay pending — conservation status unverified.")
        gate(pin, "road_access", "UNKNOWN",
             "TIGER road proximity pending — access and truck routing unverified.")

    stats = {
        "parcels_qualified": n,
        "zoning_coverage_pct": zoning_coverage,
        "wetlands_layer": "present" if wetlands_gdf is not None else "missing",
        "nfhl_layer": "present" if nfhl_gdf is not None else "missing",
        "metric_rows": len(metric_rows),
        "gate_rows": len(gate_rows),
    }
    logger.info("Qualification complete: %s", stats)
    return parcel_records, metric_rows, gate_rows, stats
