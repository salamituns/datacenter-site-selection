/**
 * Survey regions — the regions the selector offers, matching the
 * worker pipeline's ingestion targets and `grid_parcels.state_code`.
 */
export interface Region {
  /** state_code stored in the DB and used for server-side filtering */
  code: string;
  /** full label shown in the desktop selector */
  label: string;
  /** compact label shown in the mobile region pill */
  short: string;
  /** regional grid operator tag */
  operator: string;
}

export const REGIONS: Region[] = [
  { code: "VA", label: "N. Virginia · PJM", short: "VA", operator: "PJM" },
  { code: "TX", label: "Texas · ERCOT", short: "TX", operator: "ERCOT" },
  { code: "OH", label: "C. Ohio · PJM", short: "OH", operator: "PJM" },
  { code: "OR", label: "Pacific NW", short: "OR", operator: "BPA" },
];

/** Home region — always selectable: the demo dataset covers it. */
export const HOME_REGION = "VA";
