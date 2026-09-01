import React, { useState, useMemo } from "react";
import { GridParcel, LayerVisibility } from "@/types/parcel";
import { Zap, Droplets, ShieldAlert, Sparkles, Navigation, Plus, Minus, Database, Layers } from "lucide-react";

interface MapPlaceholderProps {
  parcels: GridParcel[];
  layers: LayerVisibility;
  selectedParcel: GridParcel | null;
  onSelectParcel: (parcel: GridParcel) => void;
  isLiveSupabase?: boolean;
}

export const MapPlaceholder: React.FC<MapPlaceholderProps> = ({
  parcels,
  layers,
  selectedParcel,
  onSelectParcel,
  isLiveSupabase = true,
}) => {
  const [hoveredParcel, setHoveredParcel] = useState<GridParcel | null>(null);
  const [zoomLevel, setZoomLevel] = useState(1);

  // Compute dynamic bounding box from dataset
  const bbox = useMemo(() => {
    if (parcels.length === 0) {
      return { minLon: -77.85, maxLon: -77.25, minLat: 38.75, maxLat: 39.25 };
    }
    const lons = parcels.map((p) => p.lon);
    const lats = parcels.map((p) => p.lat);
    return {
      minLon: Math.min(...lons) - 0.02,
      maxLon: Math.max(...lons) + 0.02,
      minLat: Math.min(...lats) - 0.02,
      maxLat: Math.max(...lats) + 0.02,
    };
  }, [parcels]);

  // Convert geographic coordinates to SVG viewport (800x600)
  const mapCoordsToSvg = (lon: number, lat: number) => {
    const x = ((lon - bbox.minLon) / (bbox.maxLon - bbox.minLon || 1)) * 740 + 30;
    const y = 570 - ((lat - bbox.minLat) / (bbox.maxLat - bbox.minLat || 1)) * 540;
    return { x, y };
  };

  const getParcelColor = (score: number, isPrime: boolean) => {
    if (isPrime && layers.primeClusters) {
      return "rgba(139, 92, 246, 0.40)"; // Purple for Prime Clusters
    }
    if (score >= 82) return "rgba(16, 185, 129, 0.45)"; // High score (Emerald)
    if (score >= 70) return "rgba(59, 130, 246, 0.35)";  // Good score (Blue)
    if (score >= 60) return "rgba(245, 158, 11, 0.30)"; // Moderate (Amber)
    return "rgba(239, 68, 68, 0.18)";                   // Lower tier (Red)
  };

  const getParcelStroke = (score: number, isPrime: boolean, isSelected: boolean) => {
    if (isSelected) return "#6366f1";
    if (isPrime && layers.primeClusters) return "#a855f7";
    if (score >= 82) return "#10b981";
    return "rgba(75, 85, 99, 0.5)";
  };

  return (
    <div className="relative h-full min-h-[540px] w-full overflow-hidden rounded-xl border border-border bg-[#080d1a] shadow-2xl">
      {/* Map Header Status Overlay */}
      <div className="absolute left-4 top-4 z-10 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 rounded-lg bg-surface/90 backdrop-blur-md px-3 py-1.5 border border-border text-xs text-foreground">
          <div className={`h-2 w-2 rounded-full ${isLiveSupabase ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
          <span className="font-semibold text-foreground">
            {isLiveSupabase ? "Supabase PostGIS Live" : "Local GeoJSON Cache"}
          </span>
          <span className="text-gray-400 font-mono text-[10px]">
            {parcels.length} Parcels (10 km²)
          </span>
        </div>

        {layers.primeClusters && (
          <div className="flex items-center gap-1.5 rounded-lg bg-purple-950/85 backdrop-blur-md px-3 py-1.5 border border-purple-500/40 text-xs text-purple-200">
            <Sparkles className="h-3.5 w-3.5 text-purple-400" />
            <span className="font-semibold">DBSCAN Prime Zones Active</span>
          </div>
        )}
      </div>

      {/* Map Floating Controls */}
      <div className="absolute right-4 top-4 z-10 flex flex-col gap-1.5">
        <button
          onClick={() => setZoomLevel((z) => Math.min(z + 0.2, 2.0))}
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface/90 border border-border text-foreground hover:text-foreground hover:bg-surface-raised transition-colors"
          title="Zoom In"
        >
          <Plus className="h-4 w-4" />
        </button>
        <button
          onClick={() => setZoomLevel((z) => Math.max(z - 0.2, 0.8))}
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface/90 border border-border text-foreground hover:text-foreground hover:bg-surface-raised transition-colors"
          title="Zoom Out"
        >
          <Minus className="h-4 w-4" />
        </button>
        <button
          onClick={() => setZoomLevel(1)}
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface/90 border border-border text-foreground hover:text-foreground hover:bg-surface-raised transition-colors"
          title="Reset View"
        >
          <Navigation className="h-4 w-4" />
        </button>
      </div>

      {/* Vector Geospatial Canvas */}
      <svg
        viewBox="0 0 800 600"
        className="h-full w-full select-none"
        style={{
          background: "radial-gradient(circle at center, #0e1628 0%, #050811 100%)",
          transform: `scale(${zoomLevel})`,
          transition: "transform 0.2s ease-out",
        }}
      >
        <defs>
          <pattern id="spatial-grid-pattern" width="30" height="30" patternUnits="userSpaceOnUse">
            <path d="M 30 0 L 0 0 0 30" fill="none" stroke="rgba(255, 255, 255, 0.03)" strokeWidth="1" />
          </pattern>

          <filter id="prime-zone-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>

          <filter id="power-corridor-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        <rect width="800" height="600" fill="url(#spatial-grid-pattern)" />

        {/* 1. CLIMATE HEATMAP LAYER (CDD) */}
        {layers.climateCDD && (
          <g opacity="0.22">
            <circle cx="250" cy="180" r="160" fill="rgba(59, 130, 246, 0.3)" filter="url(#prime-zone-glow)" />
            <circle cx="580" cy="240" r="200" fill="rgba(99, 102, 241, 0.25)" filter="url(#prime-zone-glow)" />
            <circle cx="420" cy="460" r="180" fill="rgba(245, 158, 11, 0.2)" filter="url(#prime-zone-glow)" />
          </g>
        )}

        {/* 2. POWER GRID TRANSMISSION CORRIDORS (HIFLD) */}
        {layers.powerGrid && (
          <g className="transition-opacity duration-300">
            {/* 500kV Backbone Corridor 1 */}
            <path
              d="M 60 120 Q 380 220 740 160"
              fill="none"
              stroke="#eab308"
              strokeWidth="3.5"
              strokeDasharray="8,4"
              filter="url(#power-corridor-glow)"
            />
            {/* 500kV Backbone Corridor 2 */}
            <path
              d="M 140 520 Q 420 360 700 420"
              fill="none"
              stroke="#eab308"
              strokeWidth="3"
            />
            {/* 230kV Feeder Line */}
            <path
              d="M 450 180 L 510 460"
              fill="none"
              stroke="#facc15"
              strokeWidth="2"
              strokeDasharray="4,3"
            />

            {/* Substations */}
            <g transform="translate(480, 190)">
              <circle r="8" fill="#eab308" stroke="#ffffff" strokeWidth="2" />
              <text x="12" y="4" fill="#fef08a" fontSize="10" fontWeight="bold" fontFamily="sans-serif">
                Pleasant View 500kV
              </text>
            </g>
            <g transform="translate(610, 170)">
              <circle r="8" fill="#eab308" stroke="#ffffff" strokeWidth="2" />
              <text x="12" y="4" fill="#fef08a" fontSize="10" fontWeight="bold" fontFamily="sans-serif">
                Goose Creek 500kV
              </text>
            </g>
            <g transform="translate(490, 370)">
              <circle r="7" fill="#ca8a04" stroke="#ffffff" strokeWidth="1.5" />
              <text x="12" y="4" fill="#fef08a" fontSize="9" fontFamily="sans-serif">
                Gainesville 230kV
              </text>
            </g>
          </g>
        )}

        {/* 3. USGS WATER OBSERVATION WELLS */}
        {layers.waterAquifers && (
          <g className="transition-opacity duration-300">
            <ellipse cx="500" cy="220" rx="150" ry="90" fill="rgba(6, 182, 212, 0.10)" stroke="rgba(6, 182, 212, 0.35)" strokeWidth="1.5" strokeDasharray="3,3" />
            <ellipse cx="430" cy="420" rx="120" ry="70" fill="rgba(6, 182, 212, 0.08)" stroke="rgba(6, 182, 212, 0.25)" strokeWidth="1.5" strokeDasharray="3,3" />

            {[
              { x: 470, y: 210, name: "USGS GW-048 (34ft)" },
              { x: 550, y: 190, name: "USGS GW-051 (38ft)" },
              { x: 420, y: 390, name: "USGS GW-102 (45ft)" },
            ].map((well, idx) => (
              <g key={idx} transform={`translate(${well.x}, ${well.y})`}>
                <circle r="4.5" fill="#06b6d4" stroke="#ffffff" strokeWidth="1" />
                <circle r="8" fill="none" stroke="#06b6d4" strokeWidth="1" opacity="0.6" />
                <text x="10" y="3" fill="#a5f3fc" fontSize="9" fontFamily="monospace">
                  {well.name}
                </text>
              </g>
            ))}
          </g>
        )}

        {/* 4. PRIME CLUSTER DEVELOPMENT ZONE BOUNDARIES */}
        {layers.primeClusters && (
          <g className="transition-opacity duration-300">
            <path
              d="M 420 140 L 680 130 L 700 280 L 440 300 Z"
              fill="rgba(139, 92, 246, 0.15)"
              stroke="#a855f7"
              strokeWidth="2.5"
              strokeDasharray="6,4"
              filter="url(#prime-zone-glow)"
            />
            <text x="450" y="125" fill="#c084fc" fontSize="11" fontWeight="bold" fontFamily="sans-serif">
              ✦ PRIME DEVELOPMENT ZONE A (HYPER-CLUSTER)
            </text>
          </g>
        )}

        {/* 5. 10 KM² PARCEL GRID CELLS */}
        {layers.parcelGrid &&
          parcels.slice(0, 180).map((parcel) => {
            const { x, y } = mapCoordsToSvg(parcel.lon, parcel.lat);
            const size = 34; // Pixel cell size
            const isSelected = selectedParcel?.id === parcel.id || selectedParcel?.grid_id === parcel.grid_id;
            const isHovered = hoveredParcel?.id === parcel.id || hoveredParcel?.grid_id === parcel.grid_id;

            return (
              <g
                key={parcel.id || parcel.grid_id}
                transform={`translate(${x - size / 2}, ${y - size / 2})`}
                onClick={() => onSelectParcel(parcel)}
                onMouseEnter={() => setHoveredParcel(parcel)}
                onMouseLeave={() => setHoveredParcel(null)}
                className="cursor-pointer transition-transform duration-150 hover:scale-110"
              >
                <rect
                  width={size}
                  height={size}
                  rx="4"
                  fill={getParcelColor(parcel.composite_score, parcel.is_prime_zone)}
                  stroke={getParcelStroke(parcel.composite_score, parcel.is_prime_zone, isSelected)}
                  strokeWidth={isSelected ? 2.5 : isHovered ? 2 : 0.8}
                />
                <text
                  x={size / 2}
                  y={size / 2 + 3.5}
                  textAnchor="middle"
                  fill="#ffffff"
                  fontSize="9.5"
                  fontWeight="bold"
                  fontFamily="monospace"
                >
                  {parcel.composite_score.toFixed(0)}
                </text>
              </g>
            );
          })}
      </svg>

      {/* Hover / Selected Parcel Inspector Overlay */}
      {(hoveredParcel || selectedParcel) && (
        <div className="absolute bottom-4 left-4 z-20 w-84 rounded-xl border border-border bg-surface/95 p-3.5 shadow-2xl backdrop-blur-md">
          {(() => {
            const p = hoveredParcel || selectedParcel!;
            return (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-mono text-xs font-bold text-foreground">
                      {p.grid_id}
                    </span>
                    <p className="text-[11px] text-gray-400">
                      {p.county_name} County, {p.state_code} • 10 km²
                    </p>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-lg font-black text-brand-400">
                      {p.composite_score.toFixed(1)}
                    </div>
                    <span className="text-[10px] uppercase font-bold text-gray-400">Suitability</span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs pt-2 border-t border-border">
                  <div className="flex items-center gap-1.5 text-yellow-300">
                    <Zap className="h-3.5 w-3.5" />
                    <span>{p.power_distance_miles} mi ({p.substation_voltage_kv}kV)</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-cyan-300">
                    <Droplets className="h-3.5 w-3.5" />
                    <span>{p.groundwater_depth_ft} ft GW depth</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-emerald-300">
                    <ShieldAlert className="h-3.5 w-3.5" />
                    <span>PGA {p.seismic_hazard_pga}g</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-purple-300">
                    <Sparkles className="h-3.5 w-3.5" />
                    <span>{p.megawatt_capacity_estimate} MW Cap</span>
                  </div>
                </div>

                {p.is_prime_zone && (
                  <div className="rounded-md bg-purple-950/60 px-2 py-1 text-[11px] font-medium text-purple-300 border border-purple-500/30">
                    ★ {p.cluster_label}
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}

      {/* Map Legend */}
      <div className="absolute bottom-4 right-4 z-10 flex items-center gap-3 rounded-lg bg-surface/90 backdrop-blur-md px-3 py-2 border border-border text-[11px] text-foreground">
        <span className="font-semibold text-gray-400">Suitability:</span>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-2.5 rounded bg-emerald-500" />
          <span>Top (82+)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-2.5 rounded bg-blue-500" />
          <span>Good (70-81)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-2.5 rounded bg-purple-500" />
          <span>Prime Cluster</span>
        </div>
      </div>
    </div>
  );
};
