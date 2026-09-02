"use client";

import React, { useState, useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { Header } from "@/components/Header";
import { LayerControls } from "@/components/LayerControls";
import { ConstraintSliders } from "@/components/ConstraintSliders";
import { RankedParcelsList } from "@/components/RankedParcelsList";
import { ParcelDetailModal } from "@/components/ParcelDetailModal";
import { MobileLayout } from "@/components/mobile/MobileLayout";
import { INITIAL_PARCELS } from "@/components/mockData";
import { fetchGridParcels, fetchRegionCounts } from "@/lib/supabase";
import { REGIONS, HOME_REGION } from "@/lib/regions";
import { GridParcel, LayerVisibility, WeightFactors } from "@/types/parcel";

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

  // Active map layers
  const [layers, setLayers] = useState<LayerVisibility>({
    powerGrid: true,
    waterAquifers: true,
    seismicHazard: true,
    climateCDD: true,
    primeClusters: true,
    parcelGrid: true,
  });

  // Dynamic weighting factors
  const [weights, setWeights] = useState<WeightFactors>(DEFAULT_WEIGHTS);

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
  };

  // Dynamically recompute parcel composite scores when sliders change
  const computedParcels = useMemo(() => {
    const totalWeight =
      weights.powerWeight + weights.waterWeight + weights.riskWeight + weights.climateWeight;
    const wNorm = {
      power: weights.powerWeight / (totalWeight || 1),
      water: weights.waterWeight / (totalWeight || 1),
      risk: weights.riskWeight / (totalWeight || 1),
      climate: weights.climateWeight / (totalWeight || 1),
    };

    return rawParcels
      .map((p) => {
        const dynamicScore =
          p.power_score * wNorm.power +
          p.water_score * wNorm.water +
          p.risk_score * wNorm.risk +
          p.climate_score * wNorm.climate;

        return {
          ...p,
          composite_score: Number(dynamicScore.toFixed(1)),
        };
      })
      .sort((a, b) => b.composite_score - a.composite_score);
  }, [rawParcels, weights]);

  // Aggregate key statistics
  const totalParcelsCount = computedParcels.length;
  const primeParcels = computedParcels.filter((p) => p.is_prime_zone);
  const primeCount = new Set(primeParcels.map((p) => p.cluster_zone_id)).size;

  // Total capacity from unique prime zone clusters
  const clusterCapacities = new Map<number, number>();
  primeParcels.forEach((p) => {
    if (p.cluster_zone_id >= 0 && !clusterCapacities.has(p.cluster_zone_id)) {
      clusterCapacities.set(p.cluster_zone_id, p.megawatt_capacity_estimate);
    }
  });
  const totalCapacityMW =
    Array.from(clusterCapacities.values()).reduce((acc, val) => acc + val, 0) || 1500;

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

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)_340px] lg:gap-4 lg:p-4">
        {/* Left rail: layers & scoring weights — desktop only (mobile owns them in the sheet) */}
        <div className="hidden space-y-4 lg:block lg:h-full lg:min-h-0 lg:overflow-y-auto lg:scrollbar-hide">
          <LayerControls layers={layers} onToggleLayer={handleToggleLayer} />
          <ConstraintSliders
            weights={weights}
            onWeightChange={setWeights}
            onResetWeights={handleResetWeights}
          />
        </div>

        {/* Map: full-bleed fixed background on mobile, center column on desktop */}
        <div className="fixed inset-0 z-0 lg:static lg:inset-auto lg:z-auto lg:h-full lg:min-h-0">
          <GeospatialMap
            parcels={computedParcels}
            layers={layers}
            selectedParcel={selectedParcel}
            onSelectParcel={setSelectedParcel}
            isLiveSupabase={isLivePostgis}
          />
        </div>

        {/* Right rail: ranked candidate parcels — desktop only */}
        <div className="hidden lg:block lg:h-full lg:min-h-0">
          <RankedParcelsList
            parcels={computedParcels}
            selectedParcel={selectedParcel}
            onSelectParcel={setSelectedParcel}
          />
        </div>
      </main>

      {/* Mobile map-centric chrome: floating top bar + bottom sheet */}
      <MobileLayout
        parcels={computedParcels}
        layers={layers}
        onToggleLayer={handleToggleLayer}
        weights={weights}
        onWeightChange={setWeights}
        onResetWeights={handleResetWeights}
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
