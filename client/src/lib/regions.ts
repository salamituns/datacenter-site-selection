/**
 * Survey regions — read from the database, not restated here.
 *
 * This file used to carry a hardcoded list of six regions under a comment
 * saying it matched the worker's presets. It did, until three Ohio counties
 * were published and it silently did not: the data was in the database and
 * the selector simply never offered it. A second copy of a fact, kept by
 * hand, drifting from the first.
 *
 * `v_survey_regions` is now the single answer to "which regions exist". A
 * region appears there as soon as it has published screening cells, which is
 * the same moment it is worth offering, so a new county needs no edit here.
 * Whether it is offered by default is a different question: only surveyed
 * counties (active parcels) lead the selector, and the screening-only ones
 * a PJM sweep publishes sit behind its search — filterRegions owns that
 * rule so both surfaces share it.
 *
 * Regions are keyed by county slug (STATE-COUNTY): the database scopes
 * publication by region_key, so one state can host more than one diligenced
 * county (OH-FRANKLIN, OH-LICKING) without either overwriting the other.
 */
import { supabase } from "./supabase";

export interface Region {
  /** region_key stored in the DB and used for server-side filtering */
  code: string;
  /** full label shown in the desktop selector */
  label: string;
  /** compact label shown in the mobile region pill */
  short: string;
  /** regional grid operator tag */
  operator: string;
  /** published screening cells — 0 means nothing to show yet */
  cells: number;
  /** active cadastral parcels; 0 for a screening-only region like Morrow */
  parcels: number;
  /**
   * True when the region has a diligenced parcel survey (parcels > 0). A
   * screening-only region is worth offering, but it is a measurement, not
   * a survey: after the PJM sweep there will be hundreds of them and the
   * selector must not bury the surveyed counties in that list.
   */
  surveyed: boolean;
}

/** Home region — always selectable: the demo dataset covers it. */
export const HOME_REGION = "VA-LOUDOUN";

/**
 * A region is surveyed when it has active cadastral parcels. The home
 * region always is (it carries the demo dataset fallback), so the selector
 * never strands the default view.
 */
export function isSurveyed(region: Region): boolean {
  return region.parcels > 0 || region.code === HOME_REGION;
}

/**
 * What the selector offers. With no query: the surveyed counties only —
 * the default view of the map is diligence, not measurement. With a
 * query: every region that matches, surveyed ones first, so the
 * screening-only counties a sweep publishes stay reachable without
 * crowding the default list.
 */
export function filterRegions(regions: Region[], query: string): Region[] {
  const q = query.trim().toLowerCase();
  const bySurvey = [...regions].sort(
    (a, b) =>
      Number(isSurveyed(b)) - Number(isSurveyed(a)) ||
      a.code.localeCompare(b.code),
  );
  if (!q) {
    return bySurvey.filter(isSurveyed);
  }
  return bySurvey.filter(
    (r) =>
      r.code.toLowerCase().includes(q) ||
      r.label.toLowerCase().includes(q) ||
      r.short.toLowerCase().includes(q),
  );
}

/**
 * Operator tags short enough for a selector. Anything unrecognised falls
 * through to its own name rather than to a guess — a region served by an
 * operator nobody has tagged should read oddly, not read wrongly.
 */
export function operatorTag(operator: string | null): string {
  if (!operator) return "—";
  if (operator.startsWith("PJM")) return "PJM";
  if (operator.startsWith("Bonneville")) return "BPA";
  return operator;
}

/**
 * Four letters of the county name. Systematic rather than hand-picked: the
 * old short codes were "VA", "TX", "OH", "LICK", "PW", "OR", which stopped
 * being unambiguous the moment a second Ohio county arrived — and there are
 * now five.
 */
export function shortTag(county: string): string {
  return county.replace(/[^A-Za-z]/g, "").slice(0, 4).toUpperCase();
}

export async function fetchRegions(): Promise<Region[]> {
  if (!supabase) return [];
  try {
    const { data, error } = await supabase
      .from("v_survey_regions")
      .select("region_key, county_name, state_code, grid_operator, screening_cells, active_parcels")
      .order("region_key");
    if (error || !data) {
      console.error("Failed to fetch survey regions:", error);
      return [];
    }
    return data.map((r) => ({
      code: r.region_key as string,
      label: `${r.county_name} ${r.state_code} · ${operatorTag(r.grid_operator as string)}`,
      short: shortTag(r.county_name as string),
      operator: operatorTag(r.grid_operator as string),
      cells: (r.screening_cells as number) ?? 0,
      parcels: (r.active_parcels as number) ?? 0,
      surveyed: ((r.active_parcels as number) ?? 0) > 0,
    }));
  } catch (err) {
    console.error("Failed to fetch survey regions:", err);
    return [];
  }
}
