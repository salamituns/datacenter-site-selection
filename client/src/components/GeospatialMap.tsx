"use client";

import React, { useEffect, useRef, useState } from "react";
import { GridParcel, LayerVisibility } from "@/types/parcel";
import { useTheme } from "next-themes";

interface GeospatialMapProps {
  parcels: GridParcel[];
  layers: LayerVisibility;
  selectedParcel: GridParcel | null;
  onSelectParcel: (parcel: GridParcel) => void;
  isLiveSupabase?: boolean;
}

const BRAND = "#5E6AD2";
const BRAND_LIGHT = "#8B96E3";

/** Sequential single-hue fill: darker = more suitable. */
function scoreOpacity(score: number): number {
  if (score >= 82) return 0.55;
  if (score >= 70) return 0.38;
  if (score >= 60) return 0.22;
  return 0.10;
}

export const GeospatialMap: React.FC<GeospatialMapProps> = ({
  parcels,
  layers,
  selectedParcel,
  onSelectParcel,
  isLiveSupabase = false,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<any>(null);
  const leafletRef = useRef<any>(null);
  const baseLayerRef = useRef<any>(null);
  const refLayerRef = useRef<any>(null);
  const fitSignatureRef = useRef<string>("");
  const [mapReady, setMapReady] = useState(false);
  const { resolvedTheme } = useTheme();

  const layersGroupRef = useRef<{
    parcels: any;
    powerGrid: any;
    water: any;
    clusters: any;
  }>({
    parcels: null,
    powerGrid: null,
    water: null,
    clusters: null,
  });

  // Initialize the map exactly once
  useEffect(() => {
    if (typeof window === "undefined" || !mapContainerRef.current) return;
    let cancelled = false;

    async function initMap() {
      const L = (await import("leaflet")).default;
      if (cancelled || !mapContainerRef.current) return;

      leafletRef.current = L;
      const map = L.map(mapContainerRef.current, {
        center: [39.02, -77.55],
        zoom: 11,
        zoomControl: false,
        attributionControl: true,
      });
      map.attributionControl.setPosition("bottomleft");

      L.control.zoom({ position: "topright" }).addTo(map);

      layersGroupRef.current = {
        parcels: L.layerGroup().addTo(map),
        powerGrid: L.layerGroup().addTo(map),
        water: L.layerGroup().addTo(map),
        clusters: L.layerGroup().addTo(map),
      };

      mapInstanceRef.current = map;
      setTimeout(() => {
        mapInstanceRef.current?.invalidateSize();
        setMapReady(true);
      }, 50);
    }

    initMap();

    const resizeObserver = new ResizeObserver(() => {
      mapInstanceRef.current?.invalidateSize();
    });
    if (mapContainerRef.current) {
      resizeObserver.observe(mapContainerRef.current);
    }

    return () => {
      cancelled = true;
      resizeObserver.disconnect();
      setMapReady(false);
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  // Swap basemap tiles when the theme changes (no map re-init)
  useEffect(() => {
    const L = leafletRef.current;
    const map = mapInstanceRef.current;
    if (!L || !map || !mapReady) return;

    const theme = resolvedTheme === "light" ? "Light" : "Dark";
    const base = `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${theme}_Gray_Base/MapServer/tile/{z}/{y}/{x}`;
    const ref = `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${theme}_Gray_Reference/MapServer/tile/{z}/{y}/{x}`;

    if (baseLayerRef.current) {
      baseLayerRef.current.setUrl(base);
      refLayerRef.current?.setUrl(ref);
    } else {
      baseLayerRef.current = L.tileLayer(base, {
        maxZoom: 16,
        attribution: "Esri, HERE, Garmin",
      }).addTo(map);
      refLayerRef.current = L.tileLayer(ref, { maxZoom: 16 }).addTo(map);
    }
  }, [mapReady, resolvedTheme]);

  // Update layers when parcels, weights, or visibility change
  useEffect(() => {
    if (!mapReady || typeof window === "undefined") return;

    async function updateLayers() {
      const L = leafletRef.current;
      const map = mapInstanceRef.current;
      const {
        parcels: parcelLayer,
        powerGrid: powerLayer,
        water: waterLayer,
        clusters: clusterLayer,
      } = layersGroupRef.current;

      if (!L || !map || !parcelLayer) return;

      parcelLayer.clearLayers();
      powerLayer.clearLayers();
      waterLayer.clearLayers();
      clusterLayer.clearLayers();

      const isDark = resolvedTheme !== "light";
      const hairline = isDark ? "rgba(255,255,255,0.14)" : "rgba(0,0,0,0.12)";
      const nodeRing = isDark ? "#0F1011" : "#FFFFFF";
      const validBounds: [number, number][] = [];

      // 1. PostGIS parcels — sequential indigo suitability fill
      if (layers.parcelGrid && parcels.length > 0) {
        parcels.forEach((p) => {
          if (isNaN(p.lat) || isNaN(p.lon)) return;
          validBounds.push([p.lat, p.lon]);

          let polygonCoords: [number, number][];
          if (
            p.geojson_geom &&
            p.geojson_geom.coordinates &&
            p.geojson_geom.coordinates[0]
          ) {
            polygonCoords = p.geojson_geom.coordinates[0].map((coord: number[]) => [
              coord[1],
              coord[0],
            ]);
          } else {
            const halfLat = 0.0142;
            const halfLon = 0.0182;
            polygonCoords = [
              [p.lat - halfLat, p.lon - halfLon],
              [p.lat + halfLat, p.lon - halfLon],
              [p.lat + halfLat, p.lon + halfLon],
              [p.lat - halfLat, p.lon + halfLon],
            ];
          }

          const isSelected = selectedParcel?.grid_id === p.grid_id;
          const isPrime = p.is_prime_zone && layers.primeClusters;
          const opacity = scoreOpacity(p.composite_score);

          const polygon = L.polygon(polygonCoords, {
            color: isSelected
              ? isDark
                ? "#F7F8F8"
                : "#18181B"
              : isPrime
                ? BRAND_LIGHT
                : hairline,
            weight: isSelected ? 2 : isPrime ? 1.25 : 0.75,
            fillColor: BRAND,
            fillOpacity: isPrime ? 0.6 : opacity,
          });

          polygon.bindTooltip(
            `<span class="font-mono">${p.grid_id}</span> · Score <b>${p.composite_score.toFixed(
              1
            )}</b>${p.is_prime_zone ? " · Prime zone" : ""}`,
            {
              sticky: true,
              className: "map-tooltip",
              direction: "top",
            }
          );

          polygon.on("click", () => onSelectParcel(p));
          polygon.addTo(isPrime ? clusterLayer : parcelLayer);
        });
      }

      // 2. HIFLD power grid corridors & substations
      if (layers.powerGrid) {
        const txCorridors = [
          [
            [39.18, -77.85],
            [39.05, -77.55],
            [38.95, -77.25],
          ],
          [
            [39.22, -77.65],
            [38.98, -77.58],
            [38.78, -77.52],
          ],
          [
            [38.88, -77.85],
            [38.82, -77.54],
            [38.75, -77.25],
          ],
        ];

        txCorridors.forEach((line) => {
          L.polyline(line as any, {
            color: "#D99E41",
            weight: 1.5,
            dashArray: "4, 6",
            opacity: 0.85,
          }).addTo(powerLayer);
        });

        const substations = [
          { lat: 39.04, lon: -77.52, name: "Pleasant View", kv: 500 },
          { lat: 39.08, lon: -77.45, name: "Goose Creek", kv: 500 },
          { lat: 38.83, lon: -77.58, name: "Gainesville", kv: 230 },
          { lat: 39.16, lon: -77.68, name: "Lucketts", kv: 500 },
        ];

        substations.forEach((sub) => {
          L.circleMarker([sub.lat, sub.lon], {
            radius: 4.5,
            fillColor: "#D99E41",
            color: nodeRing,
            weight: 1.25,
            opacity: 1,
            fillOpacity: 1,
          })
            .bindTooltip(`${sub.name} · ${sub.kv} kV`, {
              direction: "top",
              className: "map-tooltip",
            })
            .addTo(powerLayer);
        });
      }

      // 3. USGS water observation wells
      if (layers.waterAquifers) {
        const wells = [
          { lat: 39.11, lon: -77.61, id: "GW-001", depth: 34.2 },
          { lat: 38.88, lon: -77.32, id: "GW-002", depth: 38.0 },
          { lat: 39.01, lon: -77.43, id: "GW-003", depth: 42.5 },
          { lat: 39.04, lon: -77.5, id: "GW-004", depth: 28.0 },
        ];

        wells.forEach((w) => {
          L.circleMarker([w.lat, w.lon], {
            radius: 4,
            fillColor: "#4DB6AC",
            color: nodeRing,
            weight: 1.25,
            opacity: 1,
            fillOpacity: 1,
          })
            .bindTooltip(`USGS ${w.id} · ${w.depth} ft`, {
              direction: "top",
              className: "map-tooltip",
            })
            .addTo(waterLayer);
        });
      }

      // 4. Fit bounds — only when the parcel set itself changes, not when
      //    weights or selection change (prevents viewport jumps).
      const signature = `${parcels.length}:${parcels[0]?.grid_id ?? ""}`;
      if (validBounds.length > 0 && fitSignatureRef.current !== signature) {
        fitSignatureRef.current = signature;
        map.fitBounds(L.latLngBounds(validBounds), { padding: [30, 30] });
      }
    }

    updateLayers();
  }, [mapReady, parcels, layers, selectedParcel, resolvedTheme]);

  return (
    <div className="relative h-full min-h-[480px] w-full overflow-hidden rounded-xl border border-border bg-background">
      <div ref={mapContainerRef} className="absolute inset-0 z-0 h-full w-full" />

      {/* Status */}
      <div className="pointer-events-none absolute left-3 top-3 z-[500]">
        <div className="flex items-center gap-2 rounded-md border border-border bg-surface/90 px-2.5 py-1.5 text-[11px] font-medium text-muted shadow-raised backdrop-blur">
          <span
            className={`h-1.5 w-1.5 rounded-full ${isLiveSupabase ? "bg-success" : "bg-warning"}`}
          />
          <span className="text-foreground">{isLiveSupabase ? "PostGIS" : "Demo dataset"}</span>
          <span className="text-muted">·</span>
          <span className="font-mono tabular-nums">{parcels.length} parcels</span>
        </div>
      </div>

      {/* Legend */}
      <div className="absolute bottom-3 right-3 z-[500] rounded-md border border-border bg-surface/90 px-3 py-2 text-[10px] font-medium text-muted shadow-raised backdrop-blur">
        <div className="mb-1.5 text-[9px] uppercase tracking-wide">Suitability</div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ background: BRAND, opacity: 0.1 }}
            />
            &lt; 60
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ background: BRAND, opacity: 0.22 }}
            />
            60+
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ background: BRAND, opacity: 0.38 }}
            />
            70+
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ background: BRAND, opacity: 0.55 }}
            />
            82+
          </span>
          <span className="flex items-center gap-1.5 text-foreground">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ background: BRAND, opacity: 0.6, border: `1px solid ${BRAND_LIGHT}` }}
            />
            Prime
          </span>
        </div>
      </div>
    </div>
  );
};
