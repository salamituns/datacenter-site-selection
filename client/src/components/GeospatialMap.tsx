"use client";

import React, { useEffect, useRef, useState } from "react";
import { GridParcel, LandParcel, LayerVisibility, MapFeatures } from "@/types/parcel";
import { PrimeZone } from "@/lib/primeZones";
import { useTheme } from "next-themes";

interface GeospatialMapProps {
  parcels: GridParcel[];
  layers: LayerVisibility;
  selectedParcel: GridParcel | null;
  onSelectParcel: (parcel: GridParcel) => void;
  isLiveSupabase?: boolean;
  /** Real HIFLD / USGS infrastructure features for the selected region. */
  mapFeatures?: MapFeatures;
  /** Reactive prime zones (browser DBSCAN) — hulls are drawn as overlays. */
  primeZones?: PrimeZone[];
  /** Qualified cadastral parcels (Release 1 pilot) with gate verdicts. */
  landParcels?: LandParcel[];
  selectedLandParcel?: LandParcel | null;
  /** Width in px of a panel docked to the right edge. The map keeps the
   *  selected parcel out from under it. */
  revealInsetRight?: number;
  onSelectLandParcel?: (parcel: LandParcel) => void;
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
  mapFeatures = { lines: [], substations: [], wells: [] },
  primeZones = [],
  landParcels = [],
  selectedLandParcel = null,
  revealInsetRight = 0,
  onSelectLandParcel,
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
    qualified: any;
    powerGrid: any;
    water: any;
    clusters: any;
  }>({
    parcels: null,
    qualified: null,
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
        qualified: L.layerGroup().addTo(map),
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
        qualified: qualifiedLayer,
        powerGrid: powerLayer,
        water: waterLayer,
        clusters: clusterLayer,
      } = layersGroupRef.current;

      if (!L || !map || !parcelLayer) return;

      parcelLayer.clearLayers();
      qualifiedLayer.clearLayers();
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

      // 0. Reactive Prime Zone tint — the faint fill of each hull from the
      //     browser-side DBSCAN. It renders beneath the parcels (added
      //     first), so parcel clicks and tooltips always win wherever a
      //     parcel exists; the zone tooltip surfaces over the gaps between
      //     cells inside the hull. The dashed boundary renders above (1b).
      if (layers.primeClusters) {
        primeZones.forEach((zone) => {
          if (!zone.hull?.coordinates?.[0]?.length) return;
          const latlngs = zone.hull.coordinates[0].map(
            (coord: number[]) => [coord[1], coord[0]] as [number, number]
          );
          L.polygon(latlngs, {
            stroke: false,
            fillColor: stamp,
            fillOpacity: 0.04,
          })
            .bindTooltip(
              `<b>${zone.label}</b><br/><span class="font-mono">${zone.parcelCount} parcels · ${zone.avgScore}/100</span>`,
              { sticky: true, className: "map-tooltip", direction: "top" }
            )
            .addTo(clusterLayer);
        });
      }

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

      // 1a. Qualified cadastral parcels (Release 1) — verdict-shaded,
      //      drawn above the screening cells. Clicking one opens its
      //      qualification dossier; UNKNOWN is a hatched neutral, never
      //      a guessed color.
      if (layers.qualifiedParcels && landParcels.length > 0) {
        const statusStyle = (status: string | null) => {
          switch (status) {
            case "PASS":
              return { fill: isDark ? "#66C17A" : "#3E8E4E", stroke: isDark ? "#8AD79A" : "#2F6E3C" };
            case "CONDITIONAL":
              return { fill: isDark ? "#E2B056" : "#B07D0F", stroke: isDark ? "#F0C57E" : "#8A6208" };
            case "FAIL":
              return { fill: isDark ? "#E06A5A" : "#B3402F", stroke: isDark ? "#EE8A7B" : "#8F3225" };
            default: // UNKNOWN or null — pending evidence
              return { fill: isDark ? "#9AA5B1" : "#8A8A82", stroke: hairline };
          }
        };
        landParcels.forEach((p) => {
          if (isNaN(p.lat) || isNaN(p.lon)) return;
          const geom = p.geojson_geom;
          if (!geom?.coordinates) return;
          // Polygon: coordinates[number][ring][pt]; MultiPolygon:
          // coordinates[polygon][ring][pt] — normalize to polygon parts.
          const parts: number[][][] =
            geom.type === "MultiPolygon"
              ? (geom.coordinates as number[][][][]).map((poly) => poly[0]).filter(Boolean)
              : [(geom.coordinates as number[][][])[0]];
          if (!parts.some(Boolean)) return;
          const style = statusStyle(p.overall_status);
          const isSelected = selectedLandParcel?.parcel_key === p.parcel_key;
          const latlngParts = parts.map((ring) =>
            (ring ?? []).map((coord) => [coord[1], coord[0]] as [number, number])
          );
          const acres = p.gis_acreage != null ? `${Math.round(p.gis_acreage).toLocaleString()} ac` : "acreage unverified";
          latlngParts.forEach((latlngs) => {
            const polygon = L.polygon(latlngs, {
              color: isSelected ? ink : style.stroke,
              weight: isSelected ? 2 : 1,
              fillColor: style.fill,
              fillOpacity: isSelected ? 0.3 : p.overall_status === "UNKNOWN" ? 0.07 : 0.13,
            });
            polygon.bindTooltip(
              `<span class="font-mono">${p.pin}</span> · ${acres}<br/><b>${p.overall_status ?? "UNQUALIFIED"}</b> · click for gates`,
              { sticky: true, className: "map-tooltip", direction: "top" }
            );
            if (onSelectLandParcel) polygon.on("click", () => onSelectLandParcel(p));
            polygon.addTo(qualifiedLayer);
          });
        });
      }

      // 1b. Reactive Prime Zone hulls — dashed boundary overlay, boundary
      //     only and non-interactive: the convex hull hugs the cell
      //     footprints, so a filled or interactive hull would sit over the
      //     parcels and swallow every click (the "shield" bug). The edge
      //     itself is decorative; zone info lives on the tint's tooltip.
      if (layers.primeClusters) {
        primeZones.forEach((zone) => {
          if (!zone.hull?.coordinates?.[0]?.length) return;
          const latlngs = zone.hull.coordinates[0].map(
            (coord: number[]) => [coord[1], coord[0]] as [number, number]
          );
          L.polygon(latlngs, {
            color: stampStroke,
            weight: 1.75,
            dashArray: "2,4",
            fill: false,
            interactive: false,
          }).addTo(clusterLayer);
        });
      }

      // 2. HIFLD power grid corridors & substations (real, persisted per region)
      if (layers.powerGrid) {
        mapFeatures.lines.forEach((line) => {
          const coords = line.geojson_geom?.coordinates;
          if (!coords || coords.length < 2) return;
          const latlngs = coords.map((coord: number[]) => [coord[1], coord[0]] as [number, number]);
          const kv = line.voltage_kv;
          L.polyline(latlngs, {
            color: power,
            weight: kv >= 345 ? 2.25 : 1.5,
            dashArray: "4, 6",
            opacity: 0.9,
          })
            .bindTooltip(
              `<span class="font-mono">${kv} kV</span> · ${line.owner || "Unknown"}<br/>` +
                `<b>${line.line_name || "Transmission Line"}</b>`,
              { sticky: true, className: "map-tooltip", direction: "top" }
            )
            .addTo(powerLayer);
        });

        mapFeatures.substations.forEach((sub) => {
          if (isNaN(sub.lat) || isNaN(sub.lon)) return;
          const kv = sub.voltage_kv;
          L.circleMarker([sub.lat, sub.lon], {
            radius: kv >= 345 ? 5.5 : 4.5,
            fillColor: power,
            color: nodeRing,
            weight: 1.25,
            opacity: 1,
            fillOpacity: 1,
          })
            .bindTooltip(`${sub.substation_name} · ${kv} kV`, {
              direction: "top",
              className: "map-tooltip",
            })
            .addTo(powerLayer);
        });
      }

      // 3. USGS NWIS observation wells (real, persisted per region)
      if (layers.waterAquifers) {
        mapFeatures.wells.forEach((w) => {
          if (isNaN(w.lat) || isNaN(w.lon)) return;
          L.circleMarker([w.lat, w.lon], {
            radius: 4,
            fillColor: waterColor,
            color: nodeRing,
            weight: 1.25,
            opacity: 1,
            fillOpacity: 1,
          })
            .bindTooltip(
              w.water_depth_ft != null
                ? `USGS ${w.site_no} · ${w.water_depth_ft.toFixed(0)} ft`
                : `USGS ${w.site_no}`,
              { direction: "top", className: "map-tooltip" }
            )
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
  }, [
    mapReady,
    parcels,
    layers,
    selectedParcel,
    resolvedTheme,
    mapFeatures,
    primeZones,
    landParcels,
    selectedLandParcel,
    onSelectLandParcel,
  ]);


  /**
   * Keeps the selected parcel out from under the docked dossier.
   *
   * Deliberately minimal: it pans only when the parcel actually sits
   * behind the panel or off screen, and only far enough to clear it.
   * Recentring on every selection would be its own way of losing your
   * place — the map would jump each time you compared two neighbours.
   */
  useEffect(() => {
    const map = mapInstanceRef.current;
    // Whichever dossier is open, keep its subject clear of the panel.
    const subject = selectedLandParcel ?? selectedParcel;
    if (!map || !subject) return;
    const geom = subject.geojson_geom;
    if (!geom?.coordinates) return;

    const parts: number[][][] =
      geom.type === "MultiPolygon"
        ? (geom.coordinates as number[][][][]).map((poly) => poly[0]).filter(Boolean)
        : [(geom.coordinates as number[][][])[0]];
    const pts = parts.flat().filter(Boolean);
    if (pts.length === 0) return;

    // Corner points only; the projection is monotonic in both axes at a
    // single zoom, so the extremes of the ring give the extremes on screen.
    let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
    for (const c of pts) {
      if (c[0] < minLon) minLon = c[0];
      if (c[0] > maxLon) maxLon = c[0];
      if (c[1] < minLat) minLat = c[1];
      if (c[1] > maxLat) maxLat = c[1];
    }

    const size = map.getSize();
    const tl = map.latLngToContainerPoint([maxLat, minLon]);
    const br = map.latLngToContainerPoint([minLat, maxLon]);
    const visibleRight = size.x - revealInsetRight;
    const margin = 28;

    let dx = 0;
    let dy = 0;
    if (br.x > visibleRight - margin) dx = br.x - (visibleRight - margin);
    else if (tl.x < margin) dx = tl.x - margin;
    if (br.y > size.y - margin) dy = br.y - (size.y - margin);
    else if (tl.y < margin) dy = tl.y - margin;

    if (dx !== 0 || dy !== 0) map.panBy([dx, dy], { animate: true, duration: 0.4 });
    // A function of which parcel is selected and how much of the map the
    // panel covers, not of everything else the map redraws.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLandParcel?.parcel_key, selectedParcel?.grid_id, revealInsetRight, mapReady]);

  return (
    <div className="relative h-full min-h-[360px] w-full overflow-hidden rounded-[3px] border border-border-strong bg-background">
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

      {/* Plate status — desktop only; the mobile sheet carries the status dot */}
      <div className="pointer-events-none absolute left-3 top-3 z-[500] hidden lg:block">
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
        {layers.qualifiedParcels && (
          <div className="mt-1.5 border-t border-border pt-1.5">
            <div className="font-mono text-[8.5px] uppercase tracking-[0.18em] text-muted">
              Parcel verdicts
            </div>
            <div className="mt-1 flex items-center gap-3 font-mono text-[9.5px] uppercase tracking-[0.08em] text-muted">
              {(
                [
                  ["PASS", "#3E8E4E", "#66C17A"],
                  ["COND.", "#B07D0F", "#E2B056"],
                  ["FAIL", "#B3402F", "#E06A5A"],
                  ["UNKNOWN", "#8A8A82", "#9AA5B1"],
                ] as const
              ).map(([label, light, dark]) => (
                <span key={label} className="flex items-center gap-1.5">
                  <span
                    className="h-2.5 w-2.5"
                    style={{
                      background: resolvedTheme === "light" ? light : dark,
                      opacity: 0.75,
                    }}
                  />
                  {label}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
