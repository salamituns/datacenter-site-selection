"use client";

import React, { useState, useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { Header } from "@/components/Header";
import { LayerControls } from "@/components/LayerControls";
import { ConstraintSliders } from "@/components/ConstraintSliders";
import { RankedParcelsList } from "@/components/RankedParcelsList";
import { ParcelDetailModal } from "@/components/ParcelDetailModal";
import { PanelEdgeToggle } from "@/components/PanelEdgeToggle";
import { MobileLayout } from "@/components/mobile/MobileLayout";
import { INITIAL_PARCELS } from "@/components/mockData";
import { fetchGridParcels, fetchMapFeatures, fetchRegionCounts } from "@/lib/supabase";
import { computePrimeZones, PrimeZone } from "@/lib/primeZones";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { REGIONS, HOME_REGION } from "@/lib/regions";
import { GridParcel, LayerVisibility, MapFeatures, WeightFactors } from "@/types/parcel";

// Dynamically import the Leaflet map component to avoid SSR window issues
const GeospatialMap = dynamic(
  () => import("@/components/GeospatialMap").then((mod) => mod.GeospatialMap),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full min-h-[360px] w-full items-center justify-center rounded-[3px] border border-border-strong bg-surface">
        <div className="flex flex-col items-center gap-2.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-border-strong border-t-accent-600" />
          <span>Preparing plate…</span>
        </div>
      </div>
    ),
  }
);

const DEFAULT_WEIGHTS: WeightFactors = {
  powerWeight: 40,
  waterWeight: 25,
  riskWeight: 20,
  climateWeight: 15,
};

export default function DashboardPage() {
  const [selectedState, setSelectedState] = useState<string>(HOME_REGION);
  const [selectedParcel, setSelectedParcel] = useState<GridParcel | null>(null);
  const [rawParcels, setRawParcels] = useState<GridParcel[]>(INITIAL_PARCELS);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [isLivePostgis, setIsLivePostgis] = useState<boolean>(false);
  // Parcel counts per region — null until probed; drives selector availability.
  const [regionCounts, setRegionCounts] = useState<Record<string, number> | null>(null);
  // Real infrastructure features (HIFLD lines/substations, USGS wells) drawn on the map.
  const [mapFeatures, setMapFeatures] = useState<MapFeatures>({ lines: [], substations: [], wells: [] });

  // Active map layers
  const [layers, setLayers] = useState<LayerVisibility>({
    powerGrid: true,
    waterAquifers: true,
    seismicHazard: true,
    climateCDD: true,
    primeClusters: true,
    parcelGrid: true,
  });

  // Desktop rail visibility — toggled from the header buttons
  const [leftRailOpen, setLeftRailOpen] = useState(true);
  const [rightRailOpen, setRightRailOpen] = useState(true);

  // Dynamic weighting factors
  const [weights, setWeights] = useState<WeightFactors>(DEFAULT_WEIGHTS);

  // Minimum composite score for Prime Development Zone candidacy. Defaults
  // to the worker's ingestion-time threshold; exposed as a slider.
  const [primeThreshold, setPrimeThreshold] = useState(60);

  // Load the surveyed parcels for a region. Live PostGIS data when rows
  // exist; the home region falls back to the demo dataset when unreachable,
  // other regions show an honest empty survey until ingested.
  const loadParcels = async (stateCode: string) => {
    setIsSyncing(true);
    const data = await fetchGridParcels(500, stateCode);
    if (data && data.length > 0) {
      setRawParcels(data);
      setIsLivePostgis(true);
    } else {
      setRawParcels(stateCode === HOME_REGION ? INITIAL_PARCELS : []);
      setIsLivePostgis(false);
    }
    setIsSyncing(false);
  };

  // Initial + per-region load
  useEffect(() => {
    loadParcels(selectedState);
    // Map features refresh alongside the parcel survey (independent — a
    // marker-layer failure must not blank the parcel grid).
    fetchMapFeatures(selectedState).then(setMapFeatures).catch(() => {});
  }, [selectedState]);

  // Probe which regions have surveys on mount
  useEffect(() => {
    fetchRegionCounts(REGIONS.map((r) => r.code)).then(setRegionCounts);
  }, []);

  // Switching regions invalidates the current selection (it belongs to
  // another survey) — clear it so no dangling dossier stays open.
  const handleStateChange = (stateCode: string) => {
    setSelectedParcel(null);
    setSelectedState(stateCode);
  };

  const handleSync = async () => {
    setIsSyncing(true);
    const data = await fetchGridParcels(500, selectedState);
    if (data && data.length > 0) {
      setRawParcels(data);
      setIsLivePostgis(true);
    }
    setIsSyncing(false);
  };

  const handleToggleLayer = (key: keyof LayerVisibility) => {
    setLayers((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const handleResetWeights = () => {
    setWeights(DEFAULT_WEIGHTS);
    setPrimeThreshold(60);
  };

  // Dynamically recompute parcel composite scores when sliders change.
  // This is the live path: cheap arithmetic per parcel, runs on every tick,
  // and drives the map shading instantly.
  const computedParcels = useMemo(() => {
    const totalWeight =
      weights.powerWeight + weights.waterWeight + weights.riskWeight + weights.climateWeight;
    const wNorm = {
      power: weights.powerWeight / (totalWeight || 1),
      water: weights.waterWeight / (totalWeight || 1),
      risk: weights.riskWeight / (totalWeight || 1),
      climate: weights.climateWeight / (totalWeight || 1),
    };

    // Parcels missing any sub-score cannot be re-weighted — they keep
    // their stored composite (never an invented value).
    const reweightable = (p: GridParcel) =>
      p.power_score != null &&
      p.water_score != null &&
      p.risk_score != null &&
      p.climate_score != null;

    return rawParcels
      .map((p) => {
        const dynamicScore = reweightable(p)
          ? p.power_score! * wNorm.power +
            p.water_score! * wNorm.water +
            p.risk_score! * wNorm.risk +
            p.climate_score! * wNorm.climate
          : p.composite_score;

        return {
          ...p,
          composite_score: Number(dynamicScore.toFixed(1)),
        };
      })
      .sort((a, b) => b.composite_score - a.composite_score);
  }, [rawParcels, weights]);

  // Heavier derived work (DBSCAN + convex hulls) trails the sliders on a
  // debounced value so mid-drag frames stay light; zones and stamps morph
  // a few frames after the shading does.
  const debouncedWeights = useDebouncedValue(weights, 75);
  const debouncedThreshold = useDebouncedValue(primeThreshold, 75);

  // Scores recomputed with the debounced weights — the clustering input.
  const zoneScoredParcels = useMemo(() => {
    const totalWeight =
      debouncedWeights.powerWeight +
      debouncedWeights.waterWeight +
      debouncedWeights.riskWeight +
      debouncedWeights.climateWeight;
    const wNorm = {
      power: debouncedWeights.powerWeight / (totalWeight || 1),
      water: debouncedWeights.waterWeight / (totalWeight || 1),
      risk: debouncedWeights.riskWeight / (totalWeight || 1),
      climate: debouncedWeights.climateWeight / (totalWeight || 1),
    };
    return rawParcels.map((p) => ({
      ...p,
      composite_score: Number(
        (
          p.power_score != null &&
          p.water_score != null &&
          p.risk_score != null &&
          p.climate_score != null
            ? p.power_score * wNorm.power +
              p.water_score * wNorm.water +
              p.risk_score * wNorm.risk +
              p.climate_score * wNorm.climate
            : p.composite_score
        ).toFixed(1)
      ),
    }));
  }, [rawParcels, debouncedWeights]);

  // Reactive Prime Development Zones — browser-side DBSCAN (Turf) mirroring
  // the worker's ingestion semantics. No PostGIS round-trip per slider tick.
  const primeResult = useMemo(
    () => computePrimeZones(zoneScoredParcels, debouncedThreshold),
    [zoneScoredParcels, debouncedThreshold]
  );

  // Blend: live composite scores (instant shading) + debounced prime zone
  // designation (stamps, labels, capacities). The ledger, dossier, and map
  // all consume this, so the whole UI is slider-reactive.
  const displayParcels = useMemo(
    () =>
      computedParcels.map((p) => {
        const zone = primeResult.parcelZone.get(p.id);
        return zone
          ? {
              ...p,
              is_prime_zone: true,
              cluster_zone_id: zone.id,
              cluster_label: zone.label,
              megawatt_capacity_estimate: zone.mwCapacity,
            }
          : {
              ...p,
              is_prime_zone: false,
              cluster_zone_id: -1,
              cluster_label: "Secondary Candidate",
            };
      }),
    [computedParcels, primeResult]
  );

  // Aggregate key statistics — reactive with the sliders.
  const totalParcelsCount = displayParcels.length;
  const primeCount = primeResult.zones.length;
  const totalCapacityMW = primeResult.zones.reduce(
    (acc, z: PrimeZone) => acc + z.mwCapacity,
    0
  );

  // Desktop grid template tracks rail visibility so the map re-flows
  // into whatever space the visible rails leave.
  const gridTemplate =
    leftRailOpen && rightRailOpen
      ? "lg:grid-cols-[280px_minmax(0,1fr)_340px]"
      : leftRailOpen
      ? "lg:grid-cols-[280px_minmax(0,1fr)]"
      : rightRailOpen
      ? "lg:grid-cols-[minmax(0,1fr)_340px]"
      : "lg:grid-cols-1";

  return (
    <div className="flex min-h-screen flex-col bg-background lg:h-screen lg:overflow-hidden">
      <Header
        totalParcels={totalParcelsCount}
        primeCount={primeCount}
        totalCapacityMW={totalCapacityMW}
        selectedState={selectedState}
        onStateChange={handleStateChange}
        regionCounts={regionCounts}
        isLive={isLivePostgis}
        isSyncing={isSyncing}
        onSync={handleSync}
      />

      <main
        className={`grid min-h-0 flex-1 grid-cols-1 ${gridTemplate} lg:gap-4 lg:p-4`}
      >
        {/* Left rail: layers & scoring weights — desktop only (mobile owns them in the sheet) */}
        <div
          className={`hidden space-y-4 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:scrollbar-hide ${
            leftRailOpen ? "lg:block" : "lg:hidden"
          }`}
        >
          <LayerControls layers={layers} onToggleLayer={handleToggleLayer} />
          <ConstraintSliders
            weights={weights}
            onWeightChange={setWeights}
            onResetWeights={handleResetWeights}
            primeThreshold={primeThreshold}
            onPrimeThresholdChange={setPrimeThreshold}
          />
        </div>

        {/* Map: full-bleed fixed background on mobile, center column on desktop.
            Anchors the panel edge toggles, which straddle the seams to the
            side rails and stay reachable at the map edge when a rail closes. */}
        <div className="fixed inset-0 z-0 lg:relative lg:inset-auto lg:z-auto lg:h-full lg:min-h-0">
          <GeospatialMap
            parcels={displayParcels}
            layers={layers}
            selectedParcel={selectedParcel}
            onSelectParcel={setSelectedParcel}
            isLiveSupabase={isLivePostgis}
            mapFeatures={mapFeatures}
            primeZones={primeResult.zones}
          />
          {/* Rail chevrons hide while the dossier modal is open — they sit
              at z-[500] (above the map's Leaflet panes) and would otherwise
              paint over the modal at widths where the seams cross it. */}
          {!selectedParcel && (
            <>
              <PanelEdgeToggle
                side="left"
                open={leftRailOpen}
                onToggle={() => setLeftRailOpen((v) => !v)}
                titleOpen="Hide layers & weights panel"
                titleClosed="Show layers & weights panel"
              />
              <PanelEdgeToggle
                side="right"
                open={rightRailOpen}
                onToggle={() => setRightRailOpen((v) => !v)}
                titleOpen="Hide ranked parcels panel"
                titleClosed="Show ranked parcels panel"
              />
            </>
          )}
        </div>

        {/* Right rail: ranked candidate parcels — desktop only */}
        <div
          className={`hidden lg:h-full lg:min-h-0 ${
            rightRailOpen ? "lg:block" : "lg:hidden"
          }`}
        >
          <RankedParcelsList
            parcels={displayParcels}
            selectedParcel={selectedParcel}
            onSelectParcel={setSelectedParcel}
          />
        </div>
      </main>

      {/* Mobile map-centric chrome: floating top bar + bottom sheet */}
      <MobileLayout
        parcels={displayParcels}
        layers={layers}
        onToggleLayer={handleToggleLayer}
        weights={weights}
        onWeightChange={setWeights}
        onResetWeights={handleResetWeights}
        primeThreshold={primeThreshold}
        onPrimeThresholdChange={setPrimeThreshold}
        selectedParcel={selectedParcel}
        onSelectParcel={setSelectedParcel}
        selectedState={selectedState}
        onStateChange={handleStateChange}
        regionCounts={regionCounts}
        isLive={isLivePostgis}
        isSyncing={isSyncing}
        onSync={handleSync}
      />

      {/* Detailed site dossier */}
      <ParcelDetailModal parcel={selectedParcel} onClose={() => setSelectedParcel(null)} />
    </div>
  );
}
