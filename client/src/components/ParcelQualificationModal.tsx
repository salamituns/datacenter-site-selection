"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  LandParcel,
  ParcelQualification,
  ParcelGateRow,
  ParcelMetricRow,
  GateStatus,
  ParcelPowerEvidence,
  PowerDocument,
} from "@/types/parcel";
import { fetchParcelPowerEvidence, fetchPowerDocuments } from "@/lib/supabase";
import { X, Download, ChevronDown, ChevronUp } from "lucide-react";

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

/** Read order is actionability order: what blocks, then what is
 *  conditioned, then what is merely unproven, then what is settled. */
const STATUS_ORDER: Record<GateStatus, number> = {
  FAIL: 0,
  CONDITIONAL: 1,
  UNKNOWN: 2,
  PASS: 3,
};

/** One ink per verdict, drawn from the plat palette rather than the
 *  generic ramp. UNKNOWN is a dashed caliper rule — pending evidence,
 *  deliberately not a negative. */
const VERDICT_INK: Record<
  GateStatus,
  { rule: string; chip: string; tint: string; ink: string }
> = {
  FAIL: {
    rule: "border-l-danger dark:border-l-danger-night",
    chip: "border-danger dark:border-danger-night",
    tint: "bg-danger/[0.055] dark:bg-danger-night/[0.11]",
    ink: "text-danger dark:text-danger-night",
  },
  CONDITIONAL: {
    rule: "border-l-power dark:border-l-power-night",
    chip: "border-power dark:border-power-night",
    tint: "bg-power/[0.06] dark:bg-power-night/[0.11]",
    ink: "text-power dark:text-power-night",
  },
  UNKNOWN: {
    rule: "border-dashed border-l-border-strong",
    chip: "border-border-strong",
    tint: "bg-surface-raised/25",
    ink: "text-muted",
  },
  PASS: {
    rule: "border-l-success dark:border-l-success-night",
    chip: "border-success dark:border-success-night",
    tint: "",
    ink: "text-success dark:text-success-night",
  },
};

/** Verdict chip — an outline stamp, matching the bordered `Prime` chip
 *  used in the ranked list. `lg` is the header stamp on the plat. */
function StatusChip({ status, size = "sm" }: { status: GateStatus; size?: "sm" | "lg" }) {
  const { ink, chip } = VERDICT_INK[status];
  const box =
    size === "lg"
      ? "border-2 px-2.5 py-1 text-[13px] tracking-[0.2em]"
      : "border px-1.5 py-px text-[8.5px] tracking-[0.14em]";
  return (
    <span className={`shrink-0 font-mono font-semibold uppercase ${box} ${chip} ${ink}`}>
      {status}
    </span>
  );
}

function fmtAcres(v: number | null): string {
  return v == null ? "Unverified" : `${Math.round(v).toLocaleString()} ac`;
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

/** Names at most two gates and defers the rest. A parcel failing six
 *  gates still has to produce a sentence, not a paragraph — the list in
 *  full belongs to the rows below, which are already sorted to match. */
function nameGates(gates: ParcelGateRow[]): string {
  const names = gates.map((g) => gateLabel(g.gate_key).toLowerCase()).sort();
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  const rest = names.length - 2;
  return `${names[0]}, ${names[1]}, and ${rest} more ${plural(rest, "gate", "gates")}`;
}

/**
 * The single sentence under the PIN — the whole point of the header.
 * It answers "can I build here, and what is stopping me" before the
 * reader touches the gate list.
 *
 * A parcel with no failing gate but several UNKNOWN ones is deliberately
 * not called "clear": absent evidence is reported as absent rather than
 * rounded up to a pass, matching how a null metric renders "Unverified".
 */
function verdictSummary(gates: ParcelGateRow[]): string {
  if (gates.length === 0) return "No gates recorded for this parcel.";

  const failed = gates.filter((g) => g.status === "FAIL");
  const conditional = gates.filter((g) => g.status === "CONDITIONAL");
  const unknown = gates.filter((g) => g.status === "UNKNOWN");

  if (failed.length > 0) {
    return `Disqualified on ${nameGates(failed)}.`;
  }
  if (conditional.length > 0 && unknown.length > 0) {
    return `Conditionally viable — ${conditional.length} ${plural(
      conditional.length,
      "gate carries a condition",
      "gates carry conditions"
    )}, ${unknown.length} ${plural(unknown.length, "item", "items")} awaiting evidence.`;
  }
  if (conditional.length > 0) {
    return `Conditionally viable — ${conditional.length} ${plural(
      conditional.length,
      "gate carries a condition",
      "gates carry conditions"
    )}.`;
  }
  if (unknown.length > 0) {
    return `Nothing blocking, but ${unknown.length} ${plural(
      unknown.length,
      "gate is",
      "gates are"
    )} still awaiting source evidence.`;
  }
  return `Clear on all ${gates.length} gates.`;
}

/**
 * Which shell to render. The desktop modal and the mobile sheet are
 * mutually exclusive, so only one is built: rendering both and hiding
 * one with CSS still puts it in the DOM, which duplicated every gate
 * row and left two aria-modal dialogs in the accessibility tree.
 * null until mounted — the modal is an overlay, so nothing is lost.
 */
function useIsDesktop(): boolean | null {
  const [isDesktop, setIsDesktop] = useState<boolean | null>(null);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const sync = () => setIsDesktop(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return isDesktop;
}

/**
 * Moves focus into the dialog on open, keeps Tab inside it, and returns
 * focus to whatever opened it on close — the map polygon, usually.
 *
 * onClose is held in a ref rather than listed as a dependency: callers
 * pass an inline arrow, so a new identity arrives on every parent render
 * and a dependency would tear the trap down and re-run it each time,
 * re-capturing the opener as the dialog itself.
 */
function useFocusTrap(active: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!active) return;
    openerRef.current = document.activeElement as HTMLElement | null;
    const node = ref.current;
    node?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !node) return;
      const focusable = node.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      // The opener can be gone — the map redraws its polygons on
      // selection change — so only restore a node still in the document.
      const opener = openerRef.current;
      if (opener && document.contains(opener)) opener.focus?.();
    };
  }, [active]);

  return ref;
}

type SheetState = "half" | "full";

function snapHeights(): Record<SheetState, number> {
  const vh = typeof window === "undefined" ? 0 : window.innerHeight;
  return { half: Math.round(vh * 0.62), full: Math.round(vh * 0.92) };
}

/* ── Section rule — the only heading treatment, no decorative icon ── */
function SectionRule({ label, aside }: { label: string; aside?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border pb-1.5">
      <h4 className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted">{label}</h4>
      {aside && (
        <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.1em] tabular-nums text-muted">
          {aside}
        </span>
      )}
    </div>
  );
}

/* ── A gate, at full weight — left verdict rule, tinted field ── */
function BlockingGateRow({ gate }: { gate: ParcelGateRow }) {
  const { rule, tint } = VERDICT_INK[gate.status];
  return (
    <div className={`border border-border/60 border-l-[3px] ${rule} ${tint} px-4 py-3.5`}>
      <div className="flex items-start justify-between gap-3">
        <span className="font-mono text-[11.5px] font-semibold leading-snug text-foreground">
          {gateLabel(gate.gate_key)}
        </span>
        <StatusChip status={gate.status} />
      </div>
      {gate.rationale && (
        <p className="mt-2 max-w-prose font-sans text-[12px] leading-[1.55] text-muted">
          {gate.rationale}
        </p>
      )}
      {gate.affected_area_pct != null && (
        <div className="mt-2.5 flex items-baseline justify-between gap-3 border-t border-border/50 pt-2">
          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-muted">
            Parcel area affected
          </span>
          <span className="font-mono text-[11px] font-semibold tabular-nums text-foreground">
            {gate.affected_area_pct.toFixed(1)}%
          </span>
        </div>
      )}
    </div>
  );
}

/* ── A settled gate, at ledger weight — name, verdict, nothing else ── */
function PassedGateRow({ gate }: { gate: ParcelGateRow }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-4 py-2.5">
      <span className="font-mono text-[11px] text-foreground/80">{gateLabel(gate.gate_key)}</span>
      <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.14em] text-success dark:text-success-night">
        Pass
      </span>
    </div>
  );
}

/* ── A measured value carries its own provenance — no second table.
 *    Numeric readings sit inline against a right-aligned figure; a long
 *    text value (a utility name, a date range) stacks instead, so the
 *    label and the value stop competing for the same line. ── */
function MetricRow({ metric }: { metric: ParcelMetricRow }) {
  const value =
    metric.value != null
      ? `${Number(metric.value).toLocaleString()}${
          metric.unit === "percent" ? "%" : metric.unit ? ` ${metric.unit}` : ""
        }`
      : metric.text_value ?? "Unverified";
  const source = [metric.evidence_class, metric.source_organization].filter(Boolean).join(" · ");
  const unrecorded = metric.value == null && !metric.text_value;
  const stacked = metric.value == null && (metric.text_value?.length ?? 0) > 16;

  const label = (
    <div className="font-mono text-[10.5px] uppercase leading-snug tracking-[0.06em] text-foreground">
      {metric.label ?? metric.metric_key}
    </div>
  );
  // Provenance wraps rather than truncating — a hidden source is worse
  // than a second line.
  const lineage = (
    <div className="mt-0.5 font-mono text-[9px] uppercase leading-snug tracking-[0.08em] text-muted">
      {source || "no source recorded"}
    </div>
  );
  const figure = (
    <div
      className={`font-mono text-[12px] leading-snug tabular-nums ${
        unrecorded ? "text-muted" : "text-foreground"
      }`}
    >
      {value}
    </div>
  );

  if (stacked) {
    return (
      <div className="border-b border-border/60 py-2.5">
        {label}
        <div className="mt-1">{figure}</div>
        {lineage}
      </div>
    );
  }

  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border/60 py-2.5">
      <div className="min-w-0">
        {label}
        {lineage}
      </div>
      <div className="shrink-0 text-right">{figure}</div>
    </div>
  );
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

  type TabKey = "gate_results" | "measured_values" | "utility_documents";
  const [activeTab, setActiveTab] = useState<TabKey>("gate_results");
  const [passAccordionOpen, setPassAccordionOpen] = useState(false);

  const isDesktop = useIsDesktop();
  // Escape now lives in the trap, alongside the rest of the key handling.
  const dialogRef = useFocusTrap(Boolean(parcel), onClose);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (parcel) {
      setSheet("half");
      setActiveTab("gate_results");
      setPassAccordionOpen(false);
    }
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

  if (!parcel) return null;

  const gates = qualification?.gates ?? [];
  const metrics = qualification?.metrics ?? [];

  const sortedGates = [...gates].sort((a, b) => {
    const byStatus = (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99);
    return byStatus !== 0 ? byStatus : gateLabel(a.gate_key).localeCompare(gateLabel(b.gate_key));
  });

  const attentionGates = sortedGates.filter((g) => g.status !== "PASS");
  const passedGates = sortedGates.filter((g) => g.status === "PASS");

  const exportDossier = () => {
    const blob = new Blob([JSON.stringify({ parcel, qualification }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${parcel.pin}-qualification.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: "gate_results", label: "Gates", count: gates.length },
    { key: "measured_values", label: "Measured", count: metrics.length },
    { key: "utility_documents", label: "Evidence", count: documents.length + evidence.length },
  ];

  /* ── Qualification body — shared by the desktop modal and mobile sheet ── */
  const body = (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* ── Masthead: PIN and verdict carry the page ── */}
      <div className="sticky top-0 z-20 shrink-0 border-b border-border-strong bg-surface/95 backdrop-blur">
        <div className="px-4 pb-3 pt-4 lg:px-6 lg:pt-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
              <h2 className="font-mono text-[26px] font-bold leading-none tracking-tight text-foreground lg:text-[32px]">
                {parcel.pin}
              </h2>
              {parcel.overall_status && <StatusChip status={parcel.overall_status} size="lg" />}
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="flex h-7 w-7 shrink-0 items-center justify-center border border-border-strong text-muted transition-colors hover:bg-surface-raised hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* The sentence that replaces reading the list */}
          <p className="mt-2.5 max-w-prose font-display text-[15px] leading-snug text-foreground lg:text-base">
            {qualification ? verdictSummary(gates) : "Loading qualification…"}
          </p>

          <p className="mt-2 font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted">
            {parcel.county_name ?? "Unsurveyed"} County, {parcel.state_code}
            {" · "}GIS {fmtAcres(parcel.gis_acreage)}
            {" · "}Legal {fmtAcres(parcel.legal_acreage)}
          </p>
        </div>

        {/* Segmented tabs — inverted ink for the active plate.
            Roving tabindex: the tablist is one tab stop, arrows move
            between the tabs inside it (WAI-ARIA tabs pattern). */}
        <div
          role="tablist"
          aria-label="Qualification sections"
          className="mx-4 mb-3 flex border border-border-strong lg:mx-6"
          onKeyDown={(e) => {
            const i = tabs.findIndex((t) => t.key === activeTab);
            let next = i;
            if (e.key === "ArrowRight") next = (i + 1) % tabs.length;
            else if (e.key === "ArrowLeft") next = (i - 1 + tabs.length) % tabs.length;
            else if (e.key === "Home") next = 0;
            else if (e.key === "End") next = tabs.length - 1;
            else return;
            e.preventDefault();
            setActiveTab(tabs[next].key);
            tabRefs.current[next]?.focus();
          }}
        >
          {tabs.map((tab, i) => {
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                ref={(el) => {
                  tabRefs.current[i] = el;
                }}
                role="tab"
                id={`qual-tab-${tab.key}`}
                aria-selected={isActive}
                aria-controls={`qual-panel-${tab.key}`}
                tabIndex={isActive ? 0 : -1}
                onClick={() => setActiveTab(tab.key)}
                className={`flex-1 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] transition-colors ${
                  isActive
                    ? "bg-foreground text-background"
                    : "text-muted hover:bg-surface-raised/60 hover:text-foreground"
                } ${i > 0 ? "border-l border-border-strong" : ""}`}
              >
                {tab.label} · {tab.count}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* ── Gates ── */}
        {activeTab === "gate_results" && (
          <div
            role="tabpanel"
            id="qual-panel-gate_results"
            aria-labelledby="qual-tab-gate_results"
            tabIndex={0}
            className="px-4 py-4 lg:px-6 lg:py-5"
          >
            <SectionRule
              label="Gate results · by actionability"
              aside={
                gates.length === 0
                  ? undefined
                  : `${attentionGates.length} open · ${passedGates.length} passed`
              }
            />

            {gates.length === 0 ? (
              <p className="py-4 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
                No gates recorded for this parcel.
              </p>
            ) : (
              <div className="mt-3.5 space-y-2.5">
                {attentionGates.map((g) => (
                  <BlockingGateRow key={g.gate_key} gate={g} />
                ))}

                {attentionGates.length === 0 && (
                  <p className="border border-dashed border-border-strong px-4 py-3.5 font-sans text-[12px] leading-[1.55] text-muted">
                    Nothing outstanding. Every gate on this parcel is settled.
                  </p>
                )}

                {passedGates.length > 0 && (
                  <div className="border border-border-strong">
                    <button
                      onClick={() => setPassAccordionOpen((prev) => !prev)}
                      aria-expanded={passAccordionOpen}
                      className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left font-mono text-[10px] uppercase tracking-[0.12em] text-muted transition-colors hover:bg-surface-raised/60 hover:text-foreground"
                    >
                      <span>
                        {passAccordionOpen ? "Hide" : "View"} {passedGates.length} passed criteria
                      </span>
                      {passAccordionOpen ? (
                        <ChevronUp className="h-3.5 w-3.5 shrink-0" />
                      ) : (
                        <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                      )}
                    </button>
                    {passAccordionOpen && (
                      <div className="divide-y divide-border/60 border-t border-border-strong">
                        {passedGates.map((g) => (
                          <PassedGateRow key={g.gate_key} gate={g} />
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Measured values (each row carries its own lineage) ── */}
        {activeTab === "measured_values" && (
          <div
            role="tabpanel"
            id="qual-panel-measured_values"
            aria-labelledby="qual-tab-measured_values"
            tabIndex={0}
            className="px-4 py-4 lg:px-6 lg:py-5"
          >
            <SectionRule
              label="Measured values"
              aside={metrics.length ? `${metrics.length} recorded` : undefined}
            />
            {metrics.length === 0 ? (
              <p className="py-4 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
                No measurements recorded for this parcel.
              </p>
            ) : (
              <>
                <div className="mt-1 grid grid-cols-1 gap-x-10 sm:grid-cols-2">
                  {[
                    metrics.slice(0, Math.ceil(metrics.length / 2)),
                    metrics.slice(Math.ceil(metrics.length / 2)),
                  ].map((column, i) => (
                    <div key={i}>
                      {column.map((m) => (
                        <MetricRow key={m.metric_key} metric={m} />
                      ))}
                    </div>
                  ))}
                </div>
                <p className="mt-4 max-w-prose font-sans text-[11.5px] leading-[1.55] text-muted">
                  Each value is shown with the evidence class and organisation it came from.
                  Where a source recorded nothing, the row reads <em>Unverified</em> — no
                  default is substituted.
                </p>
              </>
            )}
          </div>
        )}

        {/* ── Evidence ── */}
        {activeTab === "utility_documents" && (
          <div
            role="tabpanel"
            id="qual-panel-utility_documents"
            aria-labelledby="qual-tab-utility_documents"
            tabIndex={0}
            className="px-4 py-4 lg:px-6 lg:py-5"
          >
            {evidence.length > 0 && (
              <div className="mb-6">
                <SectionRule
                  label="Parcel-specific evidence · dated county record"
                  aside={`${evidence.length}`}
                />
                <ul className="mt-3 space-y-2.5">
                  {evidence.map((e) => (
                    <li
                      key={`${e.parcel_key}-${e.application_number}`}
                      className="border border-border/60 border-l-[3px] border-l-success bg-success/[0.05] px-4 py-3.5 dark:border-l-success-night dark:bg-success-night/[0.07]"
                    >
                      <div className="flex flex-wrap items-baseline gap-x-2 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
                        <a
                          href={e.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[11px] font-semibold tracking-[0.06em] text-foreground underline decoration-border-strong underline-offset-2 hover:decoration-foreground"
                        >
                          {e.application_type} {e.application_number}
                        </a>
                        <span>· approved {e.approval_date}</span>
                        {e.utility && <span className="text-foreground">· {e.utility}</span>}
                      </div>
                      <p className="mt-2 max-w-prose font-sans text-[12px] leading-[1.55] text-foreground/90">
                        {e.utility_statement}
                      </p>
                      {e.capacity_mw != null ? (
                        <div className="mt-2.5 flex items-baseline justify-between gap-3 border-t border-border/50 pt-2">
                          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-muted">
                            Documented capacity · stated, never derived
                          </span>
                          <span className="font-mono text-[11px] font-semibold tabular-nums text-foreground">
                            {Number(e.capacity_mw).toLocaleString()} MW
                          </span>
                        </div>
                      ) : (
                        <p className="mt-2 font-mono text-[9.5px] uppercase tracking-[0.08em] text-muted">
                          No MW figure asserted — the record documents service only
                        </p>
                      )}
                      <p className="mt-2 font-mono text-[9px] uppercase tracking-[0.08em] text-muted">
                        {e.document_name} · {e.document_date} · public LandMARC record
                      </p>
                      {e.notes && (
                        <p className="mt-1.5 max-w-prose font-sans text-[11.5px] leading-[1.5] text-muted">
                          {e.notes}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <SectionRule
              label="Regional utility documents"
              aside={documents.length ? `${documents.length}` : undefined}
            />
            {documents.length === 0 ? (
              <p className="py-4 max-w-prose font-sans text-[12px] leading-[1.55] text-muted">
                No regional utility documents are currently registered for this jurisdiction.
              </p>
            ) : (
              <ul className="mt-3 space-y-2.5">
                {documents.map((d) => (
                  <li key={d.doc_key} className="border border-border px-4 py-3.5">
                    <a
                      href={d.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-[11px] font-semibold text-foreground underline decoration-border-strong underline-offset-2 hover:decoration-foreground"
                    >
                      {d.title}
                    </a>
                    <div className="mt-1 font-mono text-[9px] uppercase tracking-[0.08em] text-muted">
                      {d.publisher}
                      {d.published_date && <> · as of {d.published_date}</>}
                    </div>
                    {d.summary && (
                      <p className="mt-2 max-w-prose font-sans text-[12px] leading-[1.55] text-muted">
                        {d.summary}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <p className="mt-5 max-w-prose border-t border-border pt-3 font-sans text-[11.5px] leading-[1.55] text-muted">
              Capacity figures appear only alongside the dated document that supports them.
              Zone-level forecasts are never restated as parcel claims.
            </p>
          </div>
        )}
      </div>

      {/* ── Footer ── */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-border-strong px-4 py-3 lg:px-6">
        <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-muted">
          {qualification
            ? `${gates.length} gates · ${metrics.length} metrics · lineage via ingestion run`
            : "Loading qualification…"}
        </div>
        <button
          onClick={exportDossier}
          className="flex h-7 items-center gap-2 bg-foreground px-3 font-mono text-[10px] uppercase tracking-[0.14em] text-background transition-opacity hover:opacity-80"
        >
          <Download className="h-3 w-3" />
          Export
        </button>
      </div>
    </div>
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

  // One shell or the other, never both — see useIsDesktop. Before the
  // media query resolves there is nothing to show.
  if (isDesktop === null) return null;

  const dialogLabel = `Parcel ${parcel.pin} qualification dossier`;

  /* ── Desktop: centered modal ── */
  if (isDesktop) {
    return (
      <div
        onClick={onClose}
        className="fixed inset-0 z-[1000] flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-[2px]"
      >
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-label={dialogLabel}
          tabIndex={-1}
          onClick={(e) => e.stopPropagation()}
          className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-[3px] border border-border-strong bg-surface shadow-overlay outline-none"
        >
          {body}
        </div>
      </div>
    );
  }

  /* ── Mobile: qualification as a draggable bottom sheet ── */
  return (
    <>
      <div onClick={onClose} aria-hidden="true" className="fixed inset-0 z-[1000] bg-foreground/30" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        tabIndex={-1}
        style={dragH !== null ? { height: dragH, transitionProperty: "none" } : undefined}
        className={`fixed inset-x-0 bottom-0 z-[1001] flex flex-col overflow-hidden rounded-t-[6px] border-t border-border-strong bg-surface pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_24px_rgb(0_0_0/0.10)] outline-none transition-[height] duration-300 ease-out ${
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
    </>
  );
};
