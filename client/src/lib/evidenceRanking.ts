/**
 * Lexicographic ranking by evidence tier, then by coverage-weighted score.
 *
 * The engine surveys regions at two depths. Every region gets the screening
 * tier — power, water, risk and climate over 10 km² cells. Only a region with
 * a cadastral adapter gets the parcel tier, where the nine gates are actually
 * decided. Comparing a cell from each as though the numbers meant the same
 * thing is the error this module exists to prevent.
 *
 * The first attempt scaled the composite by evidence coverage alone. That is
 * sound inside the parcel tier — Ohio at 0.772 and Texas at 0.664 carry a real
 * and proportionate penalty — but it degenerates at the boundary: a region with
 * no parcel tier has a coverage of 0, and multiplying by zero is not a penalty,
 * it is an annihilator. Morrow County, OR lost all 330 composites to a single
 * 0.00, which discarded screening evidence that had genuinely been observed
 * (Oregon carries the best climate score of the four regions) and flattened the
 * region's internal ranking so that no cell could be told from another.
 *
 * So the tier does the ordering and the score does the measuring:
 *
 *   1. A parcel-tier cell out-ranks a screening-tier cell whatever the two
 *      scores are. The guarantee is absolute and needs no arithmetic.
 *   2. Within a tier, cells compare on score — coverage-weighted inside the
 *      parcel tier, unscaled inside the screening tier, where there are no
 *      parcel gates for a coverage figure to describe.
 *
 * Absent diligence is not a measurement of zero, and this engine does not
 * write it as one.
 */

import { EvidenceTier, GridParcel } from "@/types/parcel";

/** Deeper survey sorts first. */
const TIER_RANK: Record<EvidenceTier, number> = {
  parcel: 1,
  screening: 0,
};

/** A row with no tier recorded is read as screening — the claim that
 *  assumes least. Mock and demo rows predate the column. */
export function tierOf(p: Pick<GridParcel, "evidence_tier">): EvidenceTier {
  return p.evidence_tier === "parcel" ? "parcel" : "screening";
}

/**
 * The multiplier applied to a screening score before it is compared with
 * another score in the same tier.
 *
 * Inside the parcel tier this is the region's decided-gate share, so a
 * partially diligenced site cannot match a fully diligenced one on score.
 * Inside the screening tier it is 1: coverage there describes parcel gates
 * that do not exist, and the tier already keeps these cells below every
 * parcel-tier site. Applying it twice would be the annihilator again.
 */
export function coverageFactor(
  p: Pick<GridParcel, "evidence_tier" | "evidence_coverage">
): number {
  if (tierOf(p) !== "parcel") return 1;
  const c = p.evidence_coverage;
  return typeof c === "number" && Number.isFinite(c) ? c : 1;
}

/**
 * Comparator for descending rank: evidence tier first, score second.
 *
 * Pass it to `Array.prototype.sort`. Ties on both keys fall back to grid_id
 * so the order is stable across renders regardless of the engine's sort.
 */
export function compareByEvidenceThenScore(a: GridParcel, b: GridParcel): number {
  const tierDelta = TIER_RANK[tierOf(b)] - TIER_RANK[tierOf(a)];
  if (tierDelta !== 0) return tierDelta;

  const scoreDelta = b.composite_score - a.composite_score;
  if (scoreDelta !== 0) return scoreDelta;

  return a.grid_id.localeCompare(b.grid_id);
}
