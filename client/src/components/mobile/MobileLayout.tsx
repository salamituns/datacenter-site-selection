"use client";

import React, { useState } from "react";
import { ChevronUp, RefreshCw, Search, SlidersHorizontal, X } from "lucide-react";
import { GridParcel, LayerVisibility, WeightFactors } from "@/types/parcel";
import { ConstraintSliders } from "@/components/ConstraintSliders";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LayerChips } from "./LayerChips";
import { ParcelCards } from "./ParcelCards";

interface MobileLayoutProps {
  parcels: GridParcel[];
  layers: LayerVisibility;
  onToggleLayer: (layerKey: keyof LayerVisibility) => void;
  weights: WeightFactors;
  onWeightChange: (weights: WeightFactors) => void;
  onResetWeights: () => void;
  selectedParcel: GridParcel | null;
  onSelectParcel: (parcel: GridParcel) => void;
  isLive: boolean;
  isSyncing: boolean;
  onSync: () => void;
}

type SheetState = "minimized" | "peek" | "expanded";

const SHEET_HEIGHT: Record<SheetState, string> = {
  minimized: "h-[52px]",
  peek: "h-[36svh]",
  expanded: "h-[78svh]",
};

/**
 * Map-centric mobile chrome: a floating search bar over the full-bleed map
 * and a three-state bottom sheet (peek / expanded / minimized) that owns
 * all filtering and the ranked ledger.
 */
export const MobileLayout: React.FC<MobileLayoutProps> = ({
  parcels,
  layers,
  onToggleLayer,
  weights,
  onWeightChange,
  onResetWeights,
  selectedParcel,
  onSelectParcel,
  isLive,
  isSyncing,
  onSync,
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [sheet, setSheet] = useState<SheetState>("peek");
  const [weightsOpen, setWeightsOpen] = useState(false);

  const filteredParcels = parcels.filter((p) => {
    const q = searchTerm.toLowerCase();
    return (
      p.grid_id.toLowerCase().includes(q) ||
      p.county_name.toLowerCase().includes(q) ||
      p.cluster_label.toLowerCase().includes(q)
    );
  });

  const openWeights = () => {
    setWeightsOpen(true);
    setSheet("expanded");
  };

  return (
    <div className="lg:hidden">
      {/* ── Floating top bar ─────────────────────────────── */}
      <div className="fixed inset-x-3 top-3 z-20 flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            type="text"
            placeholder="Search grid, county, zone…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            aria-label="Search parcels"
            className="h-10 w-full rounded-[3px] border border-border-strong bg-surface/95 py-0 pl-9 pr-3 font-mono text-[11px] text-foreground shadow-plate backdrop-blur placeholder:text-muted focus:border-accent-600 focus:outline-none"
          />
        </div>
        <button
          onClick={onSync}
          disabled={isSyncing}
          aria-label="Sync parcels from PostGIS"
          title="Sync parcels from PostGIS"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[3px] border border-border-strong bg-surface/95 text-muted shadow-plate backdrop-blur transition-colors active:bg-surface-raised disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${isSyncing ? "animate-spin" : ""}`} />
        </button>
        <ThemeToggle className="h-10 w-10 rounded-[3px] bg-surface/95 shadow-plate backdrop-blur" />
      </div>

      {/* ── Bottom sheet ─────────────────────────────────── */}
      <div
        className={`fixed inset-x-0 bottom-0 z-30 flex flex-col overflow-hidden rounded-t-[6px] border-t border-border-strong bg-surface pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_24px_rgb(0_0_0/0.10)] transition-[height] duration-300 ease-out ${SHEET_HEIGHT[sheet]}`}
      >
        {sheet === "minimized" ? (
          /* Collapsed bar — tap to raise the sheet */
          <button
            onClick={() => setSheet("peek")}
            aria-label="Show ranked parcels"
            className="flex h-[52px] w-full items-center justify-between px-4"
          >
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">
              03 — Ranked Parcels
              <span className="ml-2 tabular-nums text-foreground">
                {filteredParcels.length}
              </span>
            </span>
            <ChevronUp className="h-4 w-4 text-muted" />
          </button>
        ) : (
          <>
            {/* Grabber — toggles peek / expanded */}
            <button
              onClick={() => setSheet(sheet === "expanded" ? "peek" : "expanded")}
              aria-label={sheet === "expanded" ? "Collapse sheet" : "Expand sheet"}
              className="flex h-6 w-full shrink-0 items-center justify-center"
            >
              <span className="h-1 w-10 rounded-full bg-border-strong" />
            </button>

            {/* Sheet head */}
            <div className="flex shrink-0 items-center justify-between gap-2 px-3 pb-1.5 pt-0.5">
              <h3 className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">
                03 — Ranked Parcels
                <span className="ml-2 tabular-nums text-foreground">
                  {filteredParcels.length}
                </span>
              </h3>
              <div className="flex items-center gap-2">
                <span
                  className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted"
                  title={isLive ? "Connected to Supabase PostGIS" : "Using local demo dataset"}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      isLive ? "bg-success dark:bg-success-night" : "bg-warning dark:bg-power-night"
                    }`}
                  />
                  {isLive ? "PostGIS" : "Demo"}
                </span>
                <button
                  onClick={() => setSheet("minimized")}
                  aria-label="Minimize sheet"
                  title="View full map"
                  className="flex h-7 w-7 items-center justify-center border border-border-strong text-muted transition-colors active:bg-surface-raised"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* Filter chips — layers + weights */}
            <div className="scrollbar-hide flex shrink-0 gap-2 overflow-x-auto border-b border-border px-3 py-2">
              <button
                onClick={() => (weightsOpen ? setWeightsOpen(false) : openWeights())}
                aria-pressed={weightsOpen}
                className={`flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                  weightsOpen
                    ? "border-foreground bg-foreground text-background"
                    : "border-border-strong text-foreground active:bg-surface-raised"
                }`}
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                Weights
              </button>
              <div className="flex min-w-0 gap-2 overflow-x-auto">
                <LayerChips layers={layers} onToggleLayer={onToggleLayer} />
              </div>
            </div>

            {/* Sheet body — weights dropdown or ledger cards */}
            <div
              className={`min-h-0 flex-1 ${
                sheet === "expanded" && !weightsOpen
                  ? "scrollbar-hide overflow-y-auto"
                  : "overflow-hidden"
              }`}
            >
              {weightsOpen ? (
                <div className="scrollbar-hide h-full overflow-y-auto px-3 pb-4">
                  <ConstraintSliders
                    weights={weights}
                    onWeightChange={onWeightChange}
                    onResetWeights={onResetWeights}
                  />
                  <button
                    onClick={() => setWeightsOpen(false)}
                    className="mt-3 h-10 w-full border border-border-strong bg-background font-mono text-[10px] uppercase tracking-[0.14em] text-foreground transition-colors active:bg-surface-raised"
                  >
                    Done
                  </button>
                </div>
              ) : (
                <ParcelCards
                  parcels={filteredParcels}
                  selectedId={selectedParcel?.id}
                  onSelect={onSelectParcel}
                />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};
