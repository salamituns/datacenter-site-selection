"use client";

import React, { useRef, useState } from "react";
import { ChevronDown, ChevronUp, RefreshCw, Search, SlidersHorizontal, X } from "lucide-react";
import { GridParcel, LayerVisibility, WeightFactors } from "@/types/parcel";
import { ConstraintSliders } from "@/components/ConstraintSliders";
import { BenchmarkMark } from "@/components/Header";
import { ThemeToggle } from "@/components/ThemeToggle";
import { REGIONS, HOME_REGION } from "@/lib/regions";
import { LayerChips } from "./LayerChips";
import { ParcelCards } from "./ParcelCards";

interface MobileLayoutProps {
  parcels: GridParcel[];
  layers: LayerVisibility;
  onToggleLayer: (layerKey: keyof LayerVisibility) => void;
  weights: WeightFactors;
  onWeightChange: (weights: WeightFactors) => void;
  onResetWeights: () => void;
  /** Minimum composite score for Prime Zone candidacy (worker baseline: 60). */
  primeThreshold: number;
  onPrimeThresholdChange: (threshold: number) => void;
  selectedParcel: GridParcel | null;
  onSelectParcel: (parcel: GridParcel) => void;
  selectedRegion: string;
  onRegionChange: (region: string) => void;
  /** Parcel counts per region code — unsurveyed regions are disabled. */
  regionCounts?: Record<string, number> | null;
  isLive: boolean;
  isSyncing: boolean;
  onSync: () => void;
}

type SheetState = "minimized" | "peek" | "expanded";

/** Snap-point heights in px for the current viewport. */
function snapHeights(): Record<SheetState, number> {
  const vh = typeof window === "undefined" ? 0 : window.innerHeight;
  return {
    minimized: 52,
    peek: Math.round(vh * 0.36),
    expanded: Math.round(vh * 0.78),
  };
}

/**
 * Map-centric mobile chrome: a floating search bar over the full-bleed map
 * and a drag-able bottom sheet (peek / expanded / minimized) that owns all
 * filtering and the ranked ledger. The grabber drags the sheet between snap
 * points; the ledger scrolls inside the sheet in peek and expanded states.
 */
export const MobileLayout: React.FC<MobileLayoutProps> = ({
  parcels,
  layers,
  onToggleLayer,
  weights,
  onWeightChange,
  onResetWeights,
  primeThreshold,
  onPrimeThresholdChange,
  selectedParcel,
  onSelectParcel,
  selectedRegion,
  onRegionChange,
  regionCounts,
  isLive,
  isSyncing,
  onSync,
}) => {
  const isSelectable = (code: string) =>
    code === HOME_REGION || (regionCounts?.[code] ?? 0) > 0;

  const [searchTerm, setSearchTerm] = useState("");
  const [sheet, setSheet] = useState<SheetState>("peek");
  const [weightsOpen, setWeightsOpen] = useState(false);

  // Live drag: px height override while dragging, null when snapped.
  const [dragH, setDragH] = useState<number | null>(null);
  const dragStart = useRef<{ y: number; h: number } | null>(null);
  // Suppresses the synthetic click that follows a real drag gesture.
  const lastDragEnd = useRef(0);

  const tapAfterDrag = () => {
    if (Date.now() - lastDragEnd.current < 300) return true;
    return false;
  };

  const filteredParcels = parcels.filter((p) => {
    const q = searchTerm.toLowerCase();
    return (
      p.grid_id.toLowerCase().includes(q) ||
      (p.county_name ?? "").toLowerCase().includes(q) ||
      (p.cluster_label ?? "").toLowerCase().includes(q)
    );
  });

  const openWeights = () => {
    setWeightsOpen(true);
    setSheet("expanded");
  };

  /* ── Drag-to-resize (pointer events unify touch + mouse) ── */
  const onHandleDown = (e: React.PointerEvent) => {
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      // Pointer no longer active (edge/browser quirk) — drag still works via bubbling.
    }
    dragStart.current = { y: e.clientY, h: dragH ?? snapHeights()[sheet] };
    setDragH(dragStart.current.h);
  };

  const onHandleMove = (e: React.PointerEvent) => {
    if (!dragStart.current) return;
    const dy = dragStart.current.y - e.clientY; // up = grow
    if (Math.abs(dy) > 8) lastDragEnd.current = Number.MAX_SAFE_INTEGER;
    const max = Math.round(window.innerHeight * 0.92);
    setDragH(Math.min(max, Math.max(40, dragStart.current.h + dy)));
  };

  const onHandleUp = () => {
    if (!dragStart.current) return;
    const h = dragH ?? dragStart.current.h;
    const px = snapHeights();
    const nearest = (Object.keys(px) as SheetState[]).sort(
      (a, b) => Math.abs(h - px[a]) - Math.abs(h - px[b])
    )[0];
    dragStart.current = null;
    if (lastDragEnd.current === Number.MAX_SAFE_INTEGER) {
      lastDragEnd.current = Date.now();
    }
    setDragH(null);
    setSheet(nearest);
  };

  // While dragging up out of the minimized bar, reveal the full sheet body.
  const showFull = sheet !== "minimized" || (dragH !== null && dragH > 96);
  const handleProps = {
    onPointerDown: onHandleDown,
    onPointerMove: onHandleMove,
    onPointerUp: onHandleUp,
    onPointerCancel: onHandleUp,
  };

  return (
    <div className="lg:hidden">
      {/* ── Floating top chrome: masthead + search bar ── */}
      <div className="fixed inset-x-3 top-3 z-20 flex flex-col gap-2">
        {/* Masthead — product identity, always visible over the map */}
        <div className="flex h-9 shrink-0 items-center justify-between gap-2 rounded-[3px] border border-border-strong bg-surface/95 px-2.5 shadow-plate backdrop-blur">
          <div className="flex min-w-0 items-center gap-2">
            <BenchmarkMark size={18} />
            <h1 className="truncate font-display text-[15px] font-semibold leading-none tracking-tight text-foreground">
              Site Selection Engine
            </h1>
          </div>
          <span
            className="flex shrink-0 items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted"
            title={isLive ? "Connected to Supabase PostGIS" : "Using local demo dataset"}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                isLive ? "bg-success dark:bg-success-night" : "bg-warning dark:bg-power-night"
              }`}
            />
            {isLive ? "PostGIS" : "Demo"}
          </span>
        </div>

        <div className="flex items-center gap-2">
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
        {/* Region pill — cycles surveyed regions */}
        <div className="relative shrink-0">
          <select
            value={selectedRegion}
            onChange={(e) => onRegionChange(e.target.value)}
            aria-label="Select region"
            className="h-10 appearance-none rounded-[3px] border border-border-strong bg-surface/95 pl-2.5 pr-6 font-mono text-[11px] uppercase tracking-wide text-foreground shadow-plate backdrop-blur transition-colors focus:border-accent-600 focus:outline-none"
          >
            {REGIONS.map((region) => (
              <option
                key={region.code}
                value={region.code}
                disabled={!isSelectable(region.code)}
              >
                {region.short}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted" />
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
      </div>

      {/* ── Bottom sheet ─────────────────────────────────── */}
      <div
        style={dragH !== null ? { height: dragH, transitionProperty: "none" } : undefined}
        className={`fixed inset-x-0 bottom-0 z-30 flex flex-col overflow-hidden rounded-t-[6px] border-t border-border-strong bg-surface pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_24px_rgb(0_0_0/0.10)] transition-[height] duration-300 ease-out ${
          dragH !== null ? "" : sheet === "minimized" ? "h-[52px]" : sheet === "peek" ? "h-[36svh]" : "h-[78svh]"
        }`}
      >
        {showFull ? (
          <>
            {/* Grabber — drag to resize, tap to toggle peek/expanded */}
            <button
              {...handleProps}
              onClick={() => {
                if (tapAfterDrag()) return;
                setSheet(sheet === "expanded" ? "peek" : "expanded");
              }}
              aria-label={sheet === "expanded" ? "Collapse sheet" : "Expand sheet"}
              className="flex h-7 w-full shrink-0 touch-none select-none items-center justify-center"
            >
              <span className="h-1 w-10 rounded-full bg-border-strong" />
            </button>

            {/* Sheet head */}
            <div className="flex shrink-0 items-center justify-between gap-2 px-3 pb-1.5 pt-0.5">
              <h3 className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">
                Ranked Parcels
                <span className="ml-2 tabular-nums text-foreground">
                  {filteredParcels.length}
                </span>
              </h3>
              <div className="flex items-center gap-2">
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
              <LayerChips layers={layers} onToggleLayer={onToggleLayer} />
            </div>

            {/* Sheet body — scrolls in peek and expanded alike */}
            <div className="min-h-0 flex-1 overflow-hidden">
              {weightsOpen ? (
                <div className="scrollbar-hide h-full touch-pan-y overflow-y-auto overscroll-contain px-3 pb-4">
                  <ConstraintSliders
                    weights={weights}
                    onWeightChange={onWeightChange}
                    onResetWeights={onResetWeights}
                    primeThreshold={primeThreshold}
                    onPrimeThresholdChange={onPrimeThresholdChange}
                  />
                  <button
                    onClick={() => setWeightsOpen(false)}
                    className="mt-3 h-10 w-full border border-border-strong bg-background font-mono text-[10px] uppercase tracking-[0.14em] text-foreground transition-colors active:bg-surface-raised"
                  >
                    Done
                  </button>
                </div>
              ) : (
                <div className="scrollbar-hide h-full touch-pan-y overflow-y-auto overscroll-contain">
                  <ParcelCards
                    parcels={filteredParcels}
                    selectedId={selectedParcel?.id}
                    onSelect={onSelectParcel}
                  />
                </div>
              )}
            </div>
          </>
        ) : (
          /* Collapsed bar — drag up or tap to raise the sheet */
          <button
            {...handleProps}
            onClick={() => {
              if (tapAfterDrag()) return;
              setSheet("peek");
            }}
            aria-label="Show ranked parcels"
            className="flex h-[52px] w-full touch-none select-none items-center justify-between px-4"
          >
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted">
              Ranked Parcels
              <span className="ml-2 tabular-nums text-foreground">
                {filteredParcels.length}
              </span>
            </span>
            <ChevronUp className="h-4 w-4 text-muted" />
          </button>
        )}
      </div>
    </div>
  );
};
