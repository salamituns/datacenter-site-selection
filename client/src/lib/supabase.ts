import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { GridParcel, MapFeatures } from "@/types/parcel";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// Created lazily from environment variables only — no keys in source.
export const supabase: SupabaseClient | null =
  supabaseUrl && supabaseAnonKey
    ? createClient(supabaseUrl, supabaseAnonKey)
    : null;

/**
 * Decodes PostGIS EWKB Point hex string (SRID 4326) into [lon, lat]
 */
function decodeEWKBPoint(hex: string): [number, number] | null {
  try {
    if (!hex || typeof hex !== "string" || hex.length < 42) return null;
    // Standard EWKB point: 01 (1B) + type (4B) + SRID (4B) + X (8B) + Y (8B)
    const buffer = new ArrayBuffer(hex.length / 2);
    const view = new DataView(buffer);
    for (let i = 0; i < hex.length; i += 2) {
      view.setUint8(i / 2, parseInt(hex.substr(i, 2), 16));
    }
    const isLittleEndian = view.getUint8(0) === 1;
    // Offset for coordinates: with SRID flag, coordinates start at byte 9 (offset 9)
    const lon = view.getFloat64(9, isLittleEndian);
    const lat = view.getFloat64(17, isLittleEndian);
    if (!isNaN(lon) && !isNaN(lat) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
      return [lon, lat];
    }
  } catch (e) {
    // Ignore decode error
  }
  return null;
}

/**
 * Counts parcels per region (state_code) so the selector can disable
 * regions that have not been surveyed yet. Cheap HEAD-count queries.
 */
export async function fetchRegionCounts(codes: string[]): Promise<Record<string, number>> {
  if (!supabase) return {};
  try {
    const results = await Promise.all(
      codes.map(async (code) => {
        const { count, error } = await supabase
          .from("grid_parcels")
          .select("grid_id", { count: "exact", head: true })
          .eq("state_code", code);
        return [code, error ? 0 : (count ?? 0)] as const;
      })
    );
    return Object.fromEntries(results);
  } catch (err) {
    console.error("Failed to fetch region counts:", err);
    return {};
  }
}

/**
 * Fetches the persisted map infrastructure features (HIFLD transmission
 * lines + substations, USGS observation wells) for a survey region. Returns
 * empty lists when unavailable — the map simply draws no markers.
 */
export async function fetchMapFeatures(stateCode?: string): Promise<MapFeatures> {
  const empty: MapFeatures = { lines: [], substations: [], wells: [] };
  if (!supabase) return empty;
  try {
    const scope = (q: any) => (stateCode ? q.eq("state_code", stateCode) : q);
    const [linesRes, subsRes, wellsRes] = await Promise.all([
      scope(supabase.from("v_transmission_lines").select("*").limit(500)),
      scope(supabase.from("v_substations").select("*").limit(500)),
      scope(supabase.from("v_observation_wells").select("*").limit(500)),
    ]);

    const lines = (linesRes.data || []).map((item: any) => ({
      id: item.id,
      feature_id: item.feature_id,
      state_code: item.state_code,
      owner: item.owner || null,
      voltage_kv: Number(item.voltage_kv || 0),
      volt_class: item.volt_class || null,
      line_name: item.line_name || null,
      geojson_geom:
        typeof item.geojson_geom === "string" ? JSON.parse(item.geojson_geom) : item.geojson_geom,
    }));

    const substations = (subsRes.data || []).map((item: any) => ({
      id: item.id,
      feature_id: item.feature_id,
      state_code: item.state_code,
      substation_name: item.substation_name || "Substation",
      voltage_kv: Number(item.voltage_kv || 0),
      lon: Number(item.lon),
      lat: Number(item.lat),
    }));

    const wells = (wellsRes.data || []).map((item: any) => ({
      id: item.id,
      site_no: item.site_no,
      state_code: item.state_code,
      water_depth_ft: item.water_depth_ft == null ? null : Number(item.water_depth_ft),
      lon: Number(item.lon),
      lat: Number(item.lat),
    }));

    return { lines, substations, wells };
  } catch (err) {
    console.error("Failed to fetch map features:", err);
    return empty;
  }
}

/**
 * Fetches ranked parcels directly from Supabase PostGIS `v_grid_parcels` view or table.
 * Optionally scoped to a single region (state_code) for server-side filtering.
 */
export async function fetchGridParcels(
  limit: number = 500,
  stateCode?: string
): Promise<GridParcel[]> {
  if (!supabase) {
    return []; // Credentials not configured — caller falls back to demo data.
  }
  try {
    // 1. Try querying the helper view `v_grid_parcels` which has precomputed ST_X / ST_Y / ST_AsGeoJSON
    let query = supabase
      .from("v_grid_parcels")
      .select("*")
      .order("composite_score", { ascending: false })
      .limit(limit);
    if (stateCode) query = query.eq("state_code", stateCode);
    let { data, error } = await query;

    // 2. If view query fails or returns empty, fallback to `grid_parcels` table
    if (error || !data || data.length === 0) {
      let fallbackQuery = supabase
        .from("grid_parcels")
        .select("*")
        .order("composite_score", { ascending: false })
        .limit(limit);
      if (stateCode) fallbackQuery = fallbackQuery.eq("state_code", stateCode);
      const fallbackRes = await fallbackQuery;
      data = fallbackRes.data;
      error = fallbackRes.error;
    }

    if (error) {
      console.error("Supabase query error:", error);
      return [];
    }

    if (!data || data.length === 0) {
      return [];
    }

    // Map records to GridParcel interface
    return data.map((item: any) => {
      let lon = typeof item.lon === "number" ? item.lon : null;
      let lat = typeof item.lat === "number" ? item.lat : null;

      // If lon/lat not directly on item, try parsing centroid
      if (lon === null || lat === null) {
        if (typeof item.centroid === "string") {
          const decoded = decodeEWKBPoint(item.centroid);
          if (decoded) {
            lon = decoded[0];
            lat = decoded[1];
          }
        }
      }

      // Default fallback if still null
      if (lon === null) lon = -77.534;
      if (lat === null) lat = 39.043;

      let geojson_geom = item.geojson_geom;
      if (typeof geojson_geom === "string") {
        try {
          geojson_geom = JSON.parse(geojson_geom);
        } catch {}
      }

      return {
        id: item.id || item.grid_id,
        grid_id: item.grid_id,
        state_code: item.state_code || "VA",
        county_name: item.county_name || "Loudoun",
        area_sq_km: Number(item.area_sq_km || 10.0),
        lon,
        lat,
        geojson_geom,
        power_distance_miles: Number(item.power_distance_miles || 0),
        substation_distance_miles: Number(item.substation_distance_miles || 0),
        substation_voltage_kv: Number(item.substation_voltage_kv || 230),
        substation_name: item.substation_name || "Substation",
        grid_operator: item.grid_operator || "PJM",
        groundwater_depth_ft: Number(item.groundwater_depth_ft || 45),
        surface_water_distance_miles: Number(item.surface_water_distance_miles || 2),
        water_availability_index: Number(item.water_availability_index || 80),
        seismic_hazard_pga: Number(item.seismic_hazard_pga || 0.04),
        flood_risk_score: Number(item.flood_risk_score || 15),
        hurricane_risk_score: Number(item.hurricane_risk_score || 15),
        cooling_degree_days: Number(item.cooling_degree_days || 1000),
        ambient_avg_temp_f: Number(item.ambient_avg_temp_f || 55),
        free_cooling_potential_hours: Number(item.free_cooling_potential_hours || 4500),
        power_score: Number(item.power_score || 80),
        water_score: Number(item.water_score || 80),
        risk_score: Number(item.risk_score || 80),
        climate_score: Number(item.climate_score || 80),
        composite_score: Number(item.composite_score || 80),
        cluster_zone_id: Number(item.cluster_zone_id ?? -1),
        cluster_label: item.cluster_label || "Secondary",
        is_prime_zone: Boolean(item.is_prime_zone),
        megawatt_capacity_estimate: Number(item.megawatt_capacity_estimate || 100),
      };
    });
  } catch (err) {
    console.error("Failed to fetch parcels from Supabase:", err);
    return [];
  }
}
