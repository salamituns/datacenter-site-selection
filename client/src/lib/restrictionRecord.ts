import { ParcelGateRow } from "@/types/parcel";

/**
 * The moratorium gate's dossier, lifted out of `details` into a shape the
 * modal can render without knowing the worker's serialization.
 *
 * The gate rationale already cites the instrument in prose; this module
 * exists because a verdict that names an ordinance should also show its
 * record — the adopting body, the dates (expiry above all, since this
 * gate's verdict is a function of the calendar), the source that is the
 * jurisdiction's own, and what each governing level's review found.
 */

/** ISO dates arrive as "2026-03-10" (DATE columns); PostgREST can also
 *  return a timestamp. Ten characters is the date either way. */
function asDate(v: unknown): string | null {
  if (typeof v !== "string" || v.length === 0) return null;
  return v.slice(0, 10);
}

function asText(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

export interface RestrictionLevel {
  /** county | place | township — the governing level the row speaks for. */
  kind: string;
  /** The jurisdiction's own name, as the row records it. */
  jurisdiction: string | null;
  /** adopted | pending | none_found | unverified | unreviewed. */
  status: string;
  /** When the level's review happened — null when unreviewed. */
  reviewedAt: string | null;
}

export interface RestrictionRecordView {
  adoptingBody: string | null;
  instrument: string | null;
  adoptedDate: string | null;
  effectiveDate: string | null;
  /** The date the restriction stops binding, when the row records one. */
  expiresDate: string | null;
  /** An instrument is cited but no expiry is recorded — a use-table
   *  amendment does not lapse, and "no expiry" is a finding, not a gap. */
  noExpiry: boolean;
  scope: string | null;
  /** The adopting jurisdiction's own record — never a tracker. */
  sourceUrl: string | null;
  /** When a human read the instrument. */
  reviewedAt: string | null;
  /** The run date the verdict was evaluated against. */
  evaluationDate: string | null;
  levels: RestrictionLevel[];
}

/**
 * Normalizes the moratorium gate's `details`. Returns null when the
 * details carry no restriction content (a bare UNKNOWN row, or any other
 * gate's details) — the dossier then renders nothing rather than an empty
 * frame, the same way a null metric renders "Unverified" and not a zero.
 */
export function restrictionRecord(
  gate: ParcelGateRow
): RestrictionRecordView | null {
  const d = gate.details;
  if (!d || typeof d !== "object") return null;

  const instrument = asText(d.instrument);
  const adoptingBody = asText(d.adopting_body);
  const levelsRaw =
    d.levels && typeof d.levels === "object" && !Array.isArray(d.levels)
      ? (d.levels as Record<string, unknown>)
      : null;
  if (!instrument && !adoptingBody && !levelsRaw) return null;

  const levels: RestrictionLevel[] = levelsRaw
    ? Object.entries(levelsRaw)
        .map(([kind, v]) => {
          const row =
            v && typeof v === "object" && !Array.isArray(v)
              ? (v as Record<string, unknown>)
              : {};
          return {
            kind,
            jurisdiction: asText(row.jurisdiction),
            status: asText(row.status) ?? "unreviewed",
            reviewedAt: asDate(row.reviewed_at),
          };
        })
        // The gate evaluates most-restrictive-first; the dossier lists
        // the levels in governing order, county outward, which is also
        // the order a reader checks them in.
        .sort((a, b) => levelOrder(a.kind) - levelOrder(b.kind))
    : [];

  return {
    adoptingBody,
    instrument,
    adoptedDate: asDate(d.adopted_date),
    effectiveDate: asDate(d.effective_date),
    expiresDate: asDate(d.expires_date),
    noExpiry: Boolean(instrument) && d.expires_date == null,
    scope: asText(d.scope),
    sourceUrl: asText(d.source_url),
    reviewedAt: asDate(d.reviewed_at),
    evaluationDate: asDate(d.evaluation_date),
    levels,
  };
}

function levelOrder(kind: string): number {
  return { county: 0, place: 1, township: 2 }[kind] ?? 3;
}

/** A level's status in reading English — the row's own vocabulary, not
 *  a verdict of our own. */
export const LEVEL_STATUS_TEXT: Record<string, string> = {
  adopted: "adopted restriction on record",
  pending: "restriction pending",
  none_found: "reviewed — none found",
  unverified: "claim untraced to the jurisdiction's own record",
  unreviewed: "not yet reviewed",
};

export function levelStatusText(status: string): string {
  return LEVEL_STATUS_TEXT[status] ?? status;
}

/** The level's name in reading English, keeping the worker's parenthetical
 *  for the unavailable-layer hold, which is itself a finding. */
export function levelName(kind: string): string {
  return { county: "County", place: "Incorporated place", township: "Township" }[kind] ?? kind;
}
