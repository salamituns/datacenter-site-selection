import { describe, expect, it } from "vitest";
import { computePrimeZones } from "@/lib/primeZones";
import { GridParcel } from "@/types/parcel";

function parcel(id: string, lon: number, lat: number, score: number): GridParcel {
  return {
    id,
    grid_id: id,
    state_code: "VA",
    county_name: "Loudoun",
    // Loudoun has run parcel qualification, so these cells are parcel tier
    // and their clusters are genuinely "Prime". Tests that need the
    // screening case say so explicitly.
    evidence_tier: "parcel",
    area_sq_km: 10,
    lon,
    lat,
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
    composite_score: score,
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

describe("computePrimeZones", () => {
  it("excludes parcels below the threshold from every zone", () => {
    // Three adjacent cells above threshold + one adjacent below.
    const parcels = [
      parcel("a", -77.50, 39.05, 88),
      parcel("b", -77.505, 39.05, 86),
      parcel("c", -77.51, 39.05, 84),
      parcel("low", -77.515, 39.05, 60),
    ];
    const { zones, parcelZone } = computePrimeZones(parcels, 70);
    expect(zones).toHaveLength(1);
    expect(parcelZone.has("low")).toBe(false);
    expect(parcelZone.has("a")).toBe(true);
  });

  it("clusters nearby cells into one ranked zone with no capacity claim", () => {
    const parcels = [
      parcel("a", -77.50, 39.05, 88),
      parcel("b", -77.505, 39.05, 86),
      parcel("c", -77.51, 39.05, 84),
    ];
    const { zones, parcelZone } = computePrimeZones(parcels, 70);
    expect(zones).toHaveLength(1);
    const z = zones[0];
    expect(z.label).toMatch(/^Prime Zone A \(30 km² Hyper-Cluster\)$/);
    expect(z.parcelCount).toBe(3);
    // Release 2: zones never carry an MW figure — capacity requires a
    // dated source per parcel, which screening never has.
    expect("mwCapacity" in z).toBe(false);
    expect(z.avgScore).toBeCloseTo(86, 0);
    expect(parcelZone.get("a")!.id).toBe(0);
  });

  it("rates two separated groups as distinct zones ranked by mean score", () => {
    const west = [parcel("w1", -77.90, 39.10, 90), parcel("w2", -77.905, 39.10, 89)];
    const east = [parcel("e1", -77.30, 39.10, 80), parcel("e2", -77.305, 39.10, 79)];
    const { zones } = computePrimeZones([...west, ...east], 70);
    expect(zones).toHaveLength(2);
    // Higher mean score earns the A letter.
    expect(zones[0].label).toContain("Prime Zone A");
    expect(zones[1].label).toContain("Prime Zone B");
    expect(zones[0].avgScore).toBeGreaterThan(zones[1].avgScore);
  });

  it("returns no zones when too few parcels clear the threshold", () => {
    const parcels = [parcel("a", -77.50, 39.05, 88)];
    const { zones, parcelZone } = computePrimeZones(parcels, 70);
    expect(zones).toHaveLength(0);
    expect(parcelZone.size).toBe(0);
  });

  it("builds a hull over clustered cell footprints when geometry exists", () => {
    const parcels = [
      parcel("a", -77.50, 39.05, 88),
      parcel("b", -77.505, 39.05, 86),
      parcel("c", -77.51, 39.05, 84),
    ];
    // A wide box footprint so the convex hull has real area.
    const withGeom = parcels.map((p) => ({
      ...p,
      geojson_geom: {
        type: "Polygon",
        coordinates: [
          [
            [p.lon - 0.01, p.lat - 0.01],
            [p.lon - 0.01, p.lat + 0.01],
            [p.lon + 0.01, p.lat + 0.01],
            [p.lon + 0.01, p.lat - 0.01],
            [p.lon - 0.01, p.lat - 0.01],
          ],
        ],
      } as GridParcel["geojson_geom"],
    }));
    const { zones } = computePrimeZones(withGeom, 70);
    expect(zones[0].hull).not.toBeNull();
    expect(zones[0].hull!.coordinates.length).toBeGreaterThan(0);
  });
});

describe("zone evidence tier", () => {
  function tiered(id: string, lon: number, lat: number, score: number, tier: "parcel" | "screening") {
    return { ...parcel(id, lon, lat, score), evidence_tier: tier };
  }

  it("names a fully diligenced cluster a Prime Zone", () => {
    const { zones } = computePrimeZones(
      [
        tiered("a", -77.5, 39.05, 88, "parcel"),
        tiered("b", -77.505, 39.05, 86, "parcel"),
      ],
      70
    );
    expect(zones[0].tier).toBe("parcel");
    expect(zones[0].label).toMatch(/^Prime Zone A /);
  });

  it("names a cluster with no parcel survey a Screening Zone", () => {
    // Morrow County: 210 contiguous cells averaging 68.44 is a real
    // finding, but "Prime" is a readiness claim its evidence cannot make.
    const { zones } = computePrimeZones(
      [
        tiered("a", -119.8, 45.8, 78, "screening"),
        tiered("b", -119.805, 45.8, 76, "screening"),
      ],
      70
    );
    expect(zones[0].tier).toBe("screening");
    expect(zones[0].label).toMatch(/^Screening Zone A /);
  });

  it("demotes a mixed cluster to its weakest member", () => {
    const { zones } = computePrimeZones(
      [
        tiered("a", -77.5, 39.05, 88, "parcel"),
        tiered("b", -77.505, 39.05, 86, "screening"),
      ],
      70
    );
    expect(zones[0].tier).toBe("screening");
  });

  it("treats a cluster with no tier recorded as screening", () => {
    // Mock and demo rows predate the column; an unlabelled cluster must not
    // inherit a readiness claim by default.
    const untiered = (id: string, lon: number, score: number) => {
      const p = { ...parcel(id, lon, 39.05, score) };
      delete (p as Partial<GridParcel>).evidence_tier;
      return p;
    };
    const { zones } = computePrimeZones(
      [untiered("a", -77.5, 88), untiered("b", -77.505, 86)],
      70
    );
    expect(zones[0].label).toMatch(/^Screening Zone A /);
  });
});
