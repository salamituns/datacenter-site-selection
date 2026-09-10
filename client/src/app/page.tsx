"use client";

import React, { useState, useEffect, useMemo, useRef } from "react";
import dynamic from "next/dynamic";
import { Header } from "@/components/Header";
import { LayerControls } from "@/components/LayerControls";
import { ConstraintSliders } from "@/components/ConstraintSliders";
import { RankedParcelsList } from "@/components/RankedParcelsList";
import { ParcelDetailModal } from "@/components/ParcelDetailModal";
import { ParcelQualificationModal } from "@/components/ParcelQualificationModal";
import { ParcelComparisonPanel } from "@/components/ParcelComparisonPanel";
import { Scale } from "lucide-react";
import { PanelEdgeToggle } from "@/components/PanelEdgeToggle";
import { MobileLayout } from "@/components/mobile/MobileLayout";
import { INITIAL_PARCELS } from "@/components/mockData";
import {
  fetchGridParcels,
  fetchLandParcels,
  fetchMapFeatures,
  fetchParcelQualification,
  fetchRegionCounts,
} from "@/lib/supabase";
import { computePrimeZones } from "@/lib/primeZones";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { REGIONS, HOME_REGION } from "@/lib/regions";
import {
  GridParcel,
  LandParcel,
  LayerVisibility,
  MapFeatures,
  ParcelQualification,
  WeightFactors,
} from "@/types/parcel";

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
  // Qualified cadastral parcels (Release 1 pilot) + the open qualification dossier.
  const [landParcels, setLandParcels] = useState<LandParcel[]>([]);
  const [selectedLandParcel, setSelectedLandParcel] = useState<LandParcel | null>(null);

  /**
   * The two dossiers read different things — a 10 km screening cell and a
   * cadastral parcel — and only one can be the subject at a time.
   *
   * They used to be independent, which the centred modals hid: one simply
   * covered the other. Docked side by side the overlap became visible,
   * with two panels claiming the same edge. Selecting either now clears
   * the other, so the panel always answers "what did I just click".
   */
  const selectGridCell = (p: GridParcel | null) => {
    setSelectedLandParcel(null);
    setSelectedParcel(p);
  };
  const selectLandParcel = (p: LandParcel | null) => {
    setSelectedParcel(null);
    setSelectedLandParcel(p);
  };
  // Closing the qualification dossier cannot return focus to the parcel
  // that opened it: changing the selection makes the map rebuild every
  // polygon, so that node is already detached. Focus goes here instead.
  const mapContainerRef = useRef<HTMLDivElement | null>(null);

  // The docked dossier's width, measured rather than assumed, so the map
  // knows exactly how much of itself is covered and can keep the selected
  // parcel clear of it.
  const [dossierWidth, setDossierWidth] = useState(0);
  useEffect(() => {
    // Either dossier docks to the same edge, so either one covers the map.
    if (!selectedLandParcel && !selectedParcel) { setDossierWidth(0); return; }
    const measure = () => {
      const el = document.querySelector<HTMLElement>("[data-dossier-panel]");
      setDossierWidth(el?.offsetWidth ?? 0);
    };
    // After paint, so the panel has a width to report.
    const id = requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    return () => {
      cancelAnimationFrame(id);
      window.removeEventListener("resize", measure);
    };
  }, [selectedLandParcel, selectedParcel]);

  // Shortlist (Release 4d): the set of sites under active comparison.
  // Held as parcel_keys and resolved against landParcels, so a stale key
  // from a previous region simply drops out rather than rendering a ghost.
  const [shortlistKeys, setShortlistKeys] = useState<string[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("shortlist");
      if (saved) setShortlistKeys(JSON.parse(saved));
    } catch {
      // Private mode or blocked storage — the shortlist is a convenience,
      // not state worth failing the page over.
    }
  }, []);

  /**
   * Writes on the change itself rather than in an effect watching the
   * state. A save effect also fires on mount, with the initial empty
   * array, and under StrictMode's double-invoke it beat the hydrating
   * read and wiped the stored shortlist on every page load.
   */
  const updateShortlist = (next: (prev: string[]) => string[]) =>
    setShortlistKeys((prev) => {
      const value = next(prev);
      try {
        localStorage.setItem("shortlist", JSON.stringify(value));
      } catch {
        // Losing persistence must not break shortlisting.
      }
      return value;
    });

  const shortlisted = useMemo(
    () => shortlistKeys
      .map((k) => landParcels.find((p) => p.parcel_key === k))
      .filter((p): p is LandParcel => p !== undefined),
    [shortlistKeys, landParcels]
  );

  const toggleShortlist = (key: string) =>
    updateShortlist((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]);
  const [parcelQualification, setParcelQualification] = useState<ParcelQualification | null>(null);

  // Active map layers
  const [layers, setLayers] = useState<LayerVisibility>({
    powerGrid: true,
    waterAquifers: true,
    seismicHazard: true,
    climateCDD: true,
    primeClusters: true,
    parcelGrid: true,
    qualifiedParcels: false,
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
    // Qualified cadastral parcels ride along; a region without a parcel
    // pilot simply shows none when the layer is toggled.
    setLandParcels([]);
    if (layers.qualifiedParcels) {
      fetchLandParcels(selectedState)
        .then((p) => setLandParcels(p ?? []))
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedState]);

  // Qualified-parcel layer: fetch once per region when first toggled on.
  useEffect(() => {
    if (layers.qualifiedParcels && landParcels.length === 0) {
      fetchLandParcels(selectedState)
        .then((p) => setLandParcels(p ?? []))
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.qualifiedParcels]);

  // Opening a qualification dossier fetches its gates + metrics with
  // evidence classes and source lineage.
  useEffect(() => {
    if (!selectedLandParcel) {
      setParcelQualification(null);
      return;
    }
    setParcelQualification(null);
    fetchParcelQualification(selectedLandParcel.parcel_key)
      .then(setParcelQualification)
      .catch(() => {});
  }, [selectedLandParcel]);

  // Probe which regions have surveys on mount
  useEffect(() => {
    fetchRegionCounts(REGIONS.map((r) => r.code)).then(setRegionCounts);
  }, []);

  // Switching regions invalidates the current selection (it belongs to
  // another survey) — clear it so no dangling dossier stays open.
  const handleStateChange = (stateCode: string) => {
    setSelectedParcel(null);
    setSelectedLandParcel(null);
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
        // Re-weighted from the pure component scores, then re-scaled by
        // the region's evidence coverage — the same factor the worker
        // baked into the stored composite, re-applied so dragging the
        // sliders cannot silently un-do it. Non-reweightable parcels keep
        // their stored (already-scaled) composite.
        const dynamicScore = reweightable(p)
          ? (p.power_score! * wNorm.power +
             p.water_score! * wNorm.water +
             p.risk_score! * wNorm.risk +
             p.climate_score! * wNorm.climate) *
            (p.evidence_coverage ?? 1)
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
            ? (p.power_score * wNorm.power +
               p.water_score * wNorm.water +
               p.risk_score * wNorm.risk +
               p.climate_score * wNorm.climate) *
              (p.evidence_coverage ?? 1)
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
              megawatt_capacity_estimate: null,
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

  // Aggregate key statistics — reactive with the sliders. No MW total:
  // a feasible capacity figure requires a dated source per parcel
  // (Release 2 power diligence), not an area-derived placeholder.
  const totalParcelsCount = displayParcels.length;
  const primeCount = primeResult.zones.length;

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
          <LayerControls
            layers={layers}
            onToggleLayer={handleToggleLayer}
            selectedState={selectedState}
          />
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
        <div
          ref={mapContainerRef}
          className="fixed inset-0 z-0 lg:relative lg:inset-auto lg:z-auto lg:h-full lg:min-h-0"
        >
          <GeospatialMap
            parcels={displayParcels}
            layers={layers}
            selectedParcel={selectedParcel}
            onSelectParcel={selectGridCell}
            isLiveSupabase={isLivePostgis}
            mapFeatures={mapFeatures}
            primeZones={primeResult.zones}
            landParcels={layers.qualifiedParcels ? landParcels : []}
            selectedLandParcel={selectedLandParcel}
            onSelectLandParcel={selectLandParcel}
            revealInsetRight={dossierWidth}
          />
          {/* Rail chevrons hide while either dossier modal is open — they sit
              at z-[500] (above the map's Leaflet panes) and would otherwise
              paint over the modal at widths where the seams cross it. */}
          {!selectedParcel && !selectedLandParcel && (
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
            onSelectParcel={selectGridCell}
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
        onSelectParcel={selectGridCell}
        selectedState={selectedState}
        onStateChange={handleStateChange}
        regionCounts={regionCounts}
        isLive={isLivePostgis}
        isSyncing={isSyncing}
        onSync={handleSync}
      />

      {/* Detailed site dossier */}
      <ParcelDetailModal parcel={selectedParcel} onClose={() => selectGridCell(null)} />

      {/* Parcel qualification dossier (Release 1) */}
      <ParcelQualificationModal
        parcel={selectedLandParcel}
        qualification={parcelQualification}
        onClose={() => selectLandParcel(null)}
        returnFocusTo={mapContainerRef}
        isShortlisted={
          selectedLandParcel != null &&
          shortlistKeys.includes(selectedLandParcel.parcel_key)
        }
        onToggleShortlist={
          selectedLandParcel
            ? () => toggleShortlist(selectedLandParcel.parcel_key)
            : undefined
        }
      />

      {/* Shortlist comparison — the surface the release exists for. */}
      {compareOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Shortlist comparison"
          onClick={() => setCompareOpen(false)}
          className="fixed inset-0 z-[1100] flex items-end justify-center bg-foreground/40 p-0 backdrop-blur-[2px] lg:items-center lg:p-6"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="flex h-[88vh] w-full max-w-6xl flex-col overflow-hidden rounded-t-[6px] border border-border-strong bg-surface shadow-overlay lg:h-[85vh] lg:rounded-[3px]"
          >
            <ParcelComparisonPanel
              parcels={shortlisted}
              onRemove={(k) => updateShortlist((p) => p.filter((x) => x !== k))}
              onClear={() => updateShortlist(() => [])}
              onClose={() => setCompareOpen(false)}
            />
          </div>
        </div>
      )}

      {/* Shortlist dock — only present once something is on it. */}
      {shortlisted.length > 0 && !compareOpen && !selectedLandParcel && (
        <button
          onClick={() => setCompareOpen(true)}
          className="fixed bottom-5 left-1/2 z-[900] flex -translate-x-1/2 items-center gap-2.5 border border-border-strong bg-foreground px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.14em] text-background shadow-overlay transition-opacity hover:opacity-90"
        >
          <Scale className="h-3.5 w-3.5" />
          Compare {shortlisted.length} {shortlisted.length === 1 ? "site" : "sites"}
        </button>
      )}
    </div>
  );
}
