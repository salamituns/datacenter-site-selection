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

/** Pencil shading: the more suitable the parcel, the darker the graphite. */
function scoreOpacity(score: number): number {
  if (score >= 82) return 0.30;
  if (score >= 70) return 0.20;
  if (score >= 60) return 0.11;
  return 0.05;
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
      L.control.scale({ position: "bottomleft", imperial: true, metric: false }).addTo(map);

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

  // Swap basemap tiles when the theme changes (paper <-> blueprint)
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
      const ink = isDark ? "#E6EDF4" : "#1C1A14"; // shading & hairline ink
      const hairline = isDark ? "rgba(230,237,244,0.18)" : "rgba(28,26,20,0.20)";
      const nodeRing = isDark ? "#112B46" : "#FBF9F3";
      const power = isDark ? "#E2B056" : "#B07D0F";
      const waterColor = isDark ? "#46C0B4" : "#1F7A74";
      const stamp = isDark ? "#F5854A" : "#E8590C"; // prime zone stamp
      const stampStroke = isDark ? "#F9A870" : "#C24A08";
      const validBounds: [number, number][] = [];

      // 1. PostGIS parcels — graphite-shaded suitability, stamped prime zones
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
            color: isSelected ? ink : isPrime ? stampStroke : hairline,
            weight: isSelected ? 2 : isPrime ? 1.25 : 0.75,
            dashArray: isPrime && !isSelected ? "5,3" : undefined,
            fillColor: isPrime ? stamp : ink,
            fillOpacity: isPrime ? 0.22 : opacity,
          });

          polygon.bindTooltip(
            `<span class="font-mono">${p.grid_id}</span> · SCORE <b>${p.composite_score.toFixed(
              1
            )}</b>${p.is_prime_zone ? " · PRIME" : ""}`,
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
            color: power,
            weight: 1.5,
            dashArray: "4, 6",
            opacity: 0.9,
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
            fillColor: power,
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
            fillColor: waterColor,
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
    <div className="relative h-full min-h-[480px] w-full overflow-hidden rounded-[3px] border border-border-strong bg-background">
      <div ref={mapContainerRef} className="absolute inset-0 z-0 h-full w-full" />

      {/* Graticule corner marks */}
      {(["left-2 top-1", "right-2 top-1", "left-2 bottom-1", "right-2 bottom-1"] as const).map(
        (pos) => (
          <span
            key={pos}
            className={`pointer-events-none absolute ${pos} z-[400] select-none font-mono text-[13px] leading-none text-muted/70`}
            aria-hidden="true"
          >
            +
          </span>
        )
      )}

      {/* Plate status */}
      <div className="pointer-events-none absolute left-3 top-3 z-[500]">
        <div className="flex items-center gap-2 border border-border-strong bg-surface/95 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted shadow-plate backdrop-blur">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              isLiveSupabase ? "bg-success dark:bg-success-night" : "bg-warning dark:bg-power-night"
            }`}
          />
          <span className="text-foreground">{isLiveSupabase ? "PostGIS" : "Demo"}</span>
          <span>·</span>
          <span className="tabular-nums">{parcels.length} parcels</span>
        </div>
      </div>

      {/* Map key */}
      <div className="absolute bottom-3 right-3 z-[500] border border-border-strong bg-surface/95 px-3 py-2 shadow-plate backdrop-blur">
        <div className="font-mono text-[8.5px] uppercase tracking-[0.18em] text-muted">
          Suitability
        </div>
        <div className="mt-1.5 flex items-center gap-3 font-mono text-[9.5px] uppercase tracking-[0.08em] text-muted">
          {[
            { op: 0.05, label: "<60" },
            { op: 0.11, label: "60+" },
            { op: 0.20, label: "70+" },
            { op: 0.30, label: "82+" },
          ].map((step) => (
            <span key={step.label} className="flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5"
                style={{
                  background: resolvedTheme === "light" ? "#1C1A14" : "#E6EDF4",
                  opacity: step.op,
                }}
              />
              {step.label}
            </span>
          ))}
          <span className="flex items-center gap-1.5 text-foreground">
            <span
              className="h-2.5 w-2.5"
              style={{
                background:
                  resolvedTheme === "light"
                    ? "rgba(232,89,12,0.22)"
                    : "rgba(245,133,74,0.25)",
                border: `1px dashed ${resolvedTheme === "light" ? "#C24A08" : "#F9A870"}`,
              }}
            />
            Prime
          </span>
        </div>
      </div>
    </div>
  );
};
