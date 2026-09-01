export interface GridParcel {
  id: string;
  grid_id: string;
  state_code: string;
  county_name: string;
  area_sq_km: number;
  
  // Coordinates (Centroid)
  lon: number;
  lat: number;
  geojson_geom?: {
    type: string;
    coordinates: number[][][];
  };
  
  // 1. Power Grid Proximity (HIFLD)
  power_distance_miles: number;
  substation_distance_miles: number;
  substation_voltage_kv: number;
  substation_name?: string;
  grid_operator: string;
  
  // 2. Water Availability (USGS NWIS)
  groundwater_depth_ft: number;
  surface_water_distance_miles?: number;
  water_availability_index: number;
  
  // 3. Geological & Climate Risk (FEMA NRI & USGS Seismic)
  seismic_hazard_pga: number;
  flood_risk_score: number;
  hurricane_risk_score: number;
  
  // 4. Ambient Temperature (NOAA NCEI)
  cooling_degree_days: number;
  ambient_avg_temp_f: number;
  free_cooling_potential_hours: number;
  
  // Scoring
  power_score: number;
  water_score: number;
  risk_score: number;
  climate_score: number;
  composite_score: number;
  
  // ML Clusters
  cluster_zone_id: number;
  cluster_label: string;
  is_prime_zone: boolean;
  megawatt_capacity_estimate: number;
}

export interface LayerVisibility {
  powerGrid: boolean;
  waterAquifers: boolean;
  seismicHazard: boolean;
  climateCDD: boolean;
  primeClusters: boolean;
  parcelGrid: boolean;
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
  total_mw_capacity: number;
}
