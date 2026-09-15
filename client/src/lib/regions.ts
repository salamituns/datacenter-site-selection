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
}

/** Home region — always selectable: the demo dataset covers it. */
export const HOME_REGION = "VA-LOUDOUN";

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
    }));
  } catch (err) {
    console.error("Failed to fetch survey regions:", err);
    return [];
  }
}
