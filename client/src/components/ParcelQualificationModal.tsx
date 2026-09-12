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
import { X, Download, ChevronDown, ChevronUp, Scale, Info } from "lucide-react";
import { DecisionPanel } from "@/components/DecisionPanel";

interface ParcelQualificationModalProps {
  parcel: LandParcel | null;
  qualification: ParcelQualification | null;
  onClose: () => void;
  /**
   * Where to send focus on close when the element that opened the dialog
   * is gone by then. Clicking a parcel changes the selection, which makes
   * the map rebuild every polygon, so the clicked path is detached before
   * the dialog has finished opening and cannot be focused. Point this at
   * a container that outlives the selection — the map wrapper — and a
   * keyboard user lands back where they were instead of at the page top.
   */
  returnFocusTo?: React.RefObject<HTMLElement | null>;
  /** Whether this parcel is already on the shortlist. */
  isShortlisted?: boolean;
  /** Omitted where shortlisting does not apply — the control then hides
   *  rather than rendering as a dead button. */
  onToggleShortlist?: () => void;
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
  moratorium_status: "Moratorium / restriction",
};

export function gateLabel(key: string): string {
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

/** Centroid formatting, hemisphere-suffixed rather than signed — four
 *  decimals is ~11 m, which locates a parcel without implying a surveyed
 *  point. The centroid is derived from the parcel polygon, so it is a
 *  position on the parcel, not an address. */
function fmtLat(lat: number): string {
  return `${Math.abs(lat).toFixed(4)}${lat >= 0 ? "N" : "S"}`;
}

function fmtLon(lon: number): string {
  return `${Math.abs(lon).toFixed(4)}${lon >= 0 ? "E" : "W"}`;
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
 * Focuses a node if it is still in the document. A plain container has no
 * tabindex and cannot take focus, so one is added: -1 keeps it out of the
 * tab order while allowing focus to be moved there programmatically.
 */
function focusIfPresent(el: HTMLElement | null): boolean {
  if (!el || el === document.body || !document.contains(el)) return false;
  if (!el.hasAttribute("tabindex") && el.tabIndex < 0) {
    el.setAttribute("tabindex", "-1");
  }
  el.focus();
  return document.activeElement === el;
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
function useFocusTrap(
  active: boolean,
  onClose: () => void,
  returnFocusTo?: React.RefObject<HTMLElement | null>,
  trapTab: boolean = true
) {
  const ref = useRef<HTMLDivElement | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const returnRef = useRef(returnFocusTo);
  onCloseRef.current = onClose;
  returnRef.current = returnFocusTo;

  useEffect(() => {
    if (!active) return;
    // body is what activeElement reports when nothing is really focused —
    // clicking an SVG map path does not focus it — and it is not an opener
    // worth restoring to, so record none and let the caller's anchor win.
    const active_ = document.activeElement as HTMLElement | null;
    openerRef.current =
      active_ && active_ !== document.body && active_ !== document.documentElement
        ? active_
        : null;
    const node = ref.current;
    node?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      // Tab is deliberately not intercepted. The panel sits alongside a
      // live map rather than over an inert page, so the reader has to be
      // able to leave it.
      if (!trapTab || e.key !== "Tab" || !node) return;
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
      // Prefer the opener, fall back to the caller's anchor. Either can
      // be gone — the map redraws its polygons on selection change — so
      // only a node still in the document is focused.
      focusIfPresent(openerRef.current) ||
        focusIfPresent(returnRef.current?.current ?? null);
    };
  }, [active, trapTab]);

  return ref;
}

type SheetState = "half" | "full";

function snapHeights(): Record<SheetState, number> {
  const vh = typeof window === "undefined" ? 0 : window.innerHeight;
  return { half: Math.round(vh * 0.62), full: Math.round(vh * 0.92) };
}

/* ── Section rule — the only heading treatment, no decorative icon ── */
/** A heading, not a rule. At this weight and tracking the type already
 *  separates sections; a border under it was belt and braces. */
function SectionRule({ label, aside }: { label: string; aside?: string }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4">
      <h4 className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted">{label}</h4>
      {aside && (
        <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.1em] tabular-nums text-muted">
          {aside}
        </span>
      )}
    </div>
  );
}

/* ══ Bento primitives ══════════════════════════════════════════════════
   Separation comes from space and type weight, not rules. The palette is
   the project's own tokens rather than a fixed slate ramp, because this
   surface has to survive the blueprint night theme as well as paper. ── */

function Card({ children, span = "", label, info }: {
  children: React.ReactNode; span?: string; label?: string; info?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className={`relative rounded-xl bg-surface-raised/40 p-5 ${span}`}>
      {(label || info) && (
        <header className="mb-3 flex items-start justify-between gap-2">
          {label && (
            <h4 className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted">
              {label}
            </h4>
          )}
          {info && (
            <button
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              aria-label={open ? "Hide detail" : "Show detail"}
              className={`-mt-1 -mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition-colors ${
                open ? "bg-foreground/10 text-foreground" : "text-muted hover:text-foreground"
              }`}
            >
              <Info className="h-3.5 w-3.5" />
            </button>
          )}
        </header>
      )}
      {children}
      {/* Provenance is disclosed, never dropped: the reader can always get
          back to where a number came from, it just no longer competes with
          the number itself for attention. */}
      {info && open && (
        <div className="mt-4 border-t border-border/50 pt-3 font-sans text-[11.5px] leading-[1.55] text-muted">
          {info}
        </div>
      )}
    </section>
  );
}

/** A number that reads first, with its name underneath in a quieter voice. */
function Stat({ value, label, sub, tone = "default" }: {
  value: React.ReactNode; label: string; sub?: string;
  tone?: "default" | "danger" | "warn" | "good" | "muted";
}) {
  const ink = {
    default: "text-foreground",
    danger: "text-danger dark:text-danger-night",
    warn: "text-power dark:text-power-night",
    good: "text-success dark:text-success-night",
    muted: "text-muted",
  }[tone];
  return (
    <div>
      <div className={`font-mono text-[22px] font-semibold leading-none tabular-nums ${ink}`}>
        {value}
      </div>
      <div className="mt-1.5 font-mono text-[9.5px] uppercase tracking-[0.12em] text-muted">
        {label}
      </div>
      {sub && (
        <div className="mt-0.5 font-sans text-[11px] leading-snug text-muted">{sub}</div>
      )}
    </div>
  );
}

/**
 * A thin proportion bar. Reads as telemetry rather than a table cell, and
 * shows an absent measurement as an empty track rather than a zero one —
 * nothing measured and none present are different findings.
 */
function Bar({ label, pct, tone = "neutral", suffix = "%" }: {
  label: string; pct: number | null;
  tone?: "neutral" | "danger" | "warn" | "good"; suffix?: string;
}) {
  const fill = {
    neutral: "bg-foreground/40",
    danger: "bg-danger dark:bg-danger-night",
    warn: "bg-power dark:bg-power-night",
    good: "bg-success dark:bg-success-night",
  }[tone];
  const width = pct == null ? 0 : Math.max(1.5, Math.min(100, pct));
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
          {label}
        </span>
        <span className={`font-mono text-[11.5px] tabular-nums ${
          pct == null ? "text-muted" : "text-foreground"
        }`}>
          {pct == null ? "not measured" : `${pct.toFixed(1)}${suffix}`}
        </span>
      </div>
      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-foreground/[0.07]">
        {pct != null && (
          <div className={`h-full rounded-full ${fill}`} style={{ width: `${width}%` }} />
        )}
      </div>
    </div>
  );
}

function Dot({ status }: { status: GateStatus }) {
  const tone = {
    PASS: "bg-success dark:bg-success-night",
    CONDITIONAL: "bg-power dark:bg-power-night",
    FAIL: "bg-danger dark:bg-danger-night",
    UNKNOWN: "bg-border-strong",
  }[status];
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${tone}`} aria-hidden="true" />;
}

function Pill({ tone, children }: {
  tone: "danger" | "warn" | "good" | "muted"; children: React.ReactNode;
}) {
  const cls = {
    danger: "bg-danger/12 text-danger dark:bg-danger-night/15 dark:text-danger-night",
    warn: "bg-power/12 text-power dark:bg-power-night/15 dark:text-power-night",
    good: "bg-success/12 text-success dark:bg-success-night/15 dark:text-success-night",
    muted: "bg-foreground/[0.06] text-muted",
  }[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] ${cls}`}>
      {children}
    </span>
  );
}


/* ══ Overview — the at-a-glance layer ══════════════════════════════════
   Everything here answers "should I keep reading". The gate list, the
   full measurement table and the source documents stay one tab away
   rather than on the page: 55 metrics is a reference, not a briefing. ── */

/**
 * "2025-12-31..2032-06-01" is a machine range, and at headline size it
 * wraps to three lines and pushes the rest of its card off screen. The
 * window is what matters at a glance, not the days.
 */
function fmtWindow(range: string | null): string | null {
  if (!range) return null;
  const [from, to] = range.split("..");
  const month = (d?: string) => {
    if (!d) return null;
    const t = new Date(d);
    return isNaN(t.getTime())
      ? d
      : t.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
  };
  const a = month(from), b = month(to);
  return a && b ? `${a} – ${b}` : a ?? b ?? range;
}

function OverviewPanel({ parcel, gates, metrics }: {
  parcel: LandParcel; gates: ParcelGateRow[]; metrics: ParcelMetricRow[];
}) {
  const num = (k: string): number | null => {
    const v = metrics.find((m) => m.metric_key === k)?.value;
    return v == null ? null : Number(v);
  };
  const text = (k: string): string | null =>
    metrics.find((m) => m.metric_key === k)?.text_value ?? null;

  const failed = gates.filter((g) => g.status === "FAIL");
  const conditional = gates.filter((g) => g.status === "CONDITIONAL");
  const unknown = gates.filter((g) => g.status === "UNKNOWN");

  const acres = num("total_acreage");
  const developable = num("contiguous_developable_acreage");
  const land = num("assessed_land_value_usd");
  const rollback = num("land_use_rollback_tax_usd");
  const prepLo = num("site_prep_cost_low_usd");
  const prepHi = num("site_prep_cost_high_usd");
  const entryLo = [land, rollback, prepLo].every((v) => v != null)
    ? land! + rollback! + prepLo! : null;
  const entryHi = entryLo != null && prepHi != null ? land! + rollback! + prepHi! : null;

  const latency = num("ixp_latency_floor_ms");
  const peers = num("ixp_best_facility_networks_within_25mi");
  const slipP90 = num("rtep_area_schedule_slip_p90_days");

  const usd = (v: number | null) =>
    v == null ? "—"
      : Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(1)}M`
      : Math.abs(v) >= 1e3 ? `$${(v / 1e3).toFixed(0)}k` : `$${v.toFixed(0)}`;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-6">
      {/* Verdict — the only card that is never absent */}
      <Card span="lg:col-span-3" label="Verdict">
        <div className="flex flex-wrap items-center gap-2">
          {failed.length > 0
            ? <Pill tone="danger">{failed.length} blocking</Pill>
            : <Pill tone="good">nothing blocking</Pill>}
          {conditional.length > 0 && <Pill tone="warn">{conditional.length} conditional</Pill>}
          {unknown.length > 0 && <Pill tone="muted">{unknown.length} unproven</Pill>}
        </div>
        {failed.length > 0 && (
          <ul className="mt-4 space-y-1.5">
            {failed.map((g) => (
              <li key={g.gate_key} className="flex items-center gap-2">
                <Dot status="FAIL" />
                <span className="font-sans text-[12.5px] text-foreground">
                  {gateLabel(g.gate_key)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {failed.length === 0 && unknown.length > 0 && (
          <p className="mt-4 max-w-prose font-sans text-[12px] leading-[1.55] text-muted">
            No gate blocks this site, but {unknown.length}{" "}
            {unknown.length === 1 ? "is" : "are"} still awaiting source evidence — not a
            pass, just not yet a failure.
          </p>
        )}
      </Card>

      {/* Site */}
      <Card span="lg:col-span-3" label="Site">
        <div className="grid grid-cols-2 gap-5">
          <Stat value={acres == null ? "—" : Math.round(acres).toLocaleString()} label="Total acres" />
          <Stat
            value={developable == null ? "—" : Math.round(developable).toLocaleString()}
            label="Developable"
            sub={acres && developable ? `${((developable / acres) * 100).toFixed(0)}% of the parcel` : undefined}
            tone={acres && developable && developable / acres < 0.6 ? "warn" : "default"}
          />
        </div>
      </Card>

      {/* Physical constraints, as proportion bars */}
      <Card
        span="lg:col-span-3"
        label="Constraints"
        info="Share of the parcel each constraint covers, measured from the source layer. An empty track means the layer was not available for this region, which is different from a zero."
      >
        <div className="space-y-3.5">
          <Bar label="Wetland" pct={num("wetland_pct")} tone="warn" />
          <Bar label="Floodway" pct={num("floodway_pct")} tone="danger" />
          <Bar label="Protected land" pct={num("protected_land_pct")} tone="warn" />
          <Bar label="Median slope" pct={num("slope_median_pct")} tone="neutral" />
        </div>
      </Card>

      {/* Cost */}
      <Card
        span="lg:col-span-3"
        label="Indicative entry cost"
        info="Assessed land value plus roll-back tax exposure plus site preparation. Site prep is an AACE Class 5 screening estimate at -50%/+100%, so the span is the standard's, not a guess. Blank where any term is unrecorded — a total missing a term would compare two different things."
      >
        {entryLo == null ? (
          <Stat value="—" label="Not priced here" tone="muted"
                sub="One or more terms is unrecorded in this jurisdiction." />
        ) : (
          <>
            <Stat value={`${usd(entryLo)} – ${usd(entryHi)}`} label="Land + roll-back + site prep" />
            <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2">
              <span className="font-mono text-[10.5px] text-muted">
                land <span className="text-foreground">{usd(land)}</span>
              </span>
              <span className="font-mono text-[10.5px] text-muted">
                roll-back{" "}
                <span className={rollback ? "text-power dark:text-power-night" : "text-foreground"}>
                  {rollback ? usd(rollback) : "none"}
                </span>
              </span>
              <span className="font-mono text-[10.5px] text-muted">
                prep <span className="text-foreground">{usd(prepLo)}–{usd(prepHi)}</span>
              </span>
            </div>
          </>
        )}
      </Card>

      {/* Connectivity */}
      <Card
        span="lg:col-span-2"
        label="Interconnection"
        info="Latency floor is the round trip light itself needs through fibre over the straight-line distance — a bound no route can beat, not a forecast. Peering is the largest facility within 25 miles, which usually decides whether real interconnection is available."
      >
        <Stat
          value={latency == null ? "—" : `${latency.toFixed(2)} ms`}
          label="Latency floor"
          tone={latency == null ? "muted" : latency < 0.5 ? "good" : "warn"}
        />
        <div className="mt-4">
          <Stat
            value={peers == null ? "none in reach" : peers.toLocaleString()}
            label="Networks at best facility"
            tone={peers == null ? "danger" : peers >= 100 ? "good" : "warn"}
          />
        </div>
      </Card>

      {/* Power timing */}
      <Card
        span="lg:col-span-2"
        label="Power delivery"
        info="From the serving transmission area's own record: the projected in-service window for active upgrades, and how late that area has historically run against its own dates."
      >
        <Stat
          value={
            <span className="text-[14px] leading-tight">
              {fmtWindow(text("rtep_area_energization_range")) ?? "—"}
            </span>
          }
          label="Energization window"
          tone={text("rtep_area_energization_range") ? "default" : "muted"}
        />
        <div className="mt-4">
          <Stat
            value={slipP90 == null ? "—" : `${slipP90 > 0 ? "+" : ""}${slipP90} d`}
            label="p90 schedule slip"
            tone={slipP90 == null ? "muted" : slipP90 > 90 ? "warn" : "good"}
          />
        </div>
      </Card>

      {/* Evidence quality — how much of the verdict is actually measured */}
      <Card
        span="lg:col-span-2"
        label="Evidence"
        info="Counted, not scored. Two sites can share a verdict and differ entirely in how much of it was measured rather than inferred or modelled."
      >
        <div className="space-y-3">
          {(["observed", "derived", "estimated"] as const).map((cls) => {
            const n = metrics.filter((m) => m.evidence_class === cls).length;
            return (
              <div key={cls} className="flex items-baseline justify-between">
                <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
                  {cls}
                </span>
                <span className={`font-mono text-[13px] tabular-nums ${
                  n === 0 ? "text-muted" : "text-foreground"
                }`}>{n}</span>
              </div>
            );
          })}
          <div className="flex items-baseline justify-between border-t border-border/50 pt-3">
            <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
              Gates unproven
            </span>
            <span className={`font-mono text-[13px] tabular-nums ${
              unknown.length === 0 ? "text-muted" : "text-power dark:text-power-night"
            }`}>{unknown.length}</span>
          </div>
        </div>
      </Card>
    </div>
  );
}

/* ── A gate as a card. The verdict is a dot and the ink of the label;
      the rationale is prose at reading size; a coverage figure is a bar
      rather than a ruled-off row. ── */
function BlockingGateRow({ gate }: { gate: ParcelGateRow }) {
  const tone = {
    FAIL: "danger", CONDITIONAL: "warn", UNKNOWN: "muted", PASS: "good",
  }[gate.status] as "danger" | "warn" | "muted" | "good";
  const ink = {
    danger: "text-danger dark:text-danger-night",
    warn: "text-power dark:text-power-night",
    good: "text-success dark:text-success-night",
    muted: "text-muted",
  }[tone];
  return (
    <div className="rounded-xl bg-surface-raised/40 p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <Dot status={gate.status} />
          <span className="font-mono text-[12px] font-semibold text-foreground">
            {gateLabel(gate.gate_key)}
          </span>
        </div>
        <span className={`shrink-0 font-mono text-[9.5px] font-semibold uppercase tracking-[0.14em] ${ink}`}>
          {gate.status}
        </span>
      </div>
      {gate.rationale && (
        <p className="mt-2.5 max-w-prose font-sans text-[12.5px] leading-[1.6] text-muted">
          {gate.rationale}
        </p>
      )}
      {gate.affected_area_pct != null && (
        <div className="mt-4">
          <Bar label="Parcel area affected" pct={gate.affected_area_pct} tone={tone === "muted" ? "neutral" : tone} />
        </div>
      )}
    </div>
  );
}

/** A settled gate: name, dot, nothing else. It earned its place by not
 *  needing explaining. */
function PassedGateRow({ gate }: { gate: ParcelGateRow }) {
  return (
    <div className="flex items-center gap-2.5 px-1 py-2">
      <Dot status="PASS" />
      <span className="font-sans text-[12.5px] text-foreground/80">
        {gateLabel(gate.gate_key)}
      </span>
    </div>
  );
}

/* ══ Measured values ═══════════════════════════════════════════════════
   Fifty-one measurements under one heading is a data dump. Grouping them
   by what they describe turns the same rows into six or seven readable
   cards, and lets provenance move behind a disclosure per group rather
   than repeating a source line under every value. ── */

const METRIC_GROUPS: { label: string; match: RegExp }[] = [
  // "acreage", not "acre": the loose form also caught
  // assessed_land_value_per_acre_usd, which is a price and belongs with
  // the other money.
  { label: "Land & assembly", match: /acreage|assembly|adjoining/i },
  { label: "Physical constraints", match: /wetland|flood|slope|protected|soil/i },
  { label: "Power", match: /^(rtep|pjm|serving_utility|utility|substation|transmission|dc_application|parcel_utility)|power|energization|kv$/i },
  { label: "Water", match: /water/i },
  { label: "Interconnection", match: /^ixp_/i },
  { label: "Value, tax & incentives", match: /assessed|tax|land_use|site_prep|abatement|tif_|value/i },
  { label: "Zoning & use", match: /zoning|classification|use_status|assessment_class/i },
];

function groupMetrics(metrics: ParcelMetricRow[]) {
  const seen = new Set<string>();
  const groups = METRIC_GROUPS.map(({ label, match }) => {
    const rows = metrics.filter(
      (m) => !seen.has(m.metric_key) && match.test(m.metric_key)
    );
    rows.forEach((m) => seen.add(m.metric_key));
    return { label, rows };
  }).filter((g) => g.rows.length > 0);

  // Anything the groups did not claim still has to appear: a measurement
  // silently dropped because no pattern matched it would be worse than an
  // ugly heading.
  const rest = metrics.filter((m) => !seen.has(m.metric_key));
  if (rest.length) groups.push({ label: "Other measurements", rows: rest });
  return groups;
}

function metricValue(m: ParcelMetricRow): string {
  if (m.value != null) {
    const n = Number(m.value);
    const unit = m.unit === "percent" ? "%" : m.unit ? ` ${m.unit}` : "";
    const shown = Math.abs(n) >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 })
      : Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, "");
    return `${shown}${unit}`;
  }
  return m.text_value ?? "Unverified";
}

/** One measurement: name left, value right, no rule between them. */
function MetricRow({ metric }: { metric: ParcelMetricRow }) {
  const unrecorded = metric.value == null && !metric.text_value;
  const value = metricValue(metric);
  const stacked = metric.value == null && (metric.text_value?.length ?? 0) > 18;
  return (
    <div className={stacked ? "py-1.5" : "flex items-baseline justify-between gap-4 py-1.5"}>
      <span className="font-mono text-[10.5px] uppercase leading-snug tracking-[0.06em] text-muted">
        {metric.label ?? metric.metric_key}
      </span>
      <span className={`font-mono text-[12px] leading-snug tabular-nums ${
        stacked ? "mt-1 block" : "shrink-0 text-right"
      } ${unrecorded ? "text-muted" : "text-foreground"}`}>
        {value}
      </span>
    </div>
  );
}

/** Sources for a group, collapsed into one line per organisation rather
 *  than repeated under every measurement. */
function groupProvenance(rows: ParcelMetricRow[]): React.ReactNode {
  const byOrg = new Map<string, Set<string>>();
  for (const m of rows) {
    const org = m.source_organization ?? "no source recorded";
    if (!byOrg.has(org)) byOrg.set(org, new Set());
    if (m.evidence_class) byOrg.get(org)!.add(m.evidence_class);
  }
  return (
    <ul className="space-y-1.5">
      {Array.from(byOrg.entries()).map(([org, classes]) => (
        <li key={org} className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-foreground">{org}</span>
          <span className="font-mono text-[9.5px] uppercase tracking-[0.1em]">
            {Array.from(classes).sort().join(" · ") || "—"}
          </span>
        </li>
      ))}
    </ul>
  );
}

export const ParcelQualificationModal: React.FC<ParcelQualificationModalProps> = ({
  parcel,
  qualification,
  onClose,
  returnFocusTo,
  isShortlisted = false,
  onToggleShortlist,
}) => {
  const [dragH, setDragH] = useState<number | null>(null);
  const [sheet, setSheet] = useState<SheetState>("half");
  const dragStart = useRef<{ y: number; h: number } | null>(null);
  const lastDragEnd = useRef(0);
  const [documents, setDocuments] = useState<PowerDocument[]>([]);
  const [evidence, setEvidence] = useState<ParcelPowerEvidence[]>([]);

  type TabKey = "overview" | "gate_results" | "measured_values" | "utility_documents" | "decision";
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [passAccordionOpen, setPassAccordionOpen] = useState(false);

  const isDesktop = useIsDesktop();
  // Escape now lives in the trap, alongside the rest of the key handling.
  // Trapped on mobile, where the sheet really does cover the map;
  // free on desktop, where it sits beside it.
  const dialogRef = useFocusTrap(Boolean(parcel), onClose, returnFocusTo, !isDesktop);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  // Copying the centroid is the one thing a reader reliably wants to do
  // with it — paste into a map, a GIS, or a site visit brief. Plain
  // "lat, lon" because that is what every consumer of a coordinate pair
  // accepts; the display form carries hemispheres for reading, not pasting.
  const [copiedCentroid, setCopiedCentroid] = useState(false);
  const copyCentroid = () => {
    if (!parcel) return;
    const text = `${parcel.lat.toFixed(6)}, ${parcel.lon.toFixed(6)}`;
    navigator.clipboard?.writeText(text).then(
      () => {
        setCopiedCentroid(true);
        window.setTimeout(() => setCopiedCentroid(false), 1500);
      },
      () => {
        // Clipboard blocked (insecure context, denied permission). The
        // coordinate is on screen either way; silently doing nothing is
        // better than an error over a convenience.
      }
    );
  };

  useEffect(() => {
    if (parcel) {
      setSheet("half");
      setActiveTab("overview");
      setPassAccordionOpen(false);
      setCopiedCentroid(false);
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

  const tabs: { key: TabKey; label: string; count: number | null }[] = [
    // No count on Overview: it is a reading of the parcel, not a list of
    // things, and a number there would invite counting rather than reading.
    { key: "overview", label: "Overview", count: null },
    { key: "gate_results", label: "Gates", count: gates.length },
    { key: "measured_values", label: "Measured", count: metrics.length },
    { key: "utility_documents", label: "Evidence", count: documents.length + evidence.length },
    // No count: the decision tab is a control and a record, not a list —
    // a number there would invite counting rather than deciding.
    { key: "decision", label: "Decision", count: null },
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

          {/* Where the parcel actually is. County and state alone do not
              locate a 150-acre site, and the screening dossier has carried
              a centroid all along — this one had the same lon/lat on hand
              from v_land_parcels and simply never showed it. Same format
              as ParcelDetailModal so the two dossiers read alike. */}
          <p className="mt-2 font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted">
            {parcel.county_name ?? "Unsurveyed"} County, {parcel.state_code}
            {" · "}
            <button
              type="button"
              onClick={copyCentroid}
              title="Copy centroid as latitude, longitude"
              className="underline decoration-dotted underline-offset-2 transition-colors hover:text-foreground"
            >
              {fmtLat(parcel.lat)} {fmtLon(parcel.lon)}
            </button>
            {copiedCentroid && <span className="ml-1 text-accent-700 dark:text-accent-300">copied</span>}
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
                {tab.count == null ? tab.label : `${tab.label} · ${tab.count}`}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* ── Overview: the at-a-glance layer ── */}
        {activeTab === "overview" && (
          <div
            role="tabpanel"
            id="qual-panel-overview"
            aria-labelledby="qual-tab-overview"
            tabIndex={0}
            className="px-4 py-5 lg:px-6"
          >
            <OverviewPanel parcel={parcel} gates={gates} metrics={metrics} />
          </div>
        )}

        {/* ── Gates ── */}
        {activeTab === "gate_results" && (
          <div
            role="tabpanel"
            id="qual-panel-gate_results"
            aria-labelledby="qual-tab-gate_results"
            tabIndex={0}
            className="px-4 py-5 lg:px-6"
          >
            <SectionRule
              label="Gate results · by actionability"
              aside={gates.length === 0 ? undefined
                : `${attentionGates.length} open · ${passedGates.length} passed`}
            />

            {gates.length === 0 ? (
              <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
                No gates recorded for this parcel.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {attentionGates.map((g) => (
                  <BlockingGateRow key={g.gate_key} gate={g} />
                ))}

                {attentionGates.length === 0 && (
                  <p className="rounded-xl bg-surface-raised/40 p-5 font-sans text-[12.5px] leading-[1.6] text-muted lg:col-span-2">
                    Nothing outstanding. Every gate on this parcel is settled.
                  </p>
                )}

                {passedGates.length > 0 && (
                  <div className="rounded-xl bg-surface-raised/25 p-5 lg:col-span-2">
                    <button
                      onClick={() => setPassAccordionOpen((prev) => !prev)}
                      aria-expanded={passAccordionOpen}
                      className="flex w-full items-center justify-between gap-3 text-left font-mono text-[10px] uppercase tracking-[0.12em] text-muted transition-colors hover:text-foreground"
                    >
                      <span>
                        {passAccordionOpen ? "Hide" : "View"} {passedGates.length} passed criteria
                      </span>
                      {passAccordionOpen
                        ? <ChevronUp className="h-3.5 w-3.5 shrink-0" />
                        : <ChevronDown className="h-3.5 w-3.5 shrink-0" />}
                    </button>
                    {passAccordionOpen && (
                      <div className="mt-3 grid grid-cols-1 gap-x-8 sm:grid-cols-2">
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

        {/* ── Measured values, grouped by what they describe ── */}
        {activeTab === "measured_values" && (
          <div
            role="tabpanel"
            id="qual-panel-measured_values"
            aria-labelledby="qual-tab-measured_values"
            tabIndex={0}
            className="px-4 py-5 lg:px-6"
          >
            <SectionRule
              label="Measured values"
              aside={metrics.length ? `${metrics.length} recorded` : undefined}
            />
            {metrics.length === 0 ? (
              <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
                No measurements recorded for this parcel.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {groupMetrics(metrics).map((g) => (
                  <Card key={g.label} label={g.label} info={groupProvenance(g.rows)}>
                    <div className="space-y-0.5">
                      {g.rows.map((m) => (
                        <MetricRow key={m.metric_key} metric={m} />
                      ))}
                    </div>
                  </Card>
                ))}
              </div>
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
            className="px-4 py-5 lg:px-6"
          >
            {evidence.length > 0 && (
              <div className="mb-6">
                <SectionRule
                  label="Parcel-specific evidence · dated county record"
                  aside={`${evidence.length}`}
                />
                <div className="grid grid-cols-1 gap-4">
                  {evidence.map((e) => (
                    <Card
                      key={`${e.parcel_key}-${e.application_number}`}
                      info={
                        <>
                          <div>{e.document_name} · {e.document_date} · public LandMARC record</div>
                          {e.notes && <div className="mt-1.5">{e.notes}</div>}
                        </>
                      }
                    >
                      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                        <a
                          href={e.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-mono text-[12px] font-semibold text-foreground underline decoration-border-strong underline-offset-2 hover:decoration-foreground"
                        >
                          {e.application_type} {e.application_number}
                        </a>
                        <span className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted">
                          approved {e.approval_date}
                          {e.utility && <> · {e.utility}</>}
                        </span>
                      </div>
                      <p className="mt-2.5 max-w-prose font-sans text-[12.5px] leading-[1.6] text-foreground/90">
                        {e.utility_statement}
                      </p>
                      <div className="mt-4">
                        {e.capacity_mw != null ? (
                          <Stat
                            value={`${Number(e.capacity_mw).toLocaleString()} MW`}
                            label="Documented capacity · stated, never derived"
                            tone="good"
                          />
                        ) : (
                          <p className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted">
                            No MW figure asserted — the record documents service only
                          </p>
                        )}
                      </div>
                    </Card>
                  ))}
                </div>
              </div>
            )}

            <SectionRule
              label="Regional utility documents"
              aside={documents.length ? `${documents.length}` : undefined}
            />
            {documents.length === 0 ? (
              <p className="max-w-prose font-sans text-[12.5px] leading-[1.6] text-muted">
                No regional utility documents are currently registered for this jurisdiction.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {documents.map((d) => (
                  <Card key={d.doc_key}>
                    <a
                      href={d.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-[12px] font-semibold text-foreground underline decoration-border-strong underline-offset-2 hover:decoration-foreground"
                    >
                      {d.title}
                    </a>
                    <div className="mt-1.5 font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted">
                      {d.publisher}
                      {d.published_date && <> · as of {d.published_date}</>}
                    </div>
                    {d.summary && (
                      <p className="mt-2.5 max-w-prose font-sans text-[12.5px] leading-[1.6] text-muted">
                        {d.summary}
                      </p>
                    )}
                  </Card>
                ))}
              </div>
            )}

            <p className="mt-5 max-w-prose font-sans text-[11.5px] leading-[1.6] text-muted">
              Capacity figures appear only alongside the dated document that supports them.
              Zone-level forecasts are never restated as parcel claims.
            </p>
          </div>
        )}

        {/* ── Decision: record what you concluded, against this evidence ── */}
        {activeTab === "decision" && (
          <div
            role="tabpanel"
            id="qual-panel-decision"
            aria-labelledby="qual-tab-decision"
            tabIndex={0}
            className="px-4 py-5 lg:px-6"
          >
            <DecisionPanel parcel={parcel} gates={gates} />
            <p className="mt-5 max-w-prose font-sans text-[11.5px] leading-[1.6] text-muted">
              A decision is a claim about this parcel at a point in evidence.
              When a republish moves a gate, the decision stays — flagged as
              made against earlier evidence, never silently refreshed. An
              override accepts a failing gate beside it; the gate itself
              never changes, and no score or coverage reads a decision.
            </p>
          </div>
        )}
      </div>

      {/* ── Action bar ──────────────────────────────────────────────────
          Floats over the scrolling content on a blurred ground, so the
          actions stay reachable without a rule cutting the page in two. ── */}
      <div className="sticky bottom-0 z-20 flex shrink-0 flex-wrap items-center justify-between gap-3 bg-surface/80 px-4 py-3 backdrop-blur-md lg:px-6">
        <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-muted">
          {qualification
            ? `${gates.length} gates · ${metrics.length} metrics · lineage via ingestion run`
            : "Loading qualification…"}
        </div>
        <div className="flex items-center gap-2">
          {onToggleShortlist && (
            <button
              onClick={onToggleShortlist}
              aria-pressed={isShortlisted}
              className={`flex h-8 items-center gap-2 rounded-lg px-3.5 font-mono text-[10px] uppercase tracking-[0.14em] transition-colors ${
                isShortlisted
                  ? "bg-accent-600/12 text-accent-600 dark:bg-accent-400/15 dark:text-accent-400"
                  : "text-muted hover:bg-surface-raised hover:text-foreground"
              }`}
            >
              <Scale className="h-3 w-3" />
              {isShortlisted ? "Shortlisted" : "Shortlist"}
            </button>
          )}
          <button
            onClick={exportDossier}
            className="flex h-8 items-center gap-2 rounded-lg bg-foreground px-3.5 font-mono text-[10px] uppercase tracking-[0.14em] text-background transition-opacity hover:opacity-80"
          >
            <Download className="h-3 w-3" />
            Export
          </button>
        </div>
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

  /* ── Desktop: a docked inspector, not a modal ──────────────────────
     The dossier used to sit centred behind a dimming backdrop, which put
     the map out of reach: comparing two parcels meant closing, hunting,
     clicking and reopening, losing your place each time. Docked to the
     side, the map stays live and a click on another parcel simply swaps
     what the panel is reading.

     Consequently it is not a dialog. aria-modal would tell a screen
     reader the rest of the page is inert while the whole point is that it
     is not, so this is a labelled region and focus is not trapped —
     trapping it would make the map unreachable by keyboard, which is the
     same bug in a different costume. ── */
  if (isDesktop) {
    return (
      <aside
        ref={dialogRef}
        role="region"
        aria-label={dialogLabel}
        tabIndex={-1}
        data-dossier-panel
        className="fixed right-0 top-16 z-[1000] flex h-[calc(100vh-4rem)] w-[min(34rem,42vw)] flex-col overflow-hidden border-l border-border-strong bg-surface shadow-overlay outline-none"
      >
        {body}
      </aside>
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
