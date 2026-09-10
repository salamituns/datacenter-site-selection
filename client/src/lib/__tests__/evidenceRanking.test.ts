import { describe, expect, it } from "vitest";
import {
  compareByEvidenceThenScore,
  coverageFactor,
  tierOf,
} from "@/lib/evidenceRanking";
import { EvidenceTier, GridParcel } from "@/types/parcel";

function parcel(
  grid_id: string,
  composite_score: number,
  tier?: EvidenceTier,
  evidence_coverage?: number
): GridParcel {
  return {
    id: grid_id,
    grid_id,
    state_code: "VA",
    county_name: "Loudoun",
    area_sq_km: 10,
    lon: -77.5,
    lat: 39.05,
    power_distance_miles: 0.5,
    substation_distance_miles: 1,
    substation_voltage_kv: 500,
    substation_name: null,
    grid_operator: "PJM",
    groundwater_depth_ft: 30,
    surface_water_distance_miles: 2,
    water_availability_index: 85,
    seismic_hazard_pga: 0.07,
    flood_risk_score: 12,
    hurricane_risk_score: 8,
    cooling_degree_days: 1160,
    ambient_avg_temp_f: 55,
    free_cooling_potential_hours: 4100,
    power_score: 90,
    water_score: 84,
    risk_score: 88,
    climate_score: 79,
    composite_score,
    evidence_tier: tier,
    evidence_coverage,
    cluster_zone_id: null,
    cluster_label: null,
    is_prime_zone: false,
    megawatt_capacity_estimate: null,
    ixp_nearest_facility: null,
    ixp_nearest_distance_miles: null,
    ixp_latency_floor_ms: null,
    ixp_networks_at_nearest: null,
    ixp_facilities_within_25mi: null,
    ixp_networks_within_25mi: null,
    ixp_best_networks_within_25mi: null,
  };
}

describe("tierOf", () => {
  it("reads a missing tier as screening, the claim that assumes least", () => {
    expect(tierOf(parcel("a", 70))).toBe("screening");
    expect(tierOf(parcel("b", 70, "parcel"))).toBe("parcel");
  });
});

describe("coverageFactor", () => {
  it("applies the decided-gate share inside the parcel tier", () => {
    // Texas: 4 of 9 gates undecidable, so it carries two thirds of its score.
    expect(coverageFactor(parcel("tx", 64.8, "parcel", 0.664))).toBe(0.664);
  });

  it("does not apply coverage to a screening-tier cell", () => {
    // The regression this module exists to prevent. Morrow County has no
    // parcel gates, so its coverage is 0 — multiplying by it annihilated
    // 330 observed screening scores into a single 0.00.
    expect(coverageFactor(parcel("or", 62.6, "screening", 0))).toBe(1);
  });

  it("defaults to 1 when coverage is absent or not finite", () => {
    expect(coverageFactor(parcel("a", 70, "parcel"))).toBe(1);
    expect(coverageFactor(parcel("b", 70, "parcel", NaN))).toBe(1);
  });
});

describe("compareByEvidenceThenScore", () => {
  it("ranks any parcel-tier cell above any screening-tier cell", () => {
    // Oregon out-scores Texas on screening evidence and still sorts below
    // it: the tier decides the order, not the arithmetic.
    const or = parcel("or", 78.2, "screening", 0);
    const tx = parcel("tx", 51.1, "parcel", 0.664);
    expect([or, tx].sort(compareByEvidenceThenScore).map((p) => p.grid_id)).toEqual([
      "tx",
      "or",
    ]);
  });

  it("ranks by score within a tier", () => {
    const va = parcel("va", 79.5, "parcel", 0.994);
    const oh = parcel("oh", 62.5, "parcel", 0.772);
    const tx = parcel("tx", 51.1, "parcel", 0.664);
    expect([tx, va, oh].sort(compareByEvidenceThenScore).map((p) => p.grid_id)).toEqual([
      "va",
      "oh",
      "tx",
    ]);
  });

  it("keeps a screening-tier region rankable against itself", () => {
    // The second half of the annihilator bug: every Oregon cell collapsed to
    // one value, so no cell could be told from another.
    const cells = [
      parcel("or-low", 44.0, "screening", 0),
      parcel("or-high", 78.2, "screening", 0),
      parcel("or-mid", 62.6, "screening", 0),
    ];
    expect(cells.sort(compareByEvidenceThenScore).map((p) => p.grid_id)).toEqual([
      "or-high",
      "or-mid",
      "or-low",
    ]);
  });

  it("breaks exact ties on grid_id so the order is stable across renders", () => {
    const a = parcel("aaa", 70, "parcel", 1);
    const b = parcel("bbb", 70, "parcel", 1);
    expect([b, a].sort(compareByEvidenceThenScore).map((p) => p.grid_id)).toEqual([
      "aaa",
      "bbb",
    ]);
    expect([a, b].sort(compareByEvidenceThenScore).map((p) => p.grid_id)).toEqual([
      "aaa",
      "bbb",
    ]);
  });
});

describe("disclosure figures", () => {
  // The dossier shows risked and measured together; their ratio must be
  // exactly the coverage factor, or the disclosure reads as a bug.
  it("keeps risked = measured x coverage inside the parcel tier", () => {
    const p = parcel("oh", 0, "parcel", 0.772);
    const measured = 81.0;
    const risked = measured * coverageFactor(p);
    expect(Number(risked.toFixed(1))).toBe(62.5);
  });

  it("leaves measured and risked identical outside the parcel tier", () => {
    const p = parcel("or", 0, "screening", 0);
    const measured = 78.1;
    expect(measured * coverageFactor(p)).toBe(78.1);
  });
});
