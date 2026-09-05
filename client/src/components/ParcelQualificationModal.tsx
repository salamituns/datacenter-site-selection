"use client";

import React, { useEffect, useRef, useState } from "react";
import { LandParcel, ParcelQualification, GateStatus, ParcelPowerEvidence, PowerDocument } from "@/types/parcel";
import { fetchParcelPowerEvidence, fetchPowerDocuments } from "@/lib/supabase";
import { X, Download, ClipboardCheck, FlaskConical, Landmark, FileText, Zap } from "lucide-react";

interface ParcelQualificationModalProps {
  parcel: LandParcel | null;
  qualification: ParcelQualification | null;
  onClose: () => void;
}

const GATE_LABELS: Record<string, string> = {
  zoning_dc_use: "Zoning (data-center use)",
  contiguous_acreage: "Contiguous acreage",
  floodway: "Floodway / floodplain",
  wetlands: "Wetlands",
  slope: "Slope",
  protected_land: "Protected land",
  road_access: "Road access",
  power_capacity: "Power capacity evidence",
  water_availability: "Water availability",
};

function gateLabel(key: string): string {
  return GATE_LABELS[key] ?? key.replace(/_/g, " ");
}

/** Verdict chip — stamp-like, one ink per state; UNKNOWN reads as
 *  pending evidence rather than a negative. */
function StatusChip({ status }: { status: GateStatus }) {
  const styles: Record<GateStatus, string> = {
    PASS:
      "border-success/60 bg-success/10 text-success dark:border-success-night/50 dark:bg-success-night/10 dark:text-success-night",
    CONDITIONAL:
      "border-power/60 bg-power/10 text-power dark:border-power-night/50 dark:bg-power-night/10 dark:text-power-night",
    FAIL:
      "border-danger/60 bg-danger/10 text-danger dark:border-danger-night/50 dark:bg-danger-night/10 dark:text-danger-night",
    UNKNOWN: "border-border-strong bg-surface-raised text-muted",
  };
  return (
    <span
      className={`shrink-0 border px-1.5 py-0.5 font-mono text-[8.5px] uppercase tracking-[0.14em] ${styles[status]}`}
    >
      {status}
    </span>
  );
}

function fmtAcres(v: number | null): string {
  return v == null ? "Unverified" : `${Math.round(v).toLocaleString()} ac`;
}

type SheetState = "half" | "full";

function snapHeights(): Record<SheetState, number> {
  const vh = typeof window === "undefined" ? 0 : window.innerHeight;
  return { half: Math.round(vh * 0.62), full: Math.round(vh * 0.92) };
}

export const ParcelQualificationModal: React.FC<ParcelQualificationModalProps> = ({
  parcel,
  qualification,
  onClose,
}) => {
  const [dragH, setDragH] = useState<number | null>(null);
  const [sheet, setSheet] = useState<SheetState>("half");
  const dragStart = useRef<{ y: number; h: number } | null>(null);
  const lastDragEnd = useRef(0);
  const [documents, setDocuments] = useState<PowerDocument[]>([]);
  const [evidence, setEvidence] = useState<ParcelPowerEvidence[]>([]);

  useEffect(() => {
    if (parcel) setSheet("half");
  }, [parcel?.parcel_key]);

  // Utility documents behind the power-diligence evidence — loaded once
  // per open, small list, cached across parcels while the modal is up.
  useEffect(() => {
    if (!parcel || documents.length > 0) return;
    let alive = true;
    fetchPowerDocuments().then((docs) => {
      if (alive) setDocuments(docs);
    });
    return () => {
      alive = false;
    };
  }, [parcel, documents.length]);

  // Parcel-specific utility evidence — dated county records keyed to
  // this parcel (quoted verbatim; capacity only when the record states it).
  useEffect(() => {
    if (!parcel) return;
    let alive = true;
    setEvidence([]);
    fetchParcelPowerEvidence(parcel.parcel_key).then((rows) => {
      if (alive) setEvidence(rows);
    });
    return () => {
      alive = false;
    };
  }, [parcel?.parcel_key]);

  useEffect(() => {
    if (!parcel) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [parcel, onClose]);

  if (!parcel) return null;

  const gates = qualification?.gates ?? [];
  const metrics = qualification?.metrics ?? [];
  const unknownGates = gates.filter((g) => g.status === "UNKNOWN");

  const exportDossier = () => {
    const blob = new Blob(
      [JSON.stringify({ parcel, qualification }, null, 2)],
      { type: "application/json" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${parcel.pin}-qualification.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  /* ── Qualification body — shared by the desktop modal and mobile sheet ── */
  const body = (
    <>
      {/* Header */}
      <div className="flex items-start justify-between border-b border-border-strong px-4 py-4 lg:px-6">
        <div className="min-w-0">
          <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
            Parcel Qualification
          </div>
          <div className="mt-1 flex items-center gap-2.5">
            <h2 className="font-mono text-base font-medium tracking-tight text-foreground">
              PIN {parcel.pin}
            </h2>
            {parcel.overall_status && <StatusChip status={parcel.overall_status} />}
          </div>
          <p className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
            {parcel.county_name ?? "Unsurveyed"} County, {parcel.state_code} · GIS{" "}
            {fmtAcres(parcel.gis_acreage)} · Legal {fmtAcres(parcel.legal_acreage)}
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

      {/* Gates ledger — the decision layer */}
      <div className="px-4 py-5 lg:px-6">
        <h4 className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
          <ClipboardCheck className="h-3.5 w-3.5" />
          Gate Results
        </h4>
        <div className="mt-3 border-t border-border">
          {gates.length === 0 && (
            <div className="py-3 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
              No gates recorded for this parcel.
            </div>
          )}
          {gates.map((g) => (
            <div
              key={g.gate_key}
              className="border-b border-border/70 py-2.5"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-foreground">
                  {gateLabel(g.gate_key)}
                </span>
                <StatusChip status={g.status} />
              </div>
              {g.rationale && (
                <p className="mt-1 font-mono text-[10px] leading-relaxed text-muted">
                  {g.rationale}
                  {g.affected_area_pct != null && (
                    <span className="text-foreground">
                      {" "}
                      ({g.affected_area_pct.toFixed(1)}% of parcel affected)
                    </span>
                  )}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Metrics with provenance */}
      <div className="border-t border-border px-4 py-5 lg:px-6">
        <h4 className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
          <FlaskConical className="h-3.5 w-3.5" />
          Measured Values · Evidence &amp; Source
        </h4>
        <div className="mt-3 grid grid-cols-1 gap-x-10 gap-y-5 sm:grid-cols-2">
          <div>
            <dl className="border-t border-border">
              {metrics.slice(0, Math.ceil(metrics.length / 2)).map((m) => (
                <div
                  key={m.metric_key}
                  className="flex items-baseline justify-between gap-3 border-b border-border/70 py-1.5"
                >
                  <dt className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted">
                    {m.label ?? m.metric_key}
                  </dt>
                  <dd className="text-right font-mono text-[11px] tabular-nums text-foreground">
                    {m.value != null
                      ? `${Number(m.value).toLocaleString()}${m.unit === "percent" ? "%" : m.unit ? ` ${m.unit}` : ""}`
                      : m.text_value ?? "Unverified"}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
          <div>
            <dl className="border-t border-border">
              {metrics.slice(Math.ceil(metrics.length / 2)).map((m) => (
                <div
                  key={m.metric_key}
                  className="flex items-baseline justify-between gap-3 border-b border-border/70 py-1.5"
                >
                  <dt className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted">
                    {m.label ?? m.metric_key}
                  </dt>
                  <dd className="text-right font-mono text-[11px] tabular-nums text-foreground">
                    {m.value != null
                      ? `${Number(m.value).toLocaleString()}${m.unit === "percent" ? "%" : m.unit ? ` ${m.unit}` : ""}`
                      : m.text_value ?? "Unverified"}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
        {/* Evidence + source lineage line */}
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 font-mono text-[9px] uppercase tracking-[0.08em] text-muted">
          {metrics.map((m) => (
            <span key={m.metric_key} className="flex items-center gap-1.5">
              <span className="h-1 w-1 rounded-full bg-border-strong" />
              <span className="text-foreground">{m.label ?? m.metric_key}</span>
              <span>{m.evidence_class ?? "—"} · {m.source_organization ?? "no source"}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Parcel-specific utility evidence — dated county records */}
      {evidence.length > 0 && (
        <div className="border-t border-border bg-success/5 px-4 py-4 dark:bg-success-night/5 lg:px-6">
          <h4 className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
            <Zap className="h-3.5 w-3.5" />
            Parcel-Specific Utility Evidence · Dated County Record
          </h4>
          <ul className="mt-2 space-y-3">
            {evidence.map((e) => (
              <li key={`${e.parcel_key}-${e.application_number}`} className="font-mono text-[10px] leading-relaxed text-muted">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <a
                    href={e.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-foreground underline decoration-border-strong underline-offset-2 hover:decoration-foreground"
                  >
                    {e.application_type} {e.application_number}
                  </a>
                  <span>· County approval {e.approval_date}</span>
                  {e.utility && <span>· {e.utility}</span>}
                </div>
                <p className="mt-1 text-foreground/90">{e.utility_statement}</p>
                <p className="mt-1">
                  Source: {e.document_name} · {e.document_date} · public LandMARC record
                </p>
                {e.capacity_mw != null ? (
                  <p className="mt-1 text-foreground">
                    Documented capacity: {Number(e.capacity_mw).toLocaleString()} MW
                    {" "}— stated in the dated record, never derived.
                  </p>
                ) : (
                  <p className="mt-1">No MW figure is asserted — the record documents utility service.</p>
                )}
                {e.notes && <p className="mt-1">{e.notes}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Utility documents behind the power evidence */}
      {documents.length > 0 && (
        <div className="border-t border-border px-4 py-4 lg:px-6">
          <h4 className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
            <FileText className="h-3.5 w-3.5" />
            Utility Documents · Dated Sources
          </h4>
          <ul className="mt-2 space-y-2">
            {documents.map((d) => (
              <li key={d.doc_key} className="font-mono text-[10px] leading-relaxed text-muted">
                <a
                  href={d.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-foreground underline decoration-border-strong underline-offset-2 hover:decoration-foreground"
                >
                  {d.title}
                </a>
                {" — "}
                {d.publisher}
                {d.published_date && <> · as of {d.published_date}</>}
                {d.summary && <p className="mt-0.5">{d.summary}</p>}
              </li>
            ))}
          </ul>
          <p className="mt-2 font-mono text-[9px] uppercase tracking-[0.08em] text-muted">
            Capacity figures appear only with the dated document that supports them —
            zone-level forecasts are never parcel claims.
          </p>
        </div>
      )}

      {/* Unresolved diligence items */}
      {unknownGates.length > 0 && (
        <div className="border-t border-border bg-surface-raised/40 px-4 py-4 lg:px-6">
          <h4 className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
            <Landmark className="h-3.5 w-3.5" />
            Unresolved Diligence Items
          </h4>
          <ul className="mt-2 space-y-1">
            {unknownGates.map((g) => (
              <li
                key={g.gate_key}
                className="font-mono text-[10px] leading-relaxed text-muted"
              >
                <span className="text-foreground">{gateLabel(g.gate_key)}</span>
                {" — "}
                {g.rationale ?? "awaiting source data"}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Footer */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-strong px-4 py-4 lg:px-6">
        <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
          {qualification
            ? `${gates.length} gates · ${metrics.length} metrics · lineage via ingestion run`
            : "Loading qualification…"}
        </div>
        <button
          onClick={exportDossier}
          className="flex h-8 items-center gap-2 bg-foreground px-3 font-mono text-[10px] uppercase tracking-[0.14em] text-background transition-opacity hover:opacity-80"
        >
          <Download className="h-3.5 w-3.5" />
          Export qualification
        </button>
      </div>
    </>
  );

  /* ── Mobile sheet drag (pointer events unify touch + mouse) ── */
  const onHandleDown = (e: React.PointerEvent) => {
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      // Pointer no longer active — drag still works via bubbling.
    }
    dragStart.current = { y: e.clientY, h: dragH ?? snapHeights()[sheet] };
    setDragH(dragStart.current.h);
  };

  const onHandleMove = (e: React.PointerEvent) => {
    if (!dragStart.current) return;
    const dy = dragStart.current.y - e.clientY;
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
      {/* ── Desktop: centered modal ── */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Parcel ${parcel.pin} qualification`}
        onClick={onClose}
        className="fixed inset-0 z-50 hidden items-center justify-center bg-foreground/40 p-4 backdrop-blur-[2px] lg:flex"
      >
        <div
          onClick={(e) => e.stopPropagation()}
          className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-[3px] border border-border-strong bg-surface shadow-overlay"
        >
          {body}
        </div>
      </div>

      {/* ── Mobile: qualification as a draggable bottom sheet ── */}
      <div className="lg:hidden" role="dialog" aria-modal="true" aria-label={`Parcel ${parcel.pin} qualification`}>
        <div onClick={onClose} aria-hidden="true" className="fixed inset-0 z-40 bg-foreground/30" />
        <div
          style={dragH !== null ? { height: dragH, transitionProperty: "none" } : undefined}
          className={`fixed inset-x-0 bottom-0 z-[41] flex flex-col overflow-hidden rounded-t-[6px] border-t border-border-strong bg-surface pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_24px_rgb(0_0_0/0.10)] transition-[height] duration-300 ease-out ${
            dragH !== null ? "" : sheet === "half" ? "h-[62svh]" : "h-[92svh]"
          }`}
        >
          <button
            onPointerDown={onHandleDown}
            onPointerMove={onHandleMove}
            onPointerUp={onHandleUp}
            onPointerCancel={onHandleUp}
            onClick={() => {
              if (tapAfterDrag()) return;
              setSheet(sheet === "full" ? "half" : "full");
            }}
            aria-label={sheet === "full" ? "Shrink qualification sheet" : "Expand qualification sheet"}
            className="flex h-7 w-full shrink-0 touch-none select-none items-center justify-center"
          >
            <span className="h-1 w-10 rounded-full bg-border-strong" />
          </button>
          <div className="scrollbar-hide min-h-0 flex-1 touch-pan-y overflow-y-auto overscroll-contain">
            {body}
          </div>
        </div>
      </div>
    </>
  );
};
