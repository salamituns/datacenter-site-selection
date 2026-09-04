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
 * Maps one `v_grid_parcels` / `grid_parcels` row to a GridParcel. Pure —
 * exported for tests. Nullable columns pass their nulls through (the UI
 * renders "Unverified"); a row without a drawable centroid maps to null
 * rather than being pinned to an invented coordinate.
 */
export function mapGridParcelRow(item: any): GridParcel | null {
  const num = (v: unknown): number | null =>
    v == null || v === "" || isNaN(Number(v)) ? null : Number(v);
  const str = (v: unknown): string | null => {
    const s = typeof v === "string" ? v.trim() : v;
    return s == null || s === "" ? null : String(s);
  };

  let lon = typeof item.lon === "number" ? item.lon : null;
  let lat = typeof item.lat === "number" ? item.lat : null;
  if (lon === null || lat === null) {
    if (typeof item.centroid === "string") {
      const decoded = decodeEWKBPoint(item.centroid);
      if (decoded) {
        lon = decoded[0];
        lat = decoded[1];
      }
    }
  }
  if (lon === null || lat === null) return null;

  let geojson_geom = item.geojson_geom;
  if (typeof geojson_geom === "string") {
    try {
      geojson_geom = JSON.parse(geojson_geom);
    } catch {}
  }

  return {
    id: item.id || item.grid_id,
    grid_id: item.grid_id,
    state_code: str(item.state_code) ?? "—",
    county_name: str(item.county_name),
    area_sq_km: Number(item.area_sq_km || 0),
    lon,
    lat,
    geojson_geom,
    power_distance_miles: num(item.power_distance_miles) ?? 0,
    substation_distance_miles: num(item.substation_distance_miles) ?? 0,
    substation_voltage_kv: num(item.substation_voltage_kv),
    substation_name: str(item.substation_name),
    grid_operator: str(item.grid_operator),
    groundwater_depth_ft: num(item.groundwater_depth_ft),
    surface_water_distance_miles: num(item.surface_water_distance_miles),
    water_availability_index: num(item.water_availability_index),
    seismic_hazard_pga: num(item.seismic_hazard_pga),
    flood_risk_score: num(item.flood_risk_score),
    hurricane_risk_score: num(item.hurricane_risk_score),
    cooling_degree_days: num(item.cooling_degree_days),
    ambient_avg_temp_f: num(item.ambient_avg_temp_f),
    free_cooling_potential_hours: num(item.free_cooling_potential_hours),
    power_score: num(item.power_score),
    water_score: num(item.water_score),
    risk_score: num(item.risk_score),
    climate_score: num(item.climate_score),
    composite_score: num(item.composite_score) ?? 0,
    cluster_zone_id: num(item.cluster_zone_id),
    cluster_label: str(item.cluster_label),
    is_prime_zone: Boolean(item.is_prime_zone),
    megawatt_capacity_estimate: num(item.megawatt_capacity_estimate),
  };
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

    // Map records to GridParcel; rows without a drawable centroid are
    // skipped (logged) rather than pinned to an invented coordinate.
    const mapped: GridParcel[] = [];
    for (const item of data) {
      const row = mapGridParcelRow(item);
      if (!row) {
        console.warn("Skipping parcel with no drawable centroid:", item.grid_id);
        continue;
      }
      mapped.push(row);
    }
    return mapped;
  } catch (err) {
    console.error("Failed to fetch parcels from Supabase:", err);
    return [];
  }
}
