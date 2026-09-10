/**
 * Survey regions — the regions the selector offers, matching the
 * worker pipeline's region presets and `grid_parcels.region_key`.
 *
 * Regions are keyed by county slug (STATE-COUNTY): the database scopes
 * publication by region_key, so one state can host more than one
 * diligenced county (OH-FRANKLIN, OH-LICKING) without either overwriting
 * the other.
 */
export interface Region {
  /** region_key stored in the DB and used for server-side filtering */
  code: string;
  /** full label shown in the desktop selector */
  label: string;
  /** compact label shown in the mobile region pill */
  short: string;
  /** regional grid operator tag */
  operator: string;
}

export const REGIONS: Region[] = [
  { code: "VA-LOUDOUN", label: "Loudoun · PJM", short: "VA", operator: "PJM" },
  { code: "TX-TAYLOR", label: "Taylor TX · ERCOT", short: "TX", operator: "ERCOT" },
  { code: "OH-FRANKLIN", label: "Franklin OH · PJM", short: "OH", operator: "PJM" },
  { code: "OR-MORROW", label: "Morrow OR · BPA", short: "OR", operator: "BPA" },
];

/** Home region — always selectable: the demo dataset covers it. */
export const HOME_REGION = "VA-LOUDOUN";
