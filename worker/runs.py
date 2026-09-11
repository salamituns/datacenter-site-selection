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

    def promote(self) -> Dict[str, Any]:
        """Atomically publishes the complete staged run."""
        if not self.run_id:
            raise RuntimeError("promote() called before start()")
        res = self.client.rpc("promote_ingestion_run", {"p_run_id": self.run_id}).execute()
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
        for a jurisdiction."""
        res = self.client.table("constraint_rules") \
            .select("id,gate_key,rule_version,params") \
            .eq("jurisdiction", jurisdiction).execute()
        return _rows_to_rules(res.data or [])

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
    return {r["gate_key"]: {"id": str(r["id"]),
                            "params": r["params"] or {},
                            "rule_version": r.get("rule_version")}
            for r in rows}


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
        res = client.table("constraint_rules").select("id,gate_key,params") \
            .eq("jurisdiction", jurisdiction).execute()
        rules = _rows_to_rules(res.data or [])
        logger.info("constraint_rules for %s (read-only): %s",
                    jurisdiction, sorted(rules) or "none")
        return rules
    except Exception as e:  # noqa: BLE001
        logger.warning("constraint_rules unreadable (%s) — built-in defaults "
                       "only; a zoning-supplying run will refuse.", e)
        return {}
