"""
Screen the PJM footprint, a batch at a time.

552 counties clear the screening threshold (region_registry.pjm_screening_regions).
At roughly five minutes each that is some forty-five hours of work, which is
not one job anywhere — GitHub Actions caps at six, and this repo's pipeline
workflow caps itself at ninety minutes. So it runs in batches, and the two
design choices that make batching safe are both about not keeping state.

PROGRESS IS THE PUBLISHED DATA, NOT A FILE. A county is done when it has
screening cells in grid_parcels. Nothing tracks a cursor, nothing has to be
reset after a failure, and a batch that dies halfway leaves the next batch
able to work out exactly where it stopped. A progress file would be a second
copy of a fact the database already holds, and this project has been bitten
three times by exactly that shape — the hand-typed bboxes, the hand-kept FIPS
map, the client's hardcoded region list.

BATCHES RUN IN STATE ORDER, which groups a state's counties together for
whatever reuse the caches can give. Be careful about how much that is: an
earlier version of this note claimed "88 Ohio counties share one PAD-US
download and one NWI geodatabase", and that is FALSE. Two things in
overlay_layers limit it, and both are worth knowing before planning a sweep:

  * The clip caches hold ONE clip per state file. _save_cached_clip unlinks
    and rewrites, and _load_cached_clip counts a request the cached bbox
    does not CONTAIN as a miss. So county B reuses county A's clip only if
    B's bbox sits inside A's, which for two counties side by side it does
    not. Sequential counties overwrite each other.
  * The raw state downloads — the NWI geodatabase, the PAD-US state GDB —
    are fetched into a tempfile directory and discarded. Only the clip
    survives, and the clip is the part that gets overwritten.

State order is still the right order: it keeps a state's work together, and
it is what any real caching fix would build on. It is just not, today, the
reason a sweep is affordable.

These counties have no cadastral adapter, so the parcel tier never runs: they
publish screening cells with federal-layer measurements attached and no
verdicts, which is what the national tier was built to do. Lexicographic
tiering keeps them below every qualified parcel whatever their score.

HONEST DEGRADATION MUST BE RECOVERABLE, not just survivable. A county that
publishes with a layer unreachable degrades to UNKNOWN rather than guessing —
and since the coverage guard landed, the run records which layers answered in
stats.layers and promote refuses to replace decided evidence with a thinner
generation. --incomplete is the other half: it selects counties whose live
run recorded a missing layer, so a degraded publish is re-run once the layer
is reachable instead of sitting as UNKNOWN forever. The list is derived from
the published runs, not a retry file — same rule as progress itself.
"""

import argparse
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import region_registry
from pipeline import run_pipeline

logger = logging.getLogger("pjm_screening")


def published_regions() -> set:
    """
    Region keys that already have screening cells.

    Read with whatever key is available: the anon key can read grid_parcels,
    so a dry run can report progress without a service key in the environment.
    Returns an empty set when nothing can be read, which makes the runner
    treat every county as unscreened — safe, because publishing a county twice
    republishes it rather than duplicating it.
    """
    url = os.getenv("SUPABASE_URL")
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY")
           or os.getenv("SUPABASE_ANON_KEY"))
    if not url or not key:
        logger.warning("No client for grid_parcels — cannot tell which "
                       "counties are already screened; treating all as unscreened.")
        return set()
    try:
        from supabase import create_client
        client = create_client(url, key)
        seen, page, size = set(), 0, 1000
        while True:
            # order() is not cosmetic: PostgREST's range() pages a plain
            # SELECT, and Postgres guarantees no row order without an
            # ORDER BY, so unordered paging can return a row twice and
            # skip another. Here a skipped row can drop a region from
            # the "already screened" set and make the runner redo a
            # county it has done. Measured while auditing the flood
            # gate: the same two queries disagreed by 69 rows.
            res = client.table("grid_parcels").select("region_key") \
                .order("id").range(page * size, page * size + size - 1).execute()
            rows = res.data or []
            seen.update(r["region_key"] for r in rows if r.get("region_key"))
            if len(rows) < size:
                break
            page += 1
        return seen
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read published regions (%s); treating all "
                       "as unscreened.", e)
        return set()


def _recorded_missing_layers(stats: Optional[Dict[str, Any]]) -> bool:
    """
    True when a run's stats.layers marks any layer missing.

    A run from before the map existed (no layers key) is not incomplete —
    it predates the record, and treating it as degraded would put every
    legacy county on the recovery list forever. The coverage guard handles
    such runs at promote time; recovery only re-runs what was recorded.
    """
    layers = (stats or {}).get("layers") or {}
    return any(v == "missing" for v in layers.values())


def incomplete_regions() -> set:
    """
    Region keys whose live succeeded run recorded a missing layer.

    Read from ingestion_runs.stats.layers — the map the worker writes
    before promote and the coverage guard compares. A county that
    published UNKNOWN because PAD-US was unreachable one afternoon stays
    on this list until a run with the layer back promotes over it.
    Returns an empty set when nothing can be read, which reads as "nothing
    to recover" — the safe direction, because recovery only ever re-runs
    and never destroys.
    """
    url = os.getenv("SUPABASE_URL")
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY")
           or os.getenv("SUPABASE_ANON_KEY"))
    if not url or not key:
        logger.warning("No client for ingestion_runs — cannot tell which "
                       "counties published with a missing layer.")
        return set()
    try:
        from supabase import create_client
        client = create_client(url, key)
        incomplete, seen, page, size = set(), set(), 0, 1000
        while True:
            # Ordered paging, same reason as published_regions: Postgres
            # guarantees no row order without an ORDER BY, and a row
            # returned twice or skipped here would silently drop a county
            # from recovery. Promote supersedes, so at most one succeeded
            # run per region should exist — but if that ever drifts, the
            # finished_at ordering keeps "latest" well-defined.
            res = (client.table("ingestion_runs")
                   .select("region_code, stats")
                   .eq("status", "succeeded")
                   .order("finished_at", desc=True)
                   .order("id")
                   .range(page * size, page * size + size - 1).execute())
            rows = res.data or []
            for r in rows:
                region = r.get("region_code")
                if not region or region in seen:
                    continue
                seen.add(region)
                if _recorded_missing_layers(r.get("stats")):
                    incomplete.add(region)
            if len(rows) < size:
                break
            page += 1
        return incomplete
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read incomplete regions (%s); treating "
                       "none as degraded.", e)
        return set()


def next_batch(limit: int, state: Optional[str] = None,
               redo: bool = False, incomplete: bool = False) -> List[str]:
    """
    The next `limit` PJM counties to screen, in state order.

    incomplete=True replaces the criterion rather than widening it: the
    batch is counties whose live run recorded a missing layer, not
    counties with no cells. A county with a full layer set never appears,
    whatever --redo says — recovery is for the degraded, not the bored.
    """
    if incomplete:
        # Recovery is scoped to what we PUBLISHED, not to the sweep.
        #
        # This used to start from the footprint and intersect the degraded
        # set, which quietly made the footprint a precondition for being
        # recoverable. The only degraded region in the database was
        # OR-MORROW, which sits outside PJM — so the tool reported
        # "Nothing to do" while the one county that needed recovery was
        # unreachable by it. A county does not stop deserving its
        # protected-land evidence because it fell outside a screening
        # threshold.
        regions = sorted(incomplete_regions())
    else:
        regions = region_registry.pjm_screening_regions()
    if state:
        want = state.upper()
        regions = [r for r in regions if r.split("-", 1)[0] == want]
    if not incomplete and not redo:
        done = published_regions()
        regions = [r for r in regions if r not in done]
    return regions[:limit]


def screen(region_key: str, dry_run: bool = False) -> Tuple[bool, str]:
    """
    One county. Returns (ok, note).

    A failure is caught and reported rather than raised: one county's cadastre
    or overlay going down must not end a batch that has forty more to do. The
    county simply stays unscreened, and the next batch picks it up — which is
    the whole point of taking progress from the published data.
    """
    region = region_registry.resolve(region_key)
    if region is None:
        return False, "does not resolve to a county"
    try:
        run_pipeline(
            region_key=region.region_key,
            min_lon=region.bbox[0], min_lat=region.bbox[1],
            max_lon=region.bbox[2], max_lat=region.bbox[3],
            county_name=region.county,
            grid_operator=region.grid_operator,
            dry_run=dry_run,
            # "backfill", not "pjm-screening": ingestion_runs.trigger
            # carries a CHECK constraint allowing only manual, scheduled,
            # backfill and operator, and a value outside it fails the run
            # row before any work happens. backfill is also the honest
            # word — this is a bulk automated load of coverage that was
            # never surveyed. Sweep rows stay identifiable without a
            # bespoke value: evidence_tier is 'screening' and the region
            # is not in PARCEL_PILOTS.
            trigger="backfill",
            # TRUE, despite these counties having no cadastral adapter, and
            # the name misleads. The flag does not mean "run the parcel tier";
            # it gates the whole evidence step:
            #
            #     if qualify_parcels_flag and region_key in PARCEL_PILOTS:
            #         ... parcel tier ...
            #     elif qualify_parcels_flag:
            #         ... national federal-layer metrics ...
            #
            # Passing False to "skip the parcel tier" also skips the national
            # metrics, and the run then publishes bare screening cells with
            # none of the federal evidence the national tier exists to
            # produce. It looks like a success: cells land, the composite
            # scores, nothing errors. The PARCEL_PILOTS membership test is
            # what routes a county with no adapter to the national branch,
            # and it does that correctly on its own.
            qualify_parcels_flag=True,
        )
        return True, "ok"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:160]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Screen a batch of the PJM footprint.")
    parser.add_argument("--limit", type=int, default=10,
                        help="counties to screen this run (default 10)")
    parser.add_argument("--state", default=None,
                        help="restrict to one state code, e.g. OH")
    parser.add_argument("--redo", action="store_true",
                        help="include counties already screened")
    parser.add_argument("--incomplete", action="store_true",
                        help="re-run counties whose live run recorded a "
                             "missing layer in stats.layers (recovery pass "
                             "after a degraded publish), instead of "
                             "unscreened counties")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true",
                        help="show the batch and exit without running it")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    total = len(region_registry.pjm_screening_regions())
    done = len(published_regions() & set(region_registry.pjm_screening_regions()))
    batch = next_batch(args.limit, args.state, args.redo, args.incomplete)

    logger.info("PJM footprint: %d counties at or above the %.0f%% screening "
                "threshold; %d already screened, %d remaining.",
                total, region_registry.PJM_SCREEN_MIN_PCT, done, total - done)
    if args.incomplete:
        degraded = sorted(incomplete_regions())
        logger.info("Recovery pass: %d published region(s) recorded a missing "
                    "layer%s", len(degraded),
                    (": " + ", ".join(degraded)) if degraded else ".")
    if not batch:
        logger.info("Nothing to do.")
        return 0
    logger.info("This batch (%d): %s", len(batch), ", ".join(batch))
    if args.list:
        return 0

    started = time.time()
    ok, failed = [], []
    for i, key in enumerate(batch, 1):
        logger.info("=" * 70)
        logger.info("[%d/%d] %s", i, len(batch), key)
        good, note = screen(key, dry_run=args.dry_run)
        (ok if good else failed).append(key)
        if not good:
            logger.warning("%s did not screen: %s", key, note)

    mins = (time.time() - started) / 60.0
    logger.info("=" * 70)
    logger.info("Batch done in %.1f min: %d screened, %d failed.",
                mins, len(ok), len(failed))
    if failed:
        logger.warning("Failed (they stay unscreened and the next batch will "
                       "retry them): %s", ", ".join(failed))
    # A batch where everything failed is a systemic problem — a bad key, an
    # outage, a broken deploy — not forty independent accidents. Exit non-zero
    # so a scheduled run does not report success while publishing nothing.
    return 1 if ok == [] and failed else 0


if __name__ == "__main__":
    sys.exit(main())
