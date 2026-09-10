/**
 * Reactive Prime Development Zone clustering (browser-side).
 *
 * Mirrors the worker's ingestion-time semantics (worker/clustering_model.py)
 * so the browser zones match what re-ingestion with the current weights would
 * produce:
 *   - candidates: the *unrisked* screening measurement >= threshold. The
 *     worker clusters before any evidence-coverage risking is applied, so the
 *     caller must pass cells scored the same way (see zoneScoredParcels).
 *     Judging candidacy on the risked figure instead put the browser out of
 *     step with the database — Franklin County held 274 prime cells on an
 *     unrisked max of 81.0 while the browser saw a risked max of 62.9 against
 *     a threshold of 60 — and since these zones override the stored ones, the
 *     region's zones simply vanished.
 *   - DBSCAN over centroids, eps 8.5 km (geodesic), min 2 samples
 *   - clusters ranked by mean score into zones A, B, C …
 *   - boundary = convex hull of the actual cell footprints
 *
 * No MW capacity is computed: a feasible figure requires a dated source
 * (utility study / PJM agreement), which screening never has.
 *
 * Zones carry their evidence tier in their own name. A cluster of cells that
 * has had no parcel survey is a real finding — Morrow County's is 210
 * contiguous cells averaging 68.44 — but it is not a readiness claim, and
 * calling it "Prime" would make it one. This follows the convention every
 * adjacent industry settled on: JORC reports Inferred Resources rather than
 * hiding them, and never calls them Reserves; Virginia's own Business Ready
 * Sites Program lists a Tier 1 site but reserves "business ready" for Tier
 * 4-5, where the wetlands delineation, geotech and boundary survey are done.
 * So the cluster is shown, under the name its evidence supports.
 *
 * Runs in a useMemo off the debounced weights/threshold — DBSCAN over a few
 * hundred points is sub-millisecond, so dragging the sliders morphs the zones
 * live without touching PostGIS.
 */

import clustersDbscan from "@turf/clusters-dbscan";
import convex from "@turf/convex";
import { featureCollection, point } from "@turf/helpers";
import { EvidenceTier, GridParcel } from "@/types/parcel";
import { tierOf } from "@/lib/evidenceRanking";

export interface PrimeZone {
  /** Rank index (0 = highest mean score) — used as cluster_zone_id. */
  id: number;
  /** e.g. "Prime Zone A (120 km² Hyper-Cluster)", or "Screening Zone A (…)"
   *  where the cluster has had no parcel survey. */
  label: string;
  /** The weakest evidence tier among the zone's members. A zone is only
   *  "Prime" where every cell in it has had parcel diligence; otherwise the
   *  cluster is real but uncharacterised, and says so in its own name. */
  tier: EvidenceTier;
  parcelCount: number;
  avgScore: number;
  /** Convex hull over the cluster's cell footprints, [lon, lat] rings. */
  hull: { type: "Polygon"; coordinates: number[][][] } | null;
}

export interface PrimeZoneResult {
  zones: PrimeZone[];
  /** parcel.id → the zone that parcel belongs to (absent = not prime). */
  parcelZone: Map<string, PrimeZone>;
}

const EPS_KM = 8.5;
const MIN_SAMPLES = 2;
const EARTH_RADIUS_AREA_PER_PARCEL = 10; // km² per 10 km² grid cell

/** Cell footprint vertices for hull-building (falls back to the same
 *  approximate box the map uses when a parcel lacks stored geometry). */
function cellVertices(p: GridParcel): number[][] {
  if (p.geojson_geom?.coordinates?.[0]?.length) {
    return p.geojson_geom.coordinates[0].map((coord) => [coord[0], coord[1]]);
  }
  const halfLat = 0.0142;
  const halfLon = 0.0182;
  return [
    [p.lon - halfLon, p.lat - halfLat],
    [p.lon - halfLon, p.lat + halfLat],
    [p.lon + halfLon, p.lat + halfLat],
    [p.lon + halfLon, p.lat - halfLat],
  ];
}

export function computePrimeZones(
  parcels: GridParcel[],
  threshold: number,
  options?: { epsKm?: number; minSamples?: number }
): PrimeZoneResult {
  const epsKm = options?.epsKm ?? EPS_KM;
  const minSamples = options?.minSamples ?? MIN_SAMPLES;

  const candidates = parcels.filter((p) => p.composite_score >= threshold);
  if (candidates.length < minSamples) {
    return { zones: [], parcelZone: new Map() };
  }

  // DBSCAN over candidate centroids. Turf tags each point with a `cluster`
  // property (noise is null or negative depending on version).
  const fc = featureCollection(
    candidates.map((p) =>
      point([p.lon, p.lat], { pid: p.id, score: p.composite_score })
    )
  );
  const clustered = clustersDbscan(fc, epsKm, {
    units: "kilometers",
    minPoints: minSamples,
  });

  const groups = new Map<number, typeof candidates>();
  clustered.features.forEach((f) => {
    const cid = (f.properties as any)?.cluster;
    if (typeof cid !== "number" || cid < 0) return;
    const pid = (f.properties as any)?.pid as string;
    const parcel = candidates.find((p) => p.id === pid);
    if (!parcel) return;
    if (!groups.has(cid)) groups.set(cid, []);
    groups.get(cid)!.push(parcel);
  });

  // Rank clusters by mean composite score (worker assigns zone letters A…).
  const ranked = Array.from(groups.entries())
    .map(([, members]) => ({ members }))
    .sort(
      (a, b) =>
        b.members.reduce((s, p) => s + p.composite_score, 0) / b.members.length -
        a.members.reduce((s, p) => s + p.composite_score, 0) / a.members.length
    );

  const zones: PrimeZone[] = [];
  const parcelZone = new Map<string, PrimeZone>();

  ranked.forEach((group, rankIdx) => {
    const members = group.members;
    const areaKm2 = members.length * EARTH_RADIUS_AREA_PER_PARCEL;
    // A zone is only "Prime" where every cell in it has had parcel
    // diligence. One screening-tier member is enough to demote the whole
    // cluster: the zone can be no better characterised than its weakest
    // cell, and "Prime" is a readiness claim, not a score band.
    const tier: EvidenceTier = members.every((m) => tierOf(m) === "parcel")
      ? "parcel"
      : "screening";
    const kind = tier === "parcel" ? "Prime Zone" : "Screening Zone";
    const zone: PrimeZone = {
      id: rankIdx,
      tier,
      label: `${kind} ${String.fromCharCode(65 + rankIdx)} (${areaKm2} km² Hyper-Cluster)`,
      parcelCount: members.length,
      avgScore:
        Math.round(
          (members.reduce((s, p) => s + p.composite_score, 0) / members.length) * 100
        ) / 100,
      hull: null,
    };

    // Convex boundary over the cluster's actual cell footprints.
    try {
      const vertices = members.flatMap(cellVertices);
      const hull = convex(
        featureCollection(vertices.map((v) => point(v))) as any
      );
      if (hull) {
        const g = hull.geometry as any;
        if (g?.type === "Polygon") zone.hull = g;
        else if (g?.type === "MultiPolygon" && g.coordinates?.[0]) {
          zone.hull = { type: "Polygon", coordinates: g.coordinates[0] };
        }
      }
    } catch {
      // Hull is decorative — zone is still valid without it.
    }

    zones.push(zone);
    members.forEach((p) => parcelZone.set(p.id, zone));
  });

  return { zones, parcelZone };
}
