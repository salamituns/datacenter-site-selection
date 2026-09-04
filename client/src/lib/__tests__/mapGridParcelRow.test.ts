import { describe, expect, it } from "vitest";
import { mapGridParcelRow } from "@/lib/supabase";

/**
 * Release 0 rule: a missing source value stays null — the client never
 * substitutes a plausible default. These tests pin that behavior.
 */
describe("mapGridParcelRow", () => {
  const baseRow = {
    id: "00000000-0000-0000-0000-000000000001",
    grid_id: "VA-LOUD-001",
    state_code: "VA",
    county_name: "Loudoun",
    area_sq_km: 10.2,
    lon: -77.5,
    lat: 39.05,
    power_distance_miles: 0.86,
    substation_distance_miles: 1.4,
    substation_voltage_kv: 500,
    grid_operator: "PJM",
    groundwater_depth_ft: 29.8,
    water_availability_index: 85.1,
    seismic_hazard_pga: 0.069,
    flood_risk_score: 12,
    hurricane_risk_score: 8,
    cooling_degree_days: 1164,
    ambient_avg_temp_f: 55.3,
    free_cooling_potential_hours: 4103,
    power_score: 91,
    water_score: 84,
    risk_score: 88,
    climate_score: 79,
    composite_score: 86.4,
    cluster_zone_id: 0,
    cluster_label: "Prime Zone A",
    is_prime_zone: true,
    megawatt_capacity_estimate: 1500,
  };

  it("passes measured values through unchanged", () => {
    const p = mapGridParcelRow(baseRow)!;
    expect(p.grid_id).toBe("VA-LOUD-001");
    expect(p.groundwater_depth_ft).toBeCloseTo(29.8);
    expect(p.seismic_hazard_pga).toBeCloseTo(0.069);
    expect(p.composite_score).toBeCloseTo(86.4);
  });

  it("keeps null source values null instead of inventing defaults", () => {
    const row = {
      ...baseRow,
      groundwater_depth_ft: null,
      substation_voltage_kv: null,
      grid_operator: null,
      seismic_hazard_pga: null,
      flood_risk_score: null,
      cooling_degree_days: null,
      ambient_avg_temp_f: null,
      free_cooling_potential_hours: null,
      power_score: null,
      water_score: null,
      risk_score: null,
      climate_score: null,
      megawatt_capacity_estimate: null,
      cluster_zone_id: null,
      cluster_label: null,
      county_name: null,
    };
    const p = mapGridParcelRow(row)!;
    expect(p.groundwater_depth_ft).toBeNull(); // not 45
    expect(p.substation_voltage_kv).toBeNull(); // not 230
    expect(p.grid_operator).toBeNull(); // not "PJM"
    expect(p.seismic_hazard_pga).toBeNull(); // not 0.04
    expect(p.cooling_degree_days).toBeNull(); // not 1000
    expect(p.free_cooling_potential_hours).toBeNull(); // not 4500
    expect(p.power_score).toBeNull(); // not 80
    expect(p.megawatt_capacity_estimate).toBeNull(); // not 100
    expect(p.county_name).toBeNull(); // not "Loudoun"
    expect(p.cluster_label).toBeNull();
    expect(p.cluster_zone_id).toBeNull();
  });

  it("treats empty strings as missing, not as a value", () => {
    const p = mapGridParcelRow({ ...baseRow, grid_operator: "  ", substation_name: "" })!;
    expect(p.grid_operator).toBeNull();
    expect(p.substation_name).toBeNull();
  });

  it("returns null for a row with no drawable centroid", () => {
    const row: Record<string, unknown> = { ...baseRow };
    delete row.lon;
    delete row.lat;
    delete row.centroid;
    expect(mapGridParcelRow(row)).toBeNull();
  });

  it("never substitutes the old hard-coded centroid", () => {
    const p = mapGridParcelRow({ ...baseRow, lon: null, lat: null, centroid: null });
    // Old behavior pinned undrawable parcels to (-77.534, 39.043); the
    // mapper must refuse instead.
    expect(p).toBeNull();
  });
});
