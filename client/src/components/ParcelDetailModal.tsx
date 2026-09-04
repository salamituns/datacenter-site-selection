"use client";

import React, { useEffect, useRef, useState } from "react";
import { GridParcel } from "@/types/parcel";
import {
  X,
  Zap,
  Droplets,
  ShieldAlert,
  ThermometerSnowflake,
  Download,
  CheckCircle2,
} from "lucide-react";

interface ParcelDetailModalProps {
  parcel: GridParcel | null;
  onClose: () => void;
}

function scoreTier(score: number): string {
  if (score >= 82) return "Top tier";
  if (score >= 70) return "Strong";
  if (score >= 60) return "Moderate";
  return "Marginal";
}

type SheetState = "half" | "full";

/** Snap-point heights in px for the current viewport. */
function snapHeights(): Record<SheetState, number> {
  const vh = typeof window === "undefined" ? 0 : window.innerHeight;
  return {
    half: Math.round(vh * 0.62),
    full: Math.round(vh * 0.92),
  };
}

export const ParcelDetailModal: React.FC<ParcelDetailModalProps> = ({ parcel, onClose }) => {
  // Mobile sheet drag state (live px override while dragging, null when snapped)
  const [dragH, setDragH] = useState<number | null>(null);
  const [sheet, setSheet] = useState<SheetState>("half");
  const dragStart = useRef<{ y: number; h: number } | null>(null);
  // Suppresses the synthetic click that follows a real drag gesture.
  const lastDragEnd = useRef(0);
  // Reset the sheet position whenever a new dossier opens.
  useEffect(() => {
    if (parcel) setSheet("half");
  }, [parcel?.id]);

  useEffect(() => {
    if (!parcel) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [parcel, onClose]);

  if (!parcel) return null;

  // Null-aware display: a missing source value is shown as "Unverified"
  // — never a plausible-looking default.
  const fmt = (v: number | null, unit = ""): string =>
    v == null ? "Unverified" : `${v}${unit}`;
  const fastTrackEligible =
    parcel.seismic_hazard_pga != null &&
    parcel.seismic_hazard_pga < 0.08 &&
    parcel.power_distance_miles <= 2;

  const exportDossier = () => {
    const blob = new Blob([JSON.stringify(parcel, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${parcel.grid_id}-dossier.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const stats = [
    { label: "Composite", value: parcel.composite_score.toFixed(1), sub: scoreTier(parcel.composite_score) },
    {
      label: "Power",
      value: parcel.power_score != null ? parcel.power_score.toFixed(0) : "—",
      sub:
        parcel.substation_voltage_kv != null
          ? `${parcel.substation_voltage_kv} kV grid`
          : "voltage unverified",
    },
    {
      label: "Water",
      value: parcel.water_score != null ? parcel.water_score.toFixed(0) : "—",
      sub:
        parcel.groundwater_depth_ft != null
          ? `${parcel.groundwater_depth_ft} ft depth`
          : "depth unverified",
    },
    {
      label: "Capacity",
      value:
        parcel.megawatt_capacity_estimate != null
          ? `${parcel.megawatt_capacity_estimate}`
          : "—",
      sub: "MW area-derived est.",
    },
  ];

  const constraints = [
    {
      icon: <Zap className="h-3.5 w-3.5 dark:text-power-night" />,
      title: "Power Grid Proximity",
      rows: [
        { label: "115 kV+ line", value: `${parcel.power_distance_miles} mi` },
        { label: "Nearest substation", value: `${parcel.substation_distance_miles} mi` },
        { label: "Grid operator", value: parcel.grid_operator || "Unverified" },
      ],
    },
    {
      icon: <Droplets className="h-3.5 w-3.5 text-water dark:text-water-night" />,
      title: "Water Availability",
      rows: [
        { label: "Groundwater table", value: fmt(parcel.groundwater_depth_ft, " ft") },
        {
          label: "Availability index",
          value:
            parcel.water_availability_index != null
              ? `${parcel.water_availability_index}/100`
              : "Unverified",
        },
        { label: "Cooling mode", value: "Closed-loop capable" },
      ],
    },
    {
      icon: <ShieldAlert className="h-3.5 w-3.5 text-danger dark:text-danger-night" />,
      title: "Geological Risk",
      rows: [
        { label: "Seismic (PGA)", value: fmt(parcel.seismic_hazard_pga, "g") },
        { label: "FEMA flood risk", value: fmt(parcel.flood_risk_score, "/100") },
        { label: "Design threshold", value: "< 0.08g PGA" },
      ],
    },
    {
      icon: <ThermometerSnowflake className="h-3.5 w-3.5 text-muted" />,
      title: "Ambient Cooling",
      rows: [
        { label: "Cooling degree days", value: fmt(parcel.cooling_degree_days) },
        { label: "Economizer hours", value: fmt(parcel.free_cooling_potential_hours) },
        { label: "Mean ambient", value: fmt(parcel.ambient_avg_temp_f, "°F") },
      ],
    },
  ];

  /* ── Dossier body — shared by the desktop modal and the mobile sheet ── */
  const dossierBody = (
    <>
      {/* Dossier header */}
      <div className="flex items-start justify-between border-b border-border-strong px-4 py-4 lg:px-6">
        <div className="min-w-0">
          <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
            Site Dossier
          </div>
          <div className="mt-1 flex items-center gap-2.5">
            <h2 className="font-mono text-base font-medium tracking-tight text-foreground">
              {parcel.grid_id}
            </h2>
            {parcel.is_prime_zone && (
              <span className="border border-accent-600/60 bg-accent-600/10 px-1.5 py-0.5 font-mono text-[8.5px] uppercase tracking-[0.16em] text-accent-700 dark:border-accent-400/50 dark:bg-accent-400/10 dark:text-accent-300">
                Prime — {parcel.cluster_label ?? "Unclassified"}
              </span>
            )}
          </div>
          <p className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
            {parcel.county_name ?? "Unsurveyed county"} County, {parcel.state_code} · {parcel.area_sq_km.toFixed(1)} km²
            · {parcel.lat.toFixed(4)}N {Math.abs(parcel.lon).toFixed(4)}W
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="flex h-7 w-7 shrink-0 items-center justify-center border border-border-strong text-muted transition-colors hover:bg-surface-raised hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Key metrics — serif figures */}
      <div className="grid grid-cols-2 divide-x divide-border border-b border-border sm:grid-cols-4 sm:divide-x-1">
        {stats.map((stat, i) => (
          <div
            key={stat.label}
            className={`px-4 py-3.5 lg:px-5 ${i === 0 ? "" : "sm:border-l sm:border-border"} ${
              i >= 2 ? "border-t border-border sm:border-t-0" : ""
            }`}
          >
            <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-muted">
              {stat.label}
            </div>
            <div className="mt-1 font-display text-[26px] font-semibold leading-none text-foreground">
              {stat.value}
            </div>
            <div className="mt-1.5 font-mono text-[9.5px] uppercase tracking-[0.08em] text-muted">
              {stat.sub}
            </div>
          </div>
        ))}
      </div>

      {/* Constraint analysis — ledger tables */}
      <div className="px-4 py-5 lg:px-6">
        <h4 className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
          Constraint Analysis
        </h4>
        <div className="mt-3 grid grid-cols-1 gap-x-10 gap-y-5 sm:grid-cols-2">
          {constraints.map((group) => (
            <div key={group.title}>
              <div className="flex items-center gap-2 text-xs font-medium text-foreground">
                {group.icon}
                {group.title}
              </div>
              <dl className="mt-2 border-t border-border">
                {group.rows.map((row) => (
                  <div
                    key={row.label}
                    className="flex items-baseline justify-between gap-3 border-b border-border/70 py-1.5"
                  >
                    <dt className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted">
                      {row.label}
                    </dt>
                    <dd className="font-mono text-[11px] tabular-nums text-foreground">
                      {row.value}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-strong px-4 py-4 lg:px-6">
        <div
          className={`flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em] ${
            fastTrackEligible
              ? "text-success dark:text-success-night"
              : "text-muted"
          }`}
        >
          <CheckCircle2 className="h-3.5 w-3.5" />
          {fastTrackEligible
            ? "Fast-track interconnection profile"
            : "Standard interconnection review"}
        </div>
        <button
          onClick={exportDossier}
          className="flex h-8 items-center gap-2 bg-foreground px-3 font-mono text-[10px] uppercase tracking-[0.14em] text-background transition-opacity hover:opacity-80"
        >
          <Download className="h-3.5 w-3.5" />
          Export dossier
        </button>
      </div>
    </>
  );

  /* ── Mobile sheet drag (pointer events unify touch + mouse) ── */
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
    setDragH(Math.max(64, Math.min(snapHeights().full, dragStart.current.h + dy)));
  };

  const onHandleUp = () => {
    if (!dragStart.current) return;
    const h = dragH ?? dragStart.current.h;
    dragStart.current = null;
    if (lastDragEnd.current === Number.MAX_SAFE_INTEGER) {
      lastDragEnd.current = Date.now();
    }
    setDragH(null);
    const px = snapHeights();
    // A decisive downward pull dismisses; otherwise snap to the nearest state.
    if (h < px.half * 0.45) {
      onClose();
      return;
    }
    const nearest = (Object.keys(px) as SheetState[]).sort(
      (a, b) => Math.abs(h - px[a]) - Math.abs(h - px[b])
    )[0];
    setSheet(nearest);
  };

  const tapAfterDrag = () => Date.now() - lastDragEnd.current < 300;

  return (
    <>
      {/* ── Desktop: centered modal (lg and up, unchanged behavior) ── */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Parcel ${parcel.grid_id} details`}
        onClick={onClose}
        className="fixed inset-0 z-50 hidden items-center justify-center bg-foreground/40 p-4 backdrop-blur-[2px] lg:flex"
      >
        <div
          onClick={(e) => e.stopPropagation()}
          className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-[3px] border border-border-strong bg-surface shadow-overlay"
        >
          {dossierBody}
        </div>
      </div>

      {/* ── Mobile: dossier as a draggable bottom sheet ── */}
      <div className="lg:hidden" role="dialog" aria-modal="true" aria-label={`Parcel ${parcel.grid_id} details`}>
        <div
          onClick={onClose}
          aria-hidden="true"
          className="fixed inset-0 z-40 bg-foreground/30"
        />
        <div
          style={dragH !== null ? { height: dragH, transitionProperty: "none" } : undefined}
          className={`fixed inset-x-0 bottom-0 z-[41] flex flex-col overflow-hidden rounded-t-[6px] border-t border-border-strong bg-surface pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_24px_rgb(0_0_0/0.10)] transition-[height] duration-300 ease-out ${
            dragH !== null ? "" : sheet === "half" ? "h-[62svh]" : "h-[92svh]"
          }`}
        >
          {/* Grabber — drag to resize, pull down to dismiss, tap to toggle */}
          <button
            onPointerDown={onHandleDown}
            onPointerMove={onHandleMove}
            onPointerUp={onHandleUp}
            onPointerCancel={onHandleUp}
            onClick={() => {
              if (tapAfterDrag()) return;
              setSheet(sheet === "full" ? "half" : "full");
            }}
            aria-label={sheet === "full" ? "Shrink dossier sheet" : "Expand dossier sheet"}
            className="flex h-7 w-full shrink-0 touch-none select-none items-center justify-center"
          >
            <span className="h-1 w-10 rounded-full bg-border-strong" />
          </button>

          {/* Sheet body — scrolls internally, never chains to the map */}
          <div className="scrollbar-hide min-h-0 flex-1 touch-pan-y overflow-y-auto overscroll-contain">
            {dossierBody}
          </div>
        </div>
      </div>
    </>
  );
};
