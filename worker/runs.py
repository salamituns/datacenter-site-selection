"""
Ingestion run lifecycle — provenance, staged writes, atomic publication.

Every pipeline execution becomes a row in `ingestion_runs`. Each source
fetch is recorded in `source_snapshots` with its evidence class. All
computed data lands in `stg_*` staging tables, and nothing becomes
client-visible until `promote_ingestion_run()` swaps the complete run
into the published tables inside a single database transaction. A failure
anywhere calls `fail_ingestion_run()` and re-raises, so scheduled jobs
fail loudly instead of publishing partial data.
"""

import logging
import os
import random
import uuid as uuidlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pipeline.runs")

CHUNK = 200  # rows per staged insert


def _now_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class IngestionRun:
    """Tracks one pipeline execution and its staged, atomic publication."""

    def __init__(self, client: Any, region_code: str, pipeline_version: str,
                 trigger: str = "manual", config: Optional[Dict[str, Any]] = None):
        self.client = client
        self.region_code = region_code
        self.pipeline_version = pipeline_version
        self.trigger = trigger
        self.config = config or {}
        self.run_id: Optional[str] = None
        self._source_ids: Dict[str, str] = {}
        self._rule_ids: Dict[str, str] = {}

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> str:
        run_key = f"{self.region_code}-{_now_key()}-{random.randrange(0x10000):04x}"
        res = self.client.table("ingestion_runs").insert({
            "run_key": run_key,
            "region_code": self.region_code,
            "pipeline_version": self.pipeline_version,
            "trigger": self.trigger,
            "config": self.config,
        }).execute()
        self.run_id = str(res.data[0]["id"])
        logger.info("Ingestion run %s started (%s)", run_key, self.run_id)
        return self.run_id

    def record_layers(self, layers: Dict[str, str]) -> None:
        """
        Records the {layer: present|missing} availability map on the run.

        promote_ingestion_run refuses to publish a run that would drop a
        layer the live generation had — the Taylor County incident, where a
        PAD-US outage turned 91 decided protected-land verdicts into 4,356
        UNKNOWNs overnight — and it reads the map from ingestion_runs.stats,
        so the map has to be on the row before the swap, not merged into it
        afterwards. Read-modify-write is safe here: nothing else writes this
        row between start() and promote(). A failure to record raises rather
        than degrading quietly, because a run with no map is exactly the
        blind spot the guard exists to close.
        """
        if not self.run_id:
            raise RuntimeError("record_layers() called before start()")
        res = self.client.table("ingestion_runs").select("stats") \
            .eq("id", self.run_id).single().execute()
        stats = dict((res.data or {}).get("stats") or {})
        stats["layers"] = layers
        self.client.table("ingestion_runs").update({"stats": stats}) \
            .eq("id", self.run_id).execute()
        logger.info("Run %s layer availability recorded: %s",
                    self.run_id, layers)

    def promote(self, allow_coverage_regression: bool = False) -> Dict[str, Any]:
        """
        Atomically publishes the complete staged run.

        allow_coverage_regression is the operator override for the
        database's coverage guard, not a routine flag: True publishes a run
        that would drop a layer the live generation had, which is a
        deliberate, recorded decision rather than something a scheduled
        sweep should ever pass.
        """
        if not self.run_id:
            raise RuntimeError("promote() called before start()")
        res = self.client.rpc("promote_ingestion_run", {
            "p_run_id": self.run_id,
            "p_allow_coverage_regression": allow_coverage_regression,
        }).execute()
        counts = res.data
        logger.info("Run %s promoted atomically: %s", self.run_id, counts)
        return counts

    def fail(self, error: str) -> None:
        """Best-effort failure record — never masks the original error."""
        if not self.run_id:
            return
        try:
            self.client.rpc("fail_ingestion_run", {
                "p_run_id": self.run_id, "p_error": error[:4000],
            }).execute()
        except Exception as record_err:  # noqa: BLE001
            logger.error("Could not record run failure: %s", record_err)

    # ── provenance ───────────────────────────────────────────────────────

    def snapshot(self, layer: str, source_key: str, endpoint_url: str,
                 record_count: Optional[int], evidence_class: str,
                 dataset_version: Optional[str] = None,
                 quality: Optional[Dict[str, Any]] = None,
                 notes: Optional[str] = None) -> Optional[str]:
        """Records one source fetch; returns the snapshot id for metrics."""
        if not self.run_id:
            return None
        source_id = self._source_ids.get(source_key)
        if source_id is None:
            res = self.client.table("data_sources").select("id") \
                .eq("source_key", source_key).limit(1).execute()
            source_id = res.data[0]["id"] if res.data else None
            self._source_ids[source_key] = source_id
        res = self.client.table("source_snapshots").insert({
            "run_id": self.run_id,
            "source_id": source_id,
            "layer": layer,
            "endpoint_url": endpoint_url,
            "record_count": record_count,
            "evidence_class": evidence_class,
            "dataset_version": dataset_version,
            "quality": quality or {},
            "notes": notes,
        }).execute()
        return str(res.data[0]["id"])

    def rule_id(self, gate_key: str, jurisdiction: str, rule_version: str) -> Optional[str]:
        """Resolves a constraint rule id (no generated ids hardcoded)."""
        cache_key = f"{gate_key}:{jurisdiction}:{rule_version}"
        if cache_key in self._rule_ids:
            return self._rule_ids[cache_key]
        res = self.client.table("constraint_rules").select("id") \
            .eq("gate_key", gate_key).eq("jurisdiction", jurisdiction) \
            .eq("rule_version", rule_version).limit(1).execute()
        rule_id = str(res.data[0]["id"]) if res.data else None
        self._rule_ids[cache_key] = rule_id
        return rule_id

    def load_rules(self, jurisdiction: str) -> Dict[str, Dict[str, Any]]:
        """Loads {gate_key: {"id": ..., "params": ..., "rule_version": ...}}
        for a jurisdiction.

        Only unsuperseded rows are read, so which version governs is a fact
        recorded in the table rather than an inference from insertion order.
        constraint_rules stays append-only: a run's gate rows keep the
        rule_id that actually decided them, and a new version governs from
        the next run without mutating the row that decided the last one.

        This replaced a newest-by-created_at convention. That convention was
        correct and invisible — supersession lived in the description text
        as "(supersedes X)", so nothing could answer "is this run deciding
        under the current rule?" without parsing English. v_region_rule_drift
        answers it now, and only because the relationship became data.
        """
        res = self.client.table("constraint_rules") \
            .select("id,gate_key,rule_version,params,reviewed_at,reviewed_against") \
            .eq("jurisdiction", jurisdiction) \
            .is_("superseded_by", "null") \
            .order("created_at").execute()
        rules = _rows_to_rules(res.data or [])
        _log_rule_currency(jurisdiction, rules)
        _warn_inert_rules(jurisdiction, rules)
        return rules

    def fetch_power_parcel_evidence(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Curated parcel utility evidence (power_parcel_evidence) keyed by
        parcel_key. These are the dated county records (LandMARC public
        files) behind power_capacity PASS verdicts — manual evidence,
        quoted verbatim, never derived.
        """
        res = self.client.table("v_power_parcel_evidence").select("*").execute()
        out: Dict[str, List[Dict[str, Any]]] = {}
        for r in res.data or []:
            out.setdefault(r["parcel_key"], []).append(r)
        if out:
            logger.info("Parcel utility evidence: %d curated records for %d parcels.",
                        sum(len(v) for v in out.values()), len(out))
        return out

    def load_jurisdiction_restrictions(self, state_code: str
                                       ) -> Optional[List[Dict[str, Any]]]:
        """
        Moratorium/restriction evidence rows for a state, for the
        moratorium gate. Rows are few (one per reviewed jurisdiction) and
        the gate matches them to parcels by county, place and township
        name, so the whole state loads and the matching happens where the
        parcel's jurisdictions are known. None means the table could not
        be read — the gate then holds at UNKNOWN rather than reading
        silence as "nothing restricted".
        """
        return _load_jurisdiction_restrictions(self.client, state_code)

    # ── staged writes (chunked inserts, nothing published yet) ──────────

    def _stage(self, table: str, rows: List[Dict[str, Any]]) -> None:
        if not self.run_id or not rows:
            return
        for i in range(0, len(rows), CHUNK):
            self.client.table(table).insert(rows[i:i + CHUNK]).execute()
        logger.info("Staged %d rows into %s", len(rows), table)

    def stage_grid_parcels(self, records: List[Dict[str, Any]]) -> None:
        rows = [{**r, "run_id": self.run_id} for r in records]
        self._stage("stg_grid_parcels", rows)

    def stage_transmission_lines(self, records: List[Dict[str, Any]]) -> None:
        rows = [{**r, "run_id": self.run_id} for r in records]
        self._stage("stg_transmission_lines", rows)

    def stage_substations(self, records: List[Dict[str, Any]]) -> None:
        rows = [{**r, "run_id": self.run_id} for r in records]
        self._stage("stg_substations", rows)

    def stage_observation_wells(self, records: List[Dict[str, Any]]) -> None:
        rows = [{**r, "run_id": self.run_id} for r in records]
        self._stage("stg_observation_wells", rows)

    def stage_power_rtep_upgrades(self, records: List[Dict[str, Any]]) -> None:
        rows = [{**r, "run_id": self.run_id} for r in records]
        self._stage("stg_power_rtep_upgrades", rows)

    def stage_land_parcels(self, records: List[Dict[str, Any]]) -> None:
        rows = [{**r, "run_id": self.run_id} for r in records]
        self._stage("stg_land_parcels", rows)

    def stage_parcel_metrics(self, rows: List[Dict[str, Any]]) -> None:
        for r in rows:
            r["run_id"] = self.run_id
        self._stage("stg_parcel_metric_values", rows)

    def stage_parcel_gates(self, rows: List[Dict[str, Any]]) -> None:
        for r in rows:
            r["run_id"] = self.run_id
        self._stage("stg_parcel_gate_results", rows)


def _rows_to_rules(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    # Callers filter on superseded_by IS NULL, so at most one row per
    # gate_key arrives and "which version governs" is a fact in the table
    # rather than a convention about insertion order. created_at ordering is
    # kept only as a tiebreak for the transitional case of two unsuperseded
    # rows, which the backfill left none of.
    return {r["gate_key"]: {"id": str(r["id"]),
                            "params": r["params"] or {},
                            "rule_version": r.get("rule_version"),
                            "reviewed_at": r.get("reviewed_at"),
                            "reviewed_against": r.get("reviewed_against")}
            for r in rows}


# The parameter each gate actually reads out of its rule. A rule row whose
# params omit this key decides nothing: parcel_gates falls through to
# DEFAULT_RULE_PARAMS and the row sits in the table looking authoritative.
#
# Nine rows were in exactly that state — three counties' floodway rules said
# fail_pct 25 while the gate read floodway_fail_pct and applied 0.5. The
# values happened to be the safer ones, which is why it went unnoticed: the
# verdicts were right and the stated reasons were fiction.
GATE_GOVERNING_PARAM: Dict[str, str] = {
    "contiguous_acreage": "min_pass_acres",
    "floodway": "floodway_fail_pct",
    "protected_land": "fail_pct",
    "road_access": "fail_miles",
    "slope": "max_fail_pct",
    "water_availability": "pass_overlap_pct",
    "wetlands": "fail_pct",
    "power_capacity": "queue_radius_miles",
    "zoning_dc_use": "by_right",
}


def _warn_inert_rules(jurisdiction: str, rules: Dict[str, Dict[str, Any]]) -> None:
    """
    Names rules that look authoritative and govern nothing.

    "Rules are data, not code" is the claim this table exists to make good
    on, and a row whose params the gate never reads quietly breaks it. The
    failure is silent by construction: the gate finds no key, takes its
    built-in default, and produces a perfectly reasonable verdict under a
    threshold nobody wrote down.

    zoning_dc_use is exempt from the refusal elsewhere in the engine (a
    zoning layer with no use table stops the run outright); here it is simply
    reported alongside the others.
    """
    inert = []
    for gate_key, rule in rules.items():
        needed = GATE_GOVERNING_PARAM.get(gate_key)
        if not needed:
            continue
        params = rule.get("params") or {}
        if needed not in params:
            inert.append(f"{gate_key} (no '{needed}' in params; "
                         f"{rule.get('rule_version')})")
    if inert:
        logger.warning(
            "Rules that decide nothing for %s: %s — the gate falls back to its "
            "built-in default, so the published threshold is not the one on "
            "file.", jurisdiction, "; ".join(sorted(inert)))


def _log_rule_currency(jurisdiction: str, rules: Dict[str, Dict[str, Any]]) -> None:
    """
    States how old the rules deciding this run are.

    The engine cannot know an ordinance changed — only that nobody has
    checked lately. Loudoun's use table claimed to reflect a March 2025
    amendment it did not reflect, and decided 119 parcels for months before
    anyone read the ordinance again. A rule with no recorded review is
    reported as exactly that, because "never checked" is a finding and not
    a default.
    """
    unreviewed = sorted(k for k, v in rules.items() if not v.get("reviewed_at"))
    reviewed = {k: v.get("reviewed_at") for k, v in rules.items()
                if v.get("reviewed_at")}
    if reviewed:
        logger.info("Rule review dates for %s: %s", jurisdiction,
                    ", ".join(f"{k} {d}" for k, d in sorted(reviewed.items())))
    if unreviewed:
        logger.warning(
            "Rules with no recorded review for %s: %s — these decide gates "
            "against a source nobody has verified on the record.",
            jurisdiction, ", ".join(unreviewed))


def load_rules_readonly(jurisdiction: str) -> Dict[str, Dict[str, Any]]:
    """
    Reads a jurisdiction's constraint_rules without a write client.

    Same shape and same rows as IngestionRun.load_rules, for the dry run:
    constraint_rules is world-readable, so a run with no service key still
    decides against the rules a publish would use. Before this existed the
    dry run fell back to the built-in defaults, which for zoning_dc_use
    was another county's use table — and the engine now refuses a
    zoning-supplying run with no rule row, so the dry run has to be able
    to see the real one. Returns {} when the rules cannot be read; the
    refusal in qualify_parcels then stops the run rather than guessing.
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        logger.info("No client for constraint_rules — built-in defaults only; "
                    "a zoning-supplying run will refuse rather than fall back.")
        return {}
    try:
        from supabase import create_client
        client = create_client(url, key)
        # Same newest-version-wins contract as IngestionRun.load_rules:
        # created_at order, last row per gate_key governs.
        res = client.table("constraint_rules") \
            .select("id,gate_key,rule_version,params,reviewed_at,reviewed_against") \
            .eq("jurisdiction", jurisdiction) \
            .is_("superseded_by", "null") \
            .order("created_at").execute()
        rules = _rows_to_rules(res.data or [])
        _log_rule_currency(jurisdiction, rules)
        _warn_inert_rules(jurisdiction, rules)
        logger.info("constraint_rules for %s (read-only): %s",
                    jurisdiction, sorted(rules) or "none")
        return rules
    except Exception as e:  # noqa: BLE001
        logger.warning("constraint_rules unreadable (%s) — built-in defaults "
                       "only; a zoning-supplying run will refuse.", e)
        return {}


# The moratorium gate's evidence rows — one SELECT, shared by the
# publishing client and the dry run's read-only one, so both decide
# against the same rows. None is "could not read", never "no rows": the
# distinction is the whole contract (an unread layer holds the gate at
# UNKNOWN; an empty one means no jurisdiction reviewed yet, which also
# reads UNKNOWN but says so honestly).
_RESTRICTION_FIELDS = (
    "state_code,county_name,place_name,subdivision_name,status,"
    "instrument,adopting_body,adopted_date,effective_date,expires_date,"
    "scope,source_url,basis,reviewed_at,sources_checked"
)


def _load_jurisdiction_restrictions(client: Any, state_code: str
                                    ) -> Optional[List[Dict[str, Any]]]:
    try:
        res = client.table("jurisdiction_restrictions") \
            .select(_RESTRICTION_FIELDS) \
            .eq("state_code", state_code.upper()) \
            .order("created_at").execute()
        rows = res.data or []
        logger.info("jurisdiction_restrictions for %s: %d rows.",
                    state_code.upper(), len(rows))
        return rows
    except Exception as e:  # noqa: BLE001
        logger.warning("jurisdiction_restrictions unreadable (%s) — "
                       "moratorium gate held at UNKNOWN.", e)
        return None


def load_jurisdiction_restrictions_readonly(state_code: str
                                            ) -> Optional[List[Dict[str, Any]]]:
    """
    Same rows as IngestionRun.load_jurisdiction_restrictions, without a
    write client — the table is world-readable, so a dry run decides
    against the evidence a publish would use.
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        logger.info("No client for jurisdiction_restrictions — moratorium "
                    "gate held at UNKNOWN.")
        return None
    try:
        from supabase import create_client
        return _load_jurisdiction_restrictions(
            create_client(url, key), state_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("jurisdiction_restrictions unreadable (%s) — "
                       "moratorium gate held at UNKNOWN.", e)
        return None
