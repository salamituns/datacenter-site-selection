export interface GridParcel {
  id: string;
  grid_id: string;
  state_code: string;
  county_name: string | null;
  area_sq_km: number;

  // Coordinates (Centroid)
  lon: number;
  lat: number;
  geojson_geom?: {
    type: string;
    coordinates: number[][][];
  };

  // Nullable columns mirror the database exactly: null means the source
  // had no value — the UI renders "Unverified", never an invented default.

  // 1. Power Grid Proximity (HIFLD)
  power_distance_miles: number;
  substation_distance_miles: number;
  substation_voltage_kv: number | null;
  substation_name?: string | null;
  grid_operator: string | null;

  // 2. Water Availability (USGS NWIS)
  groundwater_depth_ft: number | null;
  surface_water_distance_miles?: number | null;
  water_availability_index: number | null;

  // 3. Geological & Climate Risk (FEMA NRI & USGS Seismic)
  seismic_hazard_pga: number | null;
  flood_risk_score: number | null;
  hurricane_risk_score: number | null;

  // 4. Ambient Temperature (NOAA NCEI)
  cooling_degree_days: number | null;
  ambient_avg_temp_f: number | null;
  free_cooling_potential_hours: number | null;

  // Scoring
  power_score: number | null;
  water_score: number | null;
  risk_score: number | null;
  climate_score: number | null;
  composite_score: number;

  // ML Clusters
  cluster_zone_id: number | null;
  cluster_label: string | null;
  is_prime_zone: boolean;
  megawatt_capacity_estimate: number | null;
}

export interface LayerVisibility {
  powerGrid: boolean;
  waterAquifers: boolean;
  seismicHazard: boolean;
  climateCDD: boolean;
  primeClusters: boolean;
  parcelGrid: boolean;
  /** Loudoun pilot: cadastral parcels with gate verdicts (Release 1). */
  qualifiedParcels: boolean;
}

// ── Parcel qualification (Release 1) ──────────────────────────────────

export type GateStatus = "PASS" | "CONDITIONAL" | "FAIL" | "UNKNOWN";

/** Cadastral parcel with its latest-run gate verdict, as served by
 *  v_land_parcels_map (geometry simplified ~5 m for map transport). */
export interface LandParcel {
  parcel_key: string;
  pin: string;
  state_code: string;
  county_name: string | null;
  lon: number;
  lat: number;
  gis_acreage: number | null;
  legal_acreage: number | null;
  overall_status: GateStatus | null;
  geojson_geom?: {
    type: string;
    coordinates: number[][][] | number[][][][];
  };
}

export interface ParcelGateRow {
  gate_key: string;
  status: GateStatus;
  affected_area_pct: number | null;
  rationale: string | null;
}

export interface ParcelMetricRow {
  metric_key: string;
  label: string | null;
  value: number | null;
  text_value: string | null;
  unit: string | null;
  evidence_class: string | null;
  source_organization: string | null;
  source_dataset: string | null;
}

export interface ParcelQualification {
  gates: ParcelGateRow[];
  metrics: ParcelMetricRow[];
}

// ── Power diligence (Release 2) ───────────────────────────────────────

/** Dated utility document backing a power-evidence claim
 *  (v_power_documents). A capacity figure is only ever displayed with
 *  the document that supports it. */
export interface PowerDocument {
  doc_key: string;
  title: string;
  publisher: string;
  doc_type: string;
  published_date: string | null;
  url: string;
  summary: string | null;
}

export interface WeightFactors {
  powerWeight: number;    // e.g. 40
  waterWeight: number;    // e.g. 25
  riskWeight: number;     // e.g. 20
  climateWeight: number;  // e.g. 15
}

export interface ClusterSummary {
  cluster_zone_id: number;
  cluster_label: string;
  parcel_count: number;
  avg_composite_score: number;
  total_area_sq_km: number;
}

// ── Map infrastructure features (real HIFLD / USGS NWIS, persisted per region) ──

export interface TransmissionLineFeature {
  id: string;
  feature_id: string;
  state_code: string;
  owner: string | null;
  voltage_kv: number;
  volt_class: string | null;
  line_name: string | null;
  /** GeoJSON LineString: coordinates[0] is an array of [lon, lat] pairs */
  geojson_geom?: {
    type: string;
    coordinates: number[][];
  };
}

export interface SubstationFeature {
  id: string;
  feature_id: string;
  state_code: string;
  substation_name: string;
  voltage_kv: number;
  lon: number;
  lat: number;
}

export interface ObservationWellFeature {
  id: string;
  site_no: string;
  state_code: string;
  water_depth_ft: number | null;
  lon: number;
  lat: number;
}

export interface MapFeatures {
  lines: TransmissionLineFeature[];
  substations: SubstationFeature[];
  wells: ObservationWellFeature[];
}
