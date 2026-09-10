"""
Parcel qualification — metrics, gates, and provenance-tagged rows.

Separates the four criterion kinds the decision model needs:
  * hard gates       (zoning use, floodway, wetlands, acreage) → PASS /
                      CONDITIONAL / FAIL / UNKNOWN
  * scored factors   (distances) → metric values, not gates
  * verification     (slope, protected land, roads, power capacity) →
                      UNKNOWN until the evidence layer lands — never a
                      favorable default
  * informational    (zoning vintage, assembly potential)

Every emitted metric row carries its evidence class (observed / derived /
estimated / manual) and the source snapshot that produced it. Missing
layers produce UNKNOWN gates with an explicit rationale, never silence.
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import pandas as pd
from shapely import STRtree
from shapely.geometry import MultiPolygon
from shapely.ops import unary_union

import network_evidence
import underwriting
from assessment_evidence import assessment_of

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parcel_gates")

M2_PER_ACRE = 4046.8564224
# Local planar CRS for Loudoun County (UTM 18N) — area and distance math.
PLANAR_CRS = "EPSG:32618"
RULE_VERSIONS = {
    "zoning_dc_use": "2023-ord+2025-zoam",
    "contiguous_acreage": "v1",
    "floodway": "v1",
    "wetlands": "v1",
    "protected_land": "v1",
    "slope": "v1",
    "road_access": "v1",
    "power_capacity": "v1",
    "water_availability": "v1",
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
    "power_capacity": {"active_statuses": ["EP", "UC", "PL"], "queue_radius_miles": 3},
    "water_availability": {"pass_overlap_pct": 50, "conditional_overlap_pct": 5},
}



def _num(v: Any) -> Optional[float]:
    """
    A float the JSON encoder will accept, or None.

    `x is None` is not enough. Values arriving through pandas carry NaN
    where a source had nothing, NaN is not None, and float(NaN) serialises
    to a bare `NaN` token that is not valid JSON — which is how the first
    Ohio publish died after a complete run. Infinities go the same way.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _json_safe(obj: Any) -> Any:
    """
    Recursively replaces NaN and infinity with None inside a details
    payload. Assessment and incentive records come straight off a
    dataframe, so they carry NaN wherever the county had no value, and
    details is serialised to jsonb verbatim.
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    return obj


def _round_half_away(x: float) -> int:
    """
    Rounds like Postgres numeric rounding, half away from zero.

    Python's int() truncates and round() goes half-to-even, so both drift
    from the same percentile computed in SQL — a p90 of 47.5 becomes 47
    here and 48 there. These figures get cross-checked against the database
    sooner or later, and the two answers have to agree.
    """
    return int(math.floor(x + 0.5)) if x >= 0 else int(math.ceil(x - 0.5))


def _rtep_schedule_slip(rtep_df: pd.DataFrame, min_sample: int = 30
                        ) -> Optional[Dict[str, Any]]:
    """
    How well the transmission area actually delivers against its own dates.

    PJM publishes both a projected and an actual in-service date for
    completed upgrades, so schedule risk here is a track record rather than
    a guess: the slip distribution of upgrades that have already energised.
    Negative days mean delivered early.

    Prefers the survey area's own history and falls back to the full
    dataset only when the local sample is too small to say anything; the
    scope used is returned so the caller can state which it was. Returns
    None when neither sample qualifies — an unknown record, not a
    reassuring default.
    """
    if rtep_df is None or len(rtep_df) == 0:
        return None
    for scope, frame in (("county area", rtep_df[rtep_df["in_area"]]),
                         ("PJM dataset", rtep_df)):
        proj = pd.to_datetime(frame["projected_in_service_date"], errors="coerce")
        actual = pd.to_datetime(frame["actual_in_service_date"], errors="coerce")
        slip = (actual - proj).dt.days.dropna()
        if len(slip) < min_sample:
            continue
        return {
            "scope": scope,
            "sample": int(len(slip)),
            "median_days": _round_half_away(float(slip.median())),
            "p90_days": _round_half_away(float(slip.quantile(0.9))),
            "on_time_pct": round(float((slip <= 0).mean() * 100), 1),
            "basis": ("completed upgrades with both a projected and an actual "
                      "in-service date, PJM RTEP"),
        }
    return None

def _to_multi_wkt(geom) -> str:
    """WKT for the MultiPolygon column (single polygons wrapped)."""
    if geom.geom_type == "Polygon":
        geom = MultiPolygon([geom])
    elif geom.geom_type != "MultiPolygon":
        raise ValueError(f"unexpected parcel geometry type {geom.geom_type}")
    return f"SRID=4326;{geom.wkt}"


class _OverlapIndex:
    """
    Share (0-100%) of a parcel covered by a layer, tested only against the
    layer parts that could actually touch it.

    This replaced a `unary_union` of the whole layer plus a per-parcel
    `intersection` against the result. Unioning is the obvious way to make a
    combined layer and a quiet way to make overlap tests scale with the
    layer's total complexity rather than with what is near the parcel: a
    union carries no spatial index, so every parcel is tested against every
    vertex of the entire layer. Most parcels touch none of these layers —
    wetlands, floodway, floodplain, PAD-US, the water service areas — and
    were paying full price to discover that. On a synthetic layer of 4,000
    scattered polygons against 2,478 parcels the indexed form was ~56x
    faster for identical results.

    The answer is unchanged: the STRtree narrows by bounding box, and the
    surviving candidates are unioned and intersected exactly as before.
    """

    __slots__ = ("_parts", "_tree")

    def __init__(self, gdf: Optional[gpd.GeoDataFrame]):
        parts: List[Any] = []
        if gdf is not None and len(gdf):
            parts = [g for g in gdf.geometry if g is not None and not g.is_empty]
        self._parts = parts
        self._tree = STRtree(parts) if parts else None

    def fraction(self, parcel_geom, parcel_area_m2: float) -> float:
        if self._tree is None or parcel_area_m2 <= 0:
            return 0.0
        idx = self._tree.query(parcel_geom)
        if len(idx) == 0:
            return 0.0
        # One candidate is the common case; skip the union for it.
        cand = (self._parts[idx[0]] if len(idx) == 1
                else unary_union([self._parts[j] for j in idx]))
        inter = parcel_geom.intersection(cand)
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
    roads_gdf: Optional[gpd.GeoDataFrame] = None,
    padus_gdf: Optional[gpd.GeoDataFrame] = None,
    slopes: Optional[Dict[Any, Tuple[Optional[float], Optional[float], int]]] = None,
    utility_gdf: Optional[gpd.GeoDataFrame] = None,
    rtep_df: Optional[pd.DataFrame] = None,
    queue_gdf: Optional[gpd.GeoDataFrame] = None,
    apps_gdf: Optional[gpd.GeoDataFrame] = None,
    parcel_evidence: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    water_gdf: Optional[gpd.GeoDataFrame] = None,
    assessments: Optional[pd.DataFrame] = None,
    assumptions: Optional[Dict[str, Dict[str, Any]]] = None,
    facilities: Optional[gpd.GeoDataFrame] = None,
    parcel_incentives: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Computes metrics and gates for every fetched parcel. Returns
    (parcel_records, metric_rows, gate_rows, stats) ready for staging.
    """
    # A duplicated parcel id survives the whole run and only fails at the
    # write, where the staged upsert hits "ON CONFLICT DO UPDATE cannot
    # affect row a second time" after fifteen minutes of work. Cheaper to
    # catch it here, and loudly: a jurisdiction whose ids are not unique
    # needs its adapter looked at, not a silent last-one-wins.
    if parcels_gdf is not None and len(parcels_gdf) > 0:
        dupes = parcels_gdf["pin"].duplicated(keep="first")
        if dupes.any():
            offenders = sorted(set(parcels_gdf.loc[dupes, "pin"].astype(str)))
            logger.warning(
                "Duplicate parcel ids from the source (%d rows across %d ids: %s) — "
                "keeping the first of each. The adapter should be filtering these.",
                int(dupes.sum()), len(offenders), ", ".join(offenders[:5]))
            parcels_gdf = parcels_gdf[~dupes]

    n = len(parcels_gdf)
    assumptions = assumptions or {}
    incentives_of = parcel_incentives or {}
    logger.info("Qualifying %d Loudoun parcels…", n)

    planar = parcels_gdf.to_crs(PLANAR_CRS)
    parcel_area_m2 = planar.geometry.area

    # Layer unions in the planar CRS for overlap math
    wetlands_ix = _OverlapIndex(
        wetlands_gdf.to_crs(PLANAR_CRS) if wetlands_gdf is not None else None)
    padus_ix = _OverlapIndex(
        padus_gdf.to_crs(PLANAR_CRS) if padus_gdf is not None else None)
    roads_planar = (
        roads_gdf.to_crs(PLANAR_CRS)[["road_class", "geometry"]]
        if roads_gdf is not None and len(roads_gdf) > 0 else None
    )
    floodway_ix = _OverlapIndex(
        nfhl_gdf[nfhl_gdf["zone_subty"] == "FLOODWAY"].to_crs(PLANAR_CRS)
        if nfhl_gdf is not None else None
    )
    floodplain_ix = _OverlapIndex(
        nfhl_gdf[
            (nfhl_gdf["zone_subty"] != "FLOODWAY")
            & nfhl_gdf["fld_zone"].str.upper().str.match(r"^(A|AE|AH|AO|A[0-9])")
        ].to_crs(PLANAR_CRS)
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

    # Road access: nearest primary/secondary road (TIGER)
    road_dist_mi: Optional[pd.Series] = None
    if roads_planar is not None:
        road_dist_mi = gpd.sjoin_nearest(
            planar[["geometry"]], roads_planar[["geometry"]],
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
    prot_rule = rules.get("protected_land", {}).get("params", DEFAULT_RULE_PARAMS["protected_land"])
    slope_rule = rules.get("slope", {}).get("params", DEFAULT_RULE_PARAMS["slope"])
    road_rule = rules.get("road_access", {}).get("params", DEFAULT_RULE_PARAMS["road_access"])
    power_rule = rules.get("power_capacity", {}).get("params", DEFAULT_RULE_PARAMS["power_capacity"])
    water_rule = rules.get("water_availability", {}).get("params", DEFAULT_RULE_PARAMS["water_availability"])
    rule_ids = {k: v.get("id") for k, v in rules.items()}

    # ── Power diligence (Release 2) ──────────────────────────────────
    # Serving utility: the territory polygon containing the parcel centroid.
    utility_of: Dict[int, Dict[str, str]] = {}
    if utility_gdf is not None and len(utility_gdf) > 0:
        try:
            centroids = parcels_gdf.copy()
            centroids["geometry"] = centroids.geometry.centroid
            joined = gpd.sjoin(
                centroids[["geometry"]], utility_gdf[["utility_name", "utility_type", "geometry"]],
                predicate="within", how="left",
            )
            utility_of = {
                i: {"name": str(r.utility_name), "type": str(r.utility_type)}
                for i, r in joined.iterrows() if isinstance(r.utility_name, str)
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("Utility territory join failed: %s", e)

    # Area RTEP evidence: active Board-approved upgrades in the county area.
    rtep_area: Optional[Dict[str, Any]] = None
    active_statuses = power_rule.get("active_statuses", ["EP", "UC", "PL"])
    if rtep_df is not None and len(rtep_df) > 0:
        act = rtep_df[rtep_df["in_area"] & rtep_df["status"].isin(active_statuses)]
        isd = sorted(str(d) for d in act["projected_in_service_date"].dropna())
        boards = sorted(str(d) for d in act["board_approval_date"].dropna())
        if len(act) > 0:
            cost = act["cost_estimate_musd"].dropna()
            rtep_area = {
                "active": int(len(act)),
                "earliest_energization": isd[0] if isd else None,
                "latest_energization": isd[-1] if isd else None,
                "latest_board_approval": boards[-1] if boards else None,
                "source_updated": max(
                    (str(d) for d in rtep_df["source_updated"].dropna()), default=None
                ),
                # PJM's own Board-approved cost estimates, summed. These are
                # PJM estimates for the transmission area, not actual spend and
                # not attributable to any one parcel.
                "cost_musd": round(float(cost.sum()), 1) if len(cost) else None,
                "cost_reported": int(len(cost)),
                "schedule": _rtep_schedule_slip(
                    rtep_df, int(power_rule.get("slip_min_sample", 30))
                ),
            }

    # PJM queue activity: interconnection points within the radius.
    queue_radius_mi = float(power_rule.get("queue_radius_miles", 3))
    queue_counts: Optional[pd.Series] = None
    queue_max_kv: Optional[pd.Series] = None
    if queue_gdf is not None and len(queue_gdf) > 0:
        try:
            qp = queue_gdf.to_crs(PLANAR_CRS)[["voltage_kv", "geometry"]]
            near = gpd.sjoin_nearest(
                planar[["geometry"]], qp, how="left", distance_col="dist_m",
                max_distance=queue_radius_mi * 1609.344,
            )
            near["hit"] = near["voltage_kv"].notna()
            queue_counts = near.groupby(level=0)["hit"].sum()
            queue_max_kv = near.groupby(level=0)["voltage_kv"].max()
        except Exception as e:  # noqa: BLE001
            logger.warning("Queue activity join failed: %s", e)

    # Approved data-center legislative applications per parcel (observed):
    # county cases (SPEX/ZMAP/ZCPA…) whose boundary overlaps the parcel.
    # A sliver threshold keeps boundary-noise from counting.
    apps_of: Dict[int, List[Dict[str, Any]]] = {}
    if apps_gdf is not None and len(apps_gdf) > 0:
        try:
            inter = gpd.overlay(
                planar[["geometry"]].reset_index(names="pidx"),
                apps_gdf.to_crs(PLANAR_CRS)[
                    ["app_number", "app_type", "approval_date", "geometry"]],
                how="intersection",
            )
            if len(inter) > 0:
                inter["area"] = inter.geometry.area
                parcel_areas = planar.geometry.area
                # count an application when it covers ≥5% of the parcel
                # or ≥2 acres of it (approved project footprint, not a
                # boundary sliver)
                inter["counts"] = (
                    (inter["area"] >= 0.05 * inter["pidx"].map(parcel_areas))
                    | (inter["area"] >= 2.0 * 4046.8564224)
                )
                for pidx, grp in inter[inter["counts"]].groupby("pidx"):
                    apps_of[int(pidx)] = [
                        {"app_number": str(r.app_number), "app_type": str(r.app_type),
                         "approval_date": str(r.approval_date)}
                        for r in grp.itertuples()
                    ]
        except Exception as e:  # noqa: BLE001
            logger.warning("Legislative application overlay failed: %s", e)

    # ── Water availability (Release 3) ───────────────────────────────
    # Loudoun Water's published service-area boundary: serving areas
    # (ServiceType W/Both), the utility's explicit "NOT Served" polygon,
    # and per-area records (comment may restrict new connections).
    water_serving_ix = _OverlapIndex(None)
    water_not_served_ix = _OverlapIndex(None)
    water_layer_edited: Optional[str] = None
    water_area_of: Dict[int, Dict[str, Any]] = {}
    ww_serving_ix = _OverlapIndex(None)
    ww_area_of: Dict[int, Dict[str, Any]] = {}
    if water_gdf is not None and len(water_gdf) > 0:
        serving = water_gdf[water_gdf["service_type"].isin(("W", "Both"))]
        ww_serving = water_gdf[water_gdf["service_type"].isin(("WW", "Both"))]
        not_served = water_gdf[water_gdf["area_name"] == "NOT Served by LW"]
        water_serving_ix = _OverlapIndex(serving.to_crs(PLANAR_CRS))
        ww_serving_ix = _OverlapIndex(ww_serving.to_crs(PLANAR_CRS))
        water_not_served_ix = _OverlapIndex(not_served.to_crs(PLANAR_CRS))
        water_layer_edited = max(
            (str(d) for d in water_gdf["last_edited"].dropna()), default=None
        )
        try:
            inter = gpd.overlay(
                planar[["geometry"]].reset_index(names="pidx"),
                serving.to_crs(PLANAR_CRS)[
                    ["area_name", "service_type", "comment", "geometry"]],
                how="intersection",
            )
            if len(inter) > 0:
                inter["area"] = inter.geometry.area
                best = inter.sort_values("area", ascending=False) \
                    .drop_duplicates("pidx").set_index("pidx")
                water_area_of = {i: row for i, row in best.iterrows()}
            # Wastewater companion: best wastewater-servicing area per parcel
            ww_inter = gpd.overlay(
                planar[["geometry"]].reset_index(names="pidx"),
                ww_serving.to_crs(PLANAR_CRS)[
                    ["area_name", "service_type", "geometry"]],
                how="intersection",
            )
            if len(ww_inter) > 0:
                ww_inter["area"] = ww_inter.geometry.area
                ww_best = ww_inter.sort_values("area", ascending=False) \
                    .drop_duplicates("pidx").set_index("pidx")
                ww_area_of = {i: row for i, row in ww_best.iterrows()}
        except Exception as e:  # noqa: BLE001
            logger.warning("Water service-area overlay failed: %s", e)

    # Curated parcel utility evidence (manual, dated public records).
    evidence_of = parcel_evidence or {}

    parcel_records: List[Dict[str, Any]] = []
    metric_rows: List[Dict[str, Any]] = []
    gate_rows: List[Dict[str, Any]] = []

    def metric(pin: str, key: str, value=None, text_value=None, unit=None,
               evidence="observed", layer="parcels", details=None,
               retrieved_at: Optional[str] = None) -> None:
        # retrieved_at defaults to this run's clock, which is right for a
        # value this run actually fetched. A value served from a cache must
        # pass the time it was really retrieved: the number is still correct
        # — a static DEM over an unchanged envelope does not drift — but
        # stamping it "now" would make the evidence claim something untrue,
        # and the evidence is the part being asked to carry weight.
        metric_rows.append({
            "parcel_key": pin,
            "metric_key": key,
            # NaN and infinity are not JSON, and pandas produces NaN
            # wherever a source had no value.
            "value": (lambda f: None if f is None else round(f, 4))(_num(value)),
            "text_value": text_value,
            "unit": unit,
            "evidence_class": evidence,
            "source_snapshot_id": snapshots.get(layer),
            "retrieved_at": retrieved_at or retrieve_time,
            "details": _json_safe(details or {}),
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

    # Interconnection (Release 5): nearest facility and metro density.
    network_of = network_evidence.nearest_facilities(planar, facilities, PLANAR_CRS)

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
            "legal_acreage": (lambda f: None if f is None else round(f, 3))(
                _num(legal_acreage)),
        })

        # ── metrics ───────────────────────────────────────────────────
        metric(pin, "total_acreage", gis_acreage, unit="acres", evidence="derived",
               layer="parcels", details={"basis": "GIS geometry", "legal_acreage": legal_acreage})

        # ── Release 4b: the county assessment roll ─────────────────────
        # The assessor's own figures, carried verbatim. A parcel absent
        # from the roll emits nothing at all rather than zeroes, which
        # would read as "worthless" instead of "unrecorded".
        # Reset per parcel: a carried-over slope would silently price this
        # site off the last one's terrain.
        median_slope_pct: Optional[float] = None

        # Jurisdictions publish assessment differently. Loudoun needs a
        # separate annual roll; Franklin County carries land, building,
        # total and CAUV value on the parcel feature itself. Either way it
        # arrives here in one shape.
        assessed = assessment_of(assessments, str(row["pin"]))
        if assessed is None and "land_value" in row.index:
            cauv = row.get("cauv_land_value")
            land = row.get("land_value")
            total = row.get("total_value")
            in_cauv = bool(row.get("in_cauv"))
            # Ohio defers by holding farmland at use value, so the sum
            # untaxed is market minus use value — the same quantity
            # Virginia reports directly as DEFERRED VALUE.
            deferred = (float(land) - float(cauv)
                        if in_cauv and land is not None and cauv is not None
                           and pd.notna(land) and pd.notna(cauv) else
                        (0.0 if land is not None and pd.notna(land) else None))
            assessed = {
                "assessment_class": (str(row.get("assessment_class"))
                                     if pd.notna(row.get("assessment_class")) else None),
                "land_value": float(land) if land is not None and pd.notna(land) else None,
                "building_value": (float(row["building_value"])
                                   if pd.notna(row.get("building_value")) else None),
                "total_value": float(total) if total is not None and pd.notna(total) else None,
                "land_use_value": float(cauv) if cauv is not None and pd.notna(cauv) else None,
                "deferred_value": deferred,
                "taxable_value": None,
                # The county publishes no per-parcel levy, unlike Loudoun.
                # Left absent rather than recomputed from a rate.
                "annual_tax": None,
                "in_land_use_deferral": in_cauv,
                "assessment_year": None,
                "source": ("Franklin County Auditor, tax parcel assessment "
                           "(carried on the parcel feature)"),
            }

        if assessed is not None:
            prov = {"source": assessed["source"],
                    "assessment_year": assessed["assessment_year"]}
            for key, mkey, unit in (
                ("land_value", "assessed_land_value_usd", "USD"),
                ("building_value", "assessed_building_value_usd", "USD"),
                ("total_value", "assessed_total_value_usd", "USD"),
                ("taxable_value", "assessed_taxable_value_usd", "USD"),
                ("annual_tax", "annual_property_tax_usd", "USD"),
            ):
                if assessed[key] is not None:
                    metric(pin, mkey, assessed[key], unit=unit,
                           evidence="observed", layer="assessment", details=prov)

            if assessed["assessment_class"]:
                metric(pin, "assessment_class", None,
                       text_value=assessed["assessment_class"],
                       evidence="observed", layer="assessment", details=prov)

            # Land value per acre — the comparable an underwriter reads
            # first, and the only derived figure in this block.
            if assessed["land_value"] is not None and gis_acreage > 0:
                metric(pin, "assessed_land_value_per_acre_usd",
                       assessed["land_value"] / gis_acreage, unit="USD/acre",
                       evidence="derived", layer="assessment",
                       details={**prov,
                                "basis": "fair market land value / GIS acreage"})

            # Land-use deferral. Recorded even when zero: "assessed at full
            # fair market value" is a real finding for a buyer, and its
            # absence would be indistinguishable from an unread roll.
            if assessed["deferred_value"] is not None:
                metric(pin, "land_use_deferred_value_usd",
                       assessed["deferred_value"], unit="USD",
                       evidence="observed", layer="assessment",
                       details={**prov,
                                "program": "Code of Virginia 58.1-3230 et seq.",
                                "conversion_liability": (
                                    "A change to a more intensive use triggers "
                                    "roll-back taxes under 58.1-3237: the five "
                                    "most recent complete tax years of deferred "
                                    "tax, plus simple interest."),
                                "land_use_value": assessed["land_use_value"]})
                metric(pin, "in_land_use_deferral", None,
                       text_value="yes" if assessed["in_land_use_deferral"] else "no",
                       evidence="observed", layer="assessment", details=prov)

        wet_pct = wetlands_ix.fraction(planar.geometry.loc[i], area_m2)
        fw_pct = floodway_ix.fraction(planar.geometry.loc[i], area_m2)
        fp_pct = floodplain_ix.fraction(planar.geometry.loc[i], area_m2)
        prot_pct = padus_ix.fraction(planar.geometry.loc[i], area_m2)

        if wetlands_gdf is not None:
            metric(pin, "wetland_pct", wet_pct, unit="percent", evidence="derived", layer="wetlands")
        if nfhl_gdf is not None:
            metric(pin, "floodway_pct", fw_pct, unit="percent", evidence="derived", layer="nfhl")
            metric(pin, "floodplain_pct", fp_pct, unit="percent", evidence="derived", layer="nfhl")
        if padus_gdf is not None:
            metric(pin, "protected_land_pct", prot_pct, unit="percent",
                   evidence="derived", layer="padus")
        if road_dist_mi is not None and i in road_dist_mi.index:
            metric(pin, "road_distance_miles", road_dist_mi.loc[i], unit="miles",
                   evidence="derived", layer="roads")
        # ── Release 6: parcel-level incentives ────────────────────────
        # Ohio grants abatements and TIF standing per parcel, so unlike a
        # statewide exemption these actually differentiate two neighbouring
        # sites. Both carry an end year: a benefit with a term, not a
        # permanent condition of the land.
        inc = incentives_of.get(str(row["pin"]))
        if inc:
            ab = inc.get("abatement")
            if ab:
                metric(pin, "tax_abatement", None,
                       text_value=str(ab.get("case_type") or ab.get("abatement_type")
                                      or "recorded"),
                       evidence="observed", layer="incentives", details=ab)
                if ab.get("end_year"):
                    metric(pin, "tax_abatement_end_year", None,
                           text_value=str(ab["end_year"]),
                           evidence="observed", layer="incentives",
                           details={**ab,
                                    "reading": ("the abatement lapses after this year; "
                                                "value beyond it should not be underwritten")})
            tf = inc.get("tif")
            if tf:
                metric(pin, "tif_district", None,
                       text_value=str(tf.get("name") or tf.get("project_no") or "in a TIF"),
                       evidence="observed", layer="incentives", details=tf)
                if tf.get("last_year"):
                    metric(pin, "tif_end_year", None, text_value=str(tf["last_year"]),
                           evidence="observed", layer="incentives", details=tf)

        # ── Release 5: interconnection ────────────────────────────────
        if network_of is not None and i in network_of.index:
            nf = network_of.loc[i]
            if pd.notna(nf["facility"]):
                prov = {"source": "PeeringDB", "facility_updated": nf["updated"]}
                metric(pin, "ixp_nearest_facility", None,
                       text_value=f'{nf["facility"]} ({nf["operator"]})',
                       evidence="observed", layer="interconnection",
                       details={**prov, "city": nf["city"],
                                "networks_present": _num(nf["net_count"]),
                                "carriers_present": _num(nf["carrier_count"]),
                                "exchanges_present": _num(nf["ix_count"])})
                metric(pin, "ixp_nearest_distance_miles",
                       float(nf["distance_miles"]), unit="miles",
                       evidence="derived", layer="interconnection", details=prov)
                metric(pin, "ixp_latency_floor_ms",
                       network_evidence.latency_floor_ms(float(nf["distance_miles"])),
                       unit="ms", evidence="derived", layer="interconnection",
                       details={**prov,
                                "basis": ("round trip for light through fibre over the "
                                          "straight-line distance; c / n with n = 1.4682 "
                                          "for standard single-mode fibre"),
                                "reading": ("a floor, not a forecast — no route is shorter "
                                            "than the straight line, and real paths run "
                                            "roughly 1.3-1.5x longer before switching")})
                nets = _num(nf["net_count"])
                if nets is not None:
                    metric(pin, "ixp_networks_at_nearest", int(nets),
                           unit="count", evidence="observed",
                           layer="interconnection", details=prov)
            # Each field is guarded on itself. A parcel with nothing inside
            # the radius has a real zero for the counts and NO best at all,
            # because there is no facility to take a maximum of — every
            # Taylor County parcel is like this, the nearest facility being
            # 138 miles away. Guarding all three on one of them cast that
            # NaN and killed the run.
            radius = {"radius_miles": 25, "source": "PeeringDB"}
            for key, mkey, extra in (
                ("facilities_within_25mi", "ixp_facilities_within_25mi", {}),
                ("networks_within_25mi", "ixp_networks_within_25mi", {}),
                ("best_networks_within_25mi", "ixp_best_facility_networks_within_25mi",
                 {"basis": ("largest facility in reach — the nearest one can be a "
                            "single-tenant room while a carrier hotel sits a mile "
                            "further out")}),
            ):
                v = _num(nf[key])
                if v is not None:
                    metric(pin, mkey, int(v), unit="count", evidence="derived",
                           layer="interconnection", details={**radius, **extra})

        if slopes is not None and i in slopes:
            # (max, median, n_samples, retrieved_at). retrieved_at is None
            # for a value this run fetched and an ISO date for one served
            # from the 3DEP envelope cache; passing it through keeps a
            # reused measurement from claiming to be fresher than it is.
            smax, smed, sn, slope_at = slopes[i]
            median_slope_pct = smed
            if smax is not None:
                slope_details = {"n_samples": sn}
                if slope_at:
                    slope_details["cached_envelope_sample"] = True
                metric(pin, "slope_max_pct", smax, unit="percent",
                       evidence="derived", layer="slope",
                       details=slope_details, retrieved_at=slope_at)
                metric(pin, "slope_median_pct", smed, unit="percent",
                       evidence="derived", layer="slope",
                       details=slope_details, retrieved_at=slope_at)

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

        # ── Release 4c: estimated costs, each citing its assumption ────
        # These are the only `estimated` rows in the system. Each carries
        # the observed inputs and the assumption that priced them, so the
        # number can always be taken apart rather than merely believed.
        if assessed is not None and assessed["deferred_value"] is not None:
            rb = underwriting.rollback_tax_exposure(
                assessed["deferred_value"], assumptions.get("land_use_rollback"))
            if rb is not None:
                # Emitted even at zero: "no roll-back exposure" is a real
                # finding for a buyer, not an absence of analysis.
                metric(pin, "land_use_rollback_tax_usd", rb["value"], unit="USD",
                       evidence="estimated", layer="assessment",
                       details=rb["details"])

        sp = underwriting.site_prep_cost(
            max(developable, 0.0), median_slope_pct, assumptions.get("site_prep"))
        if sp is not None:
            # A range, never a midpoint: the unit cost is not authoritative
            # and an expected value would invent precision it cannot carry.
            metric(pin, "site_prep_cost_low_usd", sp["low"], unit="USD",
                   evidence="estimated", layer="parcels", details=sp["details"])
            metric(pin, "site_prep_cost_high_usd", sp["high"], unit="USD",
                   evidence="estimated", layer="parcels", details=sp["details"])

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
                 "per FEMA flood hazard zones (NFHL).")

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

        # Verification-required layers — verdicts when the evidence layer
        # is present, explicit UNKNOWN when it is not.
        if padus_gdf is None:
            gate(pin, "protected_land", "UNKNOWN",
                 "PAD-US protected-areas layer unavailable for this run — "
                 "conservation status unverified.")
        elif prot_pct > prot_rule.get("fail_pct", 0.5):
            gate(pin, "protected_land", "FAIL",
                 f"{prot_pct:.1f}% of the parcel overlaps PAD-US protected "
                 f"areas (limit {prot_rule.get('fail_pct', 0.5)}%).",
                 affected=prot_pct)
        else:
            gate(pin, "protected_land", "PASS",
                 f"{prot_pct:.2f}% PAD-US protected-area overlap — below the "
                 f"{prot_rule.get('fail_pct', 0.5)}% screening limit.")

        if roads_gdf is None:
            gate(pin, "road_access", "UNKNOWN",
                 "TIGER road layer unavailable for this run — access and "
                 "truck routing unverified.")
        elif road_dist_mi is None or i not in road_dist_mi.index:
            gate(pin, "road_access", "UNKNOWN",
                 "No road-distance measurement for this parcel — access "
                 "unverified.")
        else:
            rmi = float(road_dist_mi.loc[i])
            if rmi > road_rule.get("fail_miles", 5):
                gate(pin, "road_access", "FAIL",
                     f"{rmi:.1f} mi to the nearest primary/secondary road — "
                     f"beyond the {road_rule.get('fail_miles', 5)}-mi limit.")
            elif rmi > road_rule.get("conditional_miles", 2):
                gate(pin, "road_access", "CONDITIONAL",
                     f"{rmi:.1f} mi to the nearest primary/secondary road — "
                     f"access road extension likely required.")
            else:
                gate(pin, "road_access", "PASS",
                     f"{rmi:.2f} mi to the nearest primary/secondary road.")

        # Water availability (observed boundary layer — Loudoun Water's
        # own published service areas; towns run municipal systems that
        # this layer does not cover, so town parcels stay UNKNOWN).
        if water_gdf is None:
            gate(pin, "water_availability", "UNKNOWN",
                 "Loudoun Water service-area boundary unavailable for this "
                 "run — public water availability unverified.")
        else:
            w_pct = water_serving_ix.fraction(planar.geometry.loc[i], area_m2)
            ns_pct = water_not_served_ix.fraction(planar.geometry.loc[i], area_m2)
            wa = water_area_of.get(i)
            metric(pin, "water_service_area_pct", w_pct, unit="percent",
                   evidence="derived", layer="water_service_areas")
            is_town = (zr is not None
                       and str(zr["zone"]) in dc_map.get("unknown_jurisdiction", []))
            no_new_conn = bool(wa is not None and "not permitted" in str(wa["comment"]).lower())
            if w_pct >= float(water_rule.get("pass_overlap_pct", 50)) and wa is not None:
                metric(pin, "water_service_provider", None,
                       text_value=f"Loudoun Water — {wa['area_name']}",
                       evidence="observed", layer="water_service_areas",
                       details={"service_type": str(wa["service_type"])})
                if no_new_conn:
                    gate(pin, "water_availability", "CONDITIONAL",
                         f"Inside Loudoun Water's published {wa['area_name']} "
                         f"service-area boundary, but the utility's record "
                         f"states: \"{wa['comment']}\" — connection "
                         f"availability must be confirmed with Loudoun Water.",
                         affected=w_pct,
                         details={
                             "area_name": str(wa["area_name"]),
                             "service_type": str(wa["service_type"]),
                             "comment": str(wa["comment"]),
                             "layer_edited": water_layer_edited,
                         })
                else:
                    gate(pin, "water_availability", "PASS",
                         f"Inside Loudoun Water's published {wa['area_name']} "
                         f"service area ({'water and wastewater' if str(wa['service_type']) == 'Both' else 'water'} "
                         f"service; utility boundary layer edited "
                         f"{water_layer_edited}). Public water service is "
                         f"available — capacity, pressure, and connection "
                         f"fees are diligence items.",
                         details={
                             "area_name": str(wa["area_name"]),
                             "service_type": str(wa["service_type"]),
                             "provider": "Loudoun Water",
                             "layer_edited": water_layer_edited,
                         })
            elif w_pct >= float(water_rule.get("conditional_overlap_pct", 5)):
                gate(pin, "water_availability", "CONDITIONAL",
                     f"{w_pct:.1f}% of the parcel lies inside Loudoun Water's "
                     f"published service area"
                     + (f" ({wa['area_name']})" if wa is not None else "")
                     + f" — the remainder requires a service extension.",
                     affected=100.0 - w_pct,
                     details={
                         "area_name": None if wa is None else str(wa["area_name"]),
                         "layer_edited": water_layer_edited,
                     })
            elif is_town:
                gate(pin, "water_availability", "UNKNOWN",
                     "Inside an incorporated town — the municipal water "
                     "provider is not covered by Loudoun Water's boundary "
                     "layer; provider and capacity unverified.",
                     details={"layer_edited": water_layer_edited})
            elif ns_pct >= float(water_rule.get("pass_overlap_pct", 50)):
                gate(pin, "water_availability", "FAIL",
                     f"Explicitly outside Loudoun Water's published service "
                     f"area per the utility's own boundary layer (edited "
                     f"{water_layer_edited}) — no mapped public water "
                     f"provider; on-site well supply would be required "
                     f"(diligence item).",
                     affected=ns_pct,
                     details={"not_served_overlap_pct": round(ns_pct, 3),
                              "layer_edited": water_layer_edited})
            else:
                gate(pin, "water_availability", "UNKNOWN",
                     f"Not covered by Loudoun Water's published service-area "
                     f"boundary (served-area overlap {w_pct:.1f}%, not-served "
                     f"overlap {ns_pct:.1f}%) — public water availability "
                     f"unverified.",
                     details={"layer_edited": water_layer_edited})

            # Wastewater companion metrics (informational, same layer —
            # ServiceType WW/Both areas; never a gate claim).
            ww_pct = ww_serving_ix.fraction(planar.geometry.loc[i], area_m2)
            metric(pin, "wastewater_service_area_pct", ww_pct, unit="percent",
                   evidence="derived", layer="water_service_areas")
            wwa = ww_area_of.get(i)
            if ww_pct >= float(water_rule.get("pass_overlap_pct", 50)) and wwa is not None:
                metric(pin, "wastewater_service_provider", None,
                       text_value=f"Loudoun Water — {wwa['area_name']}",
                       evidence="observed", layer="water_service_areas",
                       details={"service_type": str(wwa["service_type"])})

        if slopes is None:
            gate(pin, "slope", "UNKNOWN",
                 "3DEP slope derivation unavailable for this run — terrain "
                 "suitability unverified.")
        elif i not in slopes or slopes[i][0] is None:
            gate(pin, "slope", "UNKNOWN",
                 "3DEP elevation sampling failed for this parcel — terrain "
                 "suitability unverified.")
        else:
            smax, smed, _, _ = slopes[i]
            if smax > slope_rule.get("max_fail_pct", 25):
                gate(pin, "slope", "FAIL",
                     f"Max slope {smax:.1f}% exceeds the "
                     f"{slope_rule.get('max_fail_pct', 25)}% buildability limit.")
            elif smed > slope_rule.get("median_conditional_pct", 8):
                gate(pin, "slope", "CONDITIONAL",
                     f"Median slope {smed:.1f}% exceeds the "
                     f"{slope_rule.get('median_conditional_pct', 8)}% "
                     f"threshold — significant grading expected.")
            else:
                gate(pin, "slope", "PASS",
                     f"Max slope {smax:.1f}%, median {smed:.1f}% — terrain "
                     f"suitable (3DEP-derived).")

        # Power capacity (evidence gate — a MW figure is never asserted
        # without a dated source that supports it; none exists at parcel
        # level today, so PASS is reserved for a future parcel-specific
        # utility study document and is not awarded here).
        util = utility_of.get(i)
        q_kv = (float(queue_max_kv.loc[i])
                if queue_max_kv is not None and i in queue_max_kv.index
                and pd.notna(queue_max_kv.loc[i]) else None)
        if util is not None:
            metric(pin, "serving_utility", None, text_value=util["name"],
                   evidence="observed", layer="utility_territories")
            metric(pin, "serving_utility_type", None, text_value=util["type"],
                   evidence="observed", layer="utility_territories")
        if queue_counts is not None:
            metric(pin, "pjm_queue_points_within_3mi",
                   None if i not in queue_counts.index else int(queue_counts.loc[i]),
                   unit="count", evidence="observed", layer="pjm_queue",
                   details={"radius_miles": queue_radius_mi})
            if q_kv is not None:
                metric(pin, "pjm_queue_max_kv", q_kv, unit="kV",
                       evidence="observed", layer="pjm_queue")
        if apps_gdf is not None:
            apps_here = apps_of.get(i, [])
            metric(pin, "dc_application_on_parcel", len(apps_here),
                   unit="count", evidence="observed", layer="county_applications",
                   details={"applications": apps_here} if apps_here else {})
            if apps_here:
                latest = max(a["approval_date"] for a in apps_here)
                metric(pin, "dc_application_latest_approval", None,
                       text_value=latest, evidence="observed",
                       layer="county_applications",
                       details={"applications": apps_here})

        if rtep_area is not None:
            metric(pin, "rtep_area_active_upgrades", rtep_area["active"],
                   unit="count", evidence="derived", layer="rtep_upgrades",
                   details={"statuses": active_statuses, "scope": "county area"})
            metric(pin, "rtep_area_energization_range", None,
                   text_value=(f"{rtep_area['earliest_energization']}.."
                               f"{rtep_area['latest_energization']}"),
                   evidence="derived", layer="rtep_upgrades",
                   details={"basis": "projected in-service dates, PJM RTEP"})
            metric(pin, "rtep_latest_board_approval", None,
                   text_value=rtep_area["latest_board_approval"],
                   evidence="derived", layer="rtep_upgrades")

            # ── Release 4a: commercial signal from the same dated record ──
            # Area figures, never parcel claims: this is what the serving
            # transmission area is spending and how well it hits its dates.
            if rtep_area.get("cost_musd") is not None:
                metric(pin, "rtep_area_upgrade_cost_musd",
                       rtep_area["cost_musd"], unit="USD millions",
                       evidence="derived", layer="rtep_upgrades",
                       details={
                           "scope": "county area",
                           "upgrades_costed": rtep_area["cost_reported"],
                           "basis": ("sum of PJM Board-approved project cost "
                                     "estimates for active in-area upgrades"),
                           "caveat": ("PJM's own estimates, not actual spend, "
                                      "and not attributable to a single parcel"),
                       })
            sched = rtep_area.get("schedule")
            if sched:
                metric(pin, "rtep_area_schedule_slip_median_days",
                       sched["median_days"], unit="days",
                       evidence="derived", layer="rtep_upgrades", details=sched)
                metric(pin, "rtep_area_schedule_slip_p90_days",
                       sched["p90_days"], unit="days",
                       evidence="derived", layer="rtep_upgrades", details=sched)
                metric(pin, "rtep_area_on_time_pct", sched["on_time_pct"],
                       unit="percent", evidence="derived",
                       layer="rtep_upgrades", details=sched)

        parcel_ev = evidence_of.get(pin, [])
        if parcel_ev:
            # Dated parcel-specific utility evidence on file (curated from
            # the public county record — quotes verbatim, never derived).
            best = max(parcel_ev, key=lambda r: r.get("document_date") or "")
            mw = best.get("capacity_mw")
            metric(pin, "parcel_utility_evidence", None,
                   text_value="dated_county_record", evidence="manual",
                   layer="county_applications",
                   details={
                       "applications": [r.get("application_number") for r in parcel_ev],
                       "document": best.get("document_name"),
                       "document_date": best.get("document_date"),
                   })
            if mw is not None:
                metric(pin, "parcel_utility_evidence_mw", float(mw), unit="MW",
                       evidence="manual", layer="county_applications",
                       details={
                           "document": best.get("document_name"),
                           "document_date": best.get("document_date"),
                           "basis": "stated in the dated county record — never derived",
                       })

        if util is None and utility_gdf is not None:
            evidence_level = "none"
        elif parcel_ev:
            evidence_level = "parcel_dated_record"
        elif rtep_area is not None:
            evidence_level = "area_reinforcement"
        elif util is not None:
            evidence_level = "utility_identified"
        else:
            evidence_level = "none"
        if evidence_level != "none":
            metric(pin, "power_evidence_level", None, text_value=evidence_level,
                   evidence="derived", layer="rtep_upgrades")

        if parcel_ev:
            mw_note = (
                f"The record documents a capacity figure of {float(mw):.0f} MW."
                if mw is not None else
                "No MW figure is asserted — the record documents utility "
                "service, not a capacity number."
            )
            gate(pin, "power_capacity", "PASS",
                 f"Dated parcel-specific utility evidence on file: approved "
                 f"{best.get('application_type')} {best.get('application_number')} "
                 f"(County approval {best.get('approval_date')}) — "
                 f"\"{best.get('utility_statement')}\" "
                 f"({best.get('document_name')}, {best.get('document_date')}; "
                 f"public LandMARC record). {mw_note}",
                 details={
                     "evidence_level": evidence_level,
                     "application_number": best.get("application_number"),
                     "approval_date": best.get("approval_date"),
                     "document": best.get("document_name"),
                     "document_date": best.get("document_date"),
                     "documented_mw": mw,
                     "source_url": best.get("source_url"),
                     "documents": ["pjm_rtep_construction_status"],
                 })
        elif utility_gdf is None and rtep_df is None:
            gate(pin, "power_capacity", "UNKNOWN",
                 "Power diligence layers unavailable for this run — serving "
                 "utility and capacity evidence unverified.")
        elif util is None:
            gate(pin, "power_capacity", "UNKNOWN",
                 "No electric utility service territory covers this parcel "
                 "in the HIFLD territory layer (sourced 2023) — serving "
                 "utility unverified.", details={"evidence_level": evidence_level})
        elif rtep_df is None:
            gate(pin, "power_capacity", "UNKNOWN",
                 f"Served by {util['name']} ({util['type']}), but the PJM RTEP "
                 f"upgrade dataset was unavailable — no dated transmission "
                 f"evidence could be reviewed.",
                 details={"evidence_level": evidence_level})
        elif rtep_area is None:
            gate(pin, "power_capacity", "UNKNOWN",
                 f"Served by {util['name']} ({util['type']}) — no active "
                 f"PJM Board-approved upgrades are documented in this county "
                 f"area, so no dated source supports a capacity figure. A "
                 f"PJM/utility large-load study is required before any MW "
                 f"claim.", details={"evidence_level": evidence_level})
        else:
            gate(pin, "power_capacity", "CONDITIONAL",
                 f"Served by {util['name']} ({util['type']}; HIFLD 2023). "
                 f"{rtep_area['active']} PJM Board-approved transmission "
                 f"upgrades are active in this county area (latest Board "
                 f"approval {rtep_area['latest_board_approval']}; projected "
                 f"energization {rtep_area['earliest_energization']}–"
                 f"{rtep_area['latest_energization']}; PJM RTEP Construction "
                 f"Status updated {rtep_area['source_updated']}). Area "
                 f"evidence only — parcel-specific capacity requires a "
                 f"PJM/utility large-load study; no MW figure is asserted.",
                 details={
                     "evidence_level": evidence_level,
                     "active_upgrades": rtep_area["active"],
                     "energization_range": (f"{rtep_area['earliest_energization']}.."
                                            f"{rtep_area['latest_energization']}"),
                     "board_approval": rtep_area["latest_board_approval"],
                     "documents": ["pjm_rtep_construction_status"],
                 })

    stats = {
        "parcels_qualified": n,
        "zoning_coverage_pct": zoning_coverage,
        "wetlands_layer": "present" if wetlands_gdf is not None else "missing",
        "nfhl_layer": "present" if nfhl_gdf is not None else "missing",
        "padus_layer": "present" if padus_gdf is not None else "missing",
        "roads_layer": "present" if roads_gdf is not None else "missing",
        "slope_layer": "present" if slopes is not None else "missing",
        "utility_layer": "present" if utility_gdf is not None else "missing",
        "rtep_layer": "present" if rtep_df is not None else "missing",
        "rtep_area_active": (rtep_area or {}).get("active"),
        "queue_layer": "present" if queue_gdf is not None else "missing",
        "county_applications_layer": "present" if apps_gdf is not None else "missing",
        "water_layer": "present" if water_gdf is not None else "missing",
        "water_layer_edited": water_layer_edited,
        "parcels_with_dc_application": len(apps_of),
        "parcels_water_served": sum(
            1 for i in water_area_of
            if water_serving_ix.fraction(planar.geometry.loc[i], float(parcel_area_m2.loc[i]))
            >= float(water_rule.get("pass_overlap_pct", 50))
            and "not permitted" not in str(water_area_of[i]["comment"]).lower()
        ),
        "parcels_water_not_served": sum(
            1 for i in planar.index
            if water_not_served_ix.fraction(planar.geometry.loc[i], float(parcel_area_m2.loc[i]))
            >= float(water_rule.get("pass_overlap_pct", 50))
        ),
        "parcels_with_utility_evidence": len(set(evidence_of) & {p["parcel_key"] for p in parcel_records}),
        "slope_sampled_ok": sum(1 for v in (slopes or {}).values() if v[2] > 0),
        "metric_rows": len(metric_rows),
        "gate_rows": len(gate_rows),
    }
    logger.info("Qualification complete: %s", stats)
    return parcel_records, metric_rows, gate_rows, stats
