"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  GateStatus,
  JurisdictionProgram,
  LandParcel,
  ParcelComparison,
  ParcelDecision,
  ParcelMetricRow,
} from "@/types/parcel";
import { fetchJurisdictionPrograms, fetchParcelComparison } from "@/lib/supabase";
import { DECISION_LABELS, fetchParcelDecisions } from "@/lib/decisions";
import { useSession } from "@/lib/auth";
import { X, Trash2, Download } from "lucide-react";

interface Props {
  parcels: LandParcel[];
  onRemove: (parcelKey: string) => void;
  onClear: () => void;
  onClose: () => void;
}

/* The four axes the shortlist exists to answer. Cost and timing are the
   obvious ones; evidence quality and thesis-breaking risk are the two a
   suitability score cannot express, and they are given equal weight
   here rather than relegated to a footnote. */
type Axis = "cost" | "timing" | "evidence" | "risk";

const AXES: { key: Axis; label: string; blurb: string }[] = [
  { key: "cost", label: "Cost", blurb: "What the land and the ground work are likely to take" },
  { key: "timing", label: "Timing", blurb: "What the serving area's delivery record implies, and how close the networks are" },
  { key: "evidence", label: "Evidence", blurb: "How much of the verdict is measured rather than inferred" },
  { key: "risk", label: "Risk", blurb: "What could break the thesis outright" },
];

const VERDICT_INK: Record<GateStatus, string> = {
  PASS: "text-success dark:text-success-night border-success dark:border-success-night",
  CONDITIONAL: "text-power dark:text-power-night border-power dark:border-power-night",
  FAIL: "text-danger dark:text-danger-night border-danger dark:border-danger-night",
  UNKNOWN: "text-muted border-border-strong",
};

/** A currently exempt parcel pays nothing today and becomes fully taxable
 *  on acquisition by a taxable owner. Rendering that as a dash would read
 *  as "unrecorded" and hide a liability that appears at closing. */
function isExempt(c: ParcelComparison): boolean {
  const cls = c.qualification?.metrics
    .find((m) => m.metric_key === "assessment_class")?.text_value;
  return typeof cls === "string" && cls.trim().startsWith("0:");
}

function metric(c: ParcelComparison, key: string): ParcelMetricRow | undefined {
  return c.qualification?.metrics.find((m) => m.metric_key === key);
}

function num(c: ParcelComparison, key: string): number | null {
  const v = metric(c, key)?.value;
  return v == null ? null : Number(v);
}

function usd(v: number | null, digits = 0): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(digits ? 1 : 0)}k`;
  return `$${v.toFixed(0)}`;
}

/** A dash is not the same as a zero. Unverified means the source had no
 *  value; zero means the source recorded one. */
function acres(v: number | null): string {
  return v == null ? "—" : `${Math.round(v).toLocaleString()} ac`;
}

function Row({ label, note, children }: {
  label: string; note?: string; children: React.ReactNode;
}) {
  return (
    <tr className="border-b border-border/60 align-baseline">
      <th scope="row" className="sticky left-0 z-10 bg-surface py-2.5 pr-4 text-left">
        <span className="block font-mono text-[10px] uppercase tracking-[0.06em] text-foreground">
          {label}
        </span>
        {note && (
          <span className="mt-0.5 block max-w-[15rem] font-sans text-[10.5px] leading-snug text-muted">
            {note}
          </span>
        )}
      </th>
      {children}
    </tr>
  );
}

function Cell({ children, dim }: { children: React.ReactNode; dim?: boolean }) {
  return (
    <td className={`py-2.5 pr-5 text-right font-mono text-[11.5px] tabular-nums ${
      dim ? "text-muted" : "text-foreground"
    }`}>
      {children}
    </td>
  );
}

export const ParcelComparisonPanel: React.FC<Props> = ({
  parcels, onRemove, onClear, onClose,
}) => {
  const [rows, setRows] = useState<ParcelComparison[]>([]);
  const [axis, setAxis] = useState<Axis>("cost");
  const [loading, setLoading] = useState(false);

  const keys = parcels.map((p) => p.parcel_key).join(",");

  // Decision state per parcel — what the team concluded, attributed. Anon
  // quietly gets none (RLS denies by returning zero rows), so the table is
  // identical for a signed-out reader apart from this row's dashes.
  const session = useSession();
  const [decisionsByKey, setDecisionsByKey] = useState<Record<string, ParcelDecision[]>>({});
  useEffect(() => {
    if (parcels.length === 0) { setDecisionsByKey({}); return; }
    let alive = true;
    fetchParcelDecisions(parcels.map((p) => p.parcel_key)).then((byKey) => {
      if (alive) setDecisionsByKey(byKey);
    });
    return () => { alive = false; };
    // Re-run when the session changes: a sign-in mid-comparison should
    // populate the row without reopening the panel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys, session.ready, session.userId]);

  /** The standing decisions on one parcel, newest first. */
  const standingOn = (key: string): ParcelDecision[] =>
    (decisionsByKey[key] ?? []).filter((d) => d.is_current);

  useEffect(() => {
    if (parcels.length === 0) { setRows([]); return; }
    let alive = true;
    setLoading(true);
    fetchParcelComparison(parcels)
      .then((r) => { if (alive) setRows(r); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys]);

  /**
   * Programs are fetched per jurisdiction present in the shortlist, not for
   * whichever parcel happens to be first.
   *
   * This block used to read `parcels[0].state_code` and title itself "same
   * for every site here" — true only because the shortlist could not span
   * regions. Now that it can, taking the first parcel's state would show
   * Virginia's statutory programs above an Ohio site and assert they apply
   * to it, which is the same misattribution the cost assumptions are scoped
   * by jurisdiction to prevent.
   */
  const stateCodes = useMemo(
    () => Array.from(new Set(parcels.map((p) => p.state_code))).sort(),
    [parcels.map((p) => p.state_code).join(",")]
  );
  const [programsByState, setProgramsByState] =
    useState<Record<string, JurisdictionProgram[]>>({});
  useEffect(() => {
    if (stateCodes.length === 0) return;
    let alive = true;
    Promise.all(
      stateCodes.map((code) =>
        fetchJurisdictionPrograms(code).then((p) => [code, p] as const)
      )
    ).then((pairs) => {
      if (alive) setProgramsByState(Object.fromEntries(pairs));
    });
    return () => { alive = false; };
  }, [stateCodes.join(",")]);

  /** True when the table is comparing sites under more than one statute. */
  const mixedJurisdictions = stateCodes.length > 1;

  /* Site-prep is carried as a low/high pair with no midpoint, because the
     unit cost behind it is a placeholder rather than a published schedule.
     The table shows the span for the same reason. */
  const totals = useMemo(() => rows.map((c) => {
    const land = num(c, "assessed_land_value_usd");
    const rollback = num(c, "land_use_rollback_tax_usd");
    const lo = num(c, "site_prep_cost_low_usd");
    const hi = num(c, "site_prep_cost_high_usd");
    const known = [land, rollback, lo].filter((v) => v != null).length;
    return {
      land, rollback, lo, hi,
      // Only summed when every component is present: a total quietly
      // missing a term would compare two different things.
      entryLow: known === 3 ? (land! + rollback! + lo!) : null,
      entryHigh: known === 3 && hi != null ? (land! + rollback! + hi!) : null,
    };
  }), [rows]);

  const exportCsv = () => {
    /* RFC 4180 quoting. Every field goes through it rather than only the
       ones that look risky today: the column header now carries a county
       ("(Loudoun, VA)"), and an unquoted comma there would shift every
       value in the row one column left — a silently wrong spreadsheet
       rather than a broken one. */
    const csv = (v: string | number | null): string => {
      if (v == null) return "";
      const s = String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    // A PIN is unique only within its assessor's county, so the export
    // qualifies it — a CSV outlives the screen that explained it.
    const head = ["field", ...rows.map((r) =>
      r.parcel.county_name ? `${r.parcel.pin} (${r.parcel.county_name}, ${r.parcel.state_code})`
                           : r.parcel.pin)];
    const line = (label: string, vals: (string | number | null)[]) =>
      [label, ...vals].map(csv).join(",");
    const body = [
      line("verdict", rows.map((r) => r.parcel.overall_status ?? "")),
      line("team_decision", rows.map((r) =>
        standingOn(r.parcel.parcel_key)
          .map((d) =>
            `${DECISION_LABELS[d.decision]}${d.is_stale ? " (stale)" : ""}` +
            ` by ${d.decided_by_email ?? "team member"}`)
          .join("; "))),
      line("gis_acres", rows.map((r) => r.parcel.gis_acreage ?? "")),
      line("assessed_land_value_usd", rows.map((r) => num(r, "assessed_land_value_usd"))),
      line("land_use_rollback_tax_usd", rows.map((r) => num(r, "land_use_rollback_tax_usd"))),
      line("site_prep_cost_low_usd", rows.map((r) => num(r, "site_prep_cost_low_usd"))),
      line("site_prep_cost_high_usd", rows.map((r) => num(r, "site_prep_cost_high_usd"))),
      line("annual_property_tax_usd", rows.map((r) => num(r, "annual_property_tax_usd"))),
      line("rtep_area_schedule_slip_p90_days", rows.map((r) => num(r, "rtep_area_schedule_slip_p90_days"))),
      line("failing_gates", rows.map((r) =>
        (r.qualification?.gates.filter((g) => g.status === "FAIL").length ?? 0))),
      line("unknown_gates", rows.map((r) => r.evidence.unknownGates)),
      line("estimated_metrics", rows.map((r) => r.evidence.estimated)),
    ];
    const blob = new Blob([[head.map(csv).join(","), ...body].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "shortlist-comparison.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      {/* Masthead */}
      <div className="shrink-0 border-b border-border-strong px-4 pb-3 pt-4 lg:px-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="font-mono text-[20px] font-bold leading-none tracking-tight text-foreground lg:text-[24px]">
              Shortlist
            </h2>
            <p className="mt-2 max-w-prose font-display text-[14px] leading-snug text-foreground">
              {parcels.length === 0
                ? "No sites shortlisted yet."
                : `${parcels.length} ${parcels.length === 1 ? "site" : "sites"}, compared on what a suitability score cannot say.`}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {rows.length > 0 && (
              <button onClick={exportCsv} aria-label="Export comparison"
                className="flex h-7 items-center gap-1.5 border border-border-strong px-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted transition-colors hover:text-foreground">
                <Download className="h-3 w-3" /> CSV
              </button>
            )}
            {parcels.length > 0 && (
              <button onClick={onClear}
                className="flex h-7 items-center gap-1.5 border border-border-strong px-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted transition-colors hover:text-danger">
                <Trash2 className="h-3 w-3" /> Clear
              </button>
            )}
            <button onClick={onClose} aria-label="Close comparison"
              className="flex h-7 w-7 items-center justify-center border border-border-strong text-muted transition-colors hover:bg-surface-raised hover:text-foreground">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {parcels.length > 0 && (
          <div className="mt-3 flex border border-border-strong">
            {AXES.map((a, i) => (
              <button key={a.key} onClick={() => setAxis(a.key)}
                aria-current={axis === a.key}
                className={`flex-1 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em] transition-colors ${
                  axis === a.key
                    ? "bg-foreground text-background"
                    : "text-muted hover:bg-surface-raised/60 hover:text-foreground"
                } ${i > 0 ? "border-l border-border-strong" : ""}`}>
                {a.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-4 lg:px-6">
        {parcels.length === 0 ? (
          <p className="max-w-prose font-sans text-[12px] leading-[1.55] text-muted">
            Open a parcel from the map and add it to the shortlist. Sites can then
            be compared side by side on cost, timing, evidence quality and the
            risks that would break the thesis outright — the things a single
            suitability score flattens away.
          </p>
        ) : loading && rows.length === 0 ? (
          <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
            Resolving shortlist…
          </p>
        ) : (
          <>
            <p className="mb-3 max-w-prose font-sans text-[11.5px] leading-[1.5] text-muted">
              {AXES.find((a) => a.key === axis)?.blurb}.
            </p>
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-border-strong">
                  <th className="sticky left-0 z-10 bg-surface py-2 pr-4 text-left font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
                    Site
                  </th>
                  {rows.map((c) => (
                    <th key={c.parcel.parcel_key} className="py-2 pr-5 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <span className="font-mono text-[12px] font-bold text-foreground">
                          {c.parcel.pin}
                        </span>
                        <button onClick={() => onRemove(c.parcel.parcel_key)}
                          aria-label={`Remove ${c.parcel.pin}${
                            c.parcel.county_name ? ` in ${c.parcel.county_name} County` : ""
                          }`}
                          className="text-muted transition-colors hover:text-danger">
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                      {/* A PIN is only unique within its assessor's county, so
                          once the table spans counties the identifier alone
                          does not say which site a column is. */}
                      {mixedJurisdictions && (
                        <div className="mt-0.5 font-mono text-[8.5px] font-normal uppercase tracking-[0.14em] text-muted">
                          {c.parcel.county_name ?? "Unsurveyed"}, {c.parcel.state_code}
                        </div>
                      )}
                      {c.parcel.overall_status && (
                        <span className={`mt-1 inline-block border px-1.5 py-px font-mono text-[8.5px] font-semibold uppercase tracking-[0.14em] ${VERDICT_INK[c.parcel.overall_status]}`}>
                          {c.parcel.overall_status}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {axis === "cost" && (
                  <>
                    <tr className="border-b border-border/60">
                      <th scope="row" className="sticky left-0 z-10 bg-surface py-2.5 pr-4 text-left font-mono text-[10px] uppercase tracking-[0.06em] text-foreground">
                        Acreage
                      </th>
                      {rows.map((c) => (
                        <Cell key={c.parcel.parcel_key}>{acres(c.parcel.gis_acreage)}</Cell>
                      ))}
                    </tr>
                    <Row label="Assessed land value" note="Assessor's opinion, not a sale price.">
                      {rows.map((c) => (
                        <Cell key={c.parcel.parcel_key}>{usd(num(c, "assessed_land_value_usd"))}</Cell>
                      ))}
                    </Row>
                    <Row label="Land value / acre">
                      {rows.map((c) => (
                        <Cell key={c.parcel.parcel_key}>
                          {usd(num(c, "assessed_land_value_per_acre_usd"), 1)}
                        </Cell>
                      ))}
                    </Row>
                    <Row label="Annual property tax"
                         note="The county's own estimate. An exempt parcel pays nothing today and becomes fully taxable on acquisition.">
                      {rows.map((c) => {
                        const t = num(c, "annual_property_tax_usd");
                        if (t == null && isExempt(c)) {
                          const land = num(c, "assessed_total_value_usd")
                            ?? num(c, "assessed_land_value_usd");
                          return (
                            <Cell key={c.parcel.parcel_key} dim>
                              exempt
                              {land != null && (
                                <span className="block font-mono text-[9.5px] text-muted">
                                  ~{usd(land * 0.00805)}/yr if taxed
                                </span>
                              )}
                            </Cell>
                          );
                        }
                        return <Cell key={c.parcel.parcel_key}>{usd(t)}</Cell>;
                      })}
                    </Row>
                    <Row label="Assessment class" note="Exempt status does not survive a sale to a taxable owner.">
                      {rows.map((c) => {
                        const cls = metric(c, "assessment_class")?.text_value;
                        return (
                          <td key={c.parcel.parcel_key}
                              className={`py-2.5 pr-5 text-right font-mono text-[10.5px] ${
                                isExempt(c) ? "text-power dark:text-power-night" : "text-muted"
                              }`}>
                            {cls ? cls.replace(/^\d+:\s*/, "") : "—"}
                          </td>
                        );
                      })}
                    </Row>
                    <Row label="Roll-back tax exposure" note="Triggered on conversion where the parcel is in land-use deferral.">
                      {rows.map((c) => {
                        const v = num(c, "land_use_rollback_tax_usd");
                        return (
                          <Cell key={c.parcel.parcel_key} dim={v === 0}>
                            {v === 0 ? "none" : usd(v)}
                          </Cell>
                        );
                      })}
                    </Row>
                    <Row label="Site preparation" note="AACE Class 5 screening band, from this parcel's acreage and measured slope. Clearing and earthwork only.">
                      {rows.map((c) => {
                        const lo = num(c, "site_prep_cost_low_usd");
                        const hi = num(c, "site_prep_cost_high_usd");
                        return (
                          <Cell key={c.parcel.parcel_key}>
                            {lo == null ? "—" : `${usd(lo)} – ${usd(hi)}`}
                          </Cell>
                        );
                      })}
                    </Row>
                    <tr className="border-t-2 border-border-strong">
                      <th scope="row" className="sticky left-0 z-10 bg-surface py-3 pr-4 text-left">
                        <span className="block font-mono text-[10px] font-bold uppercase tracking-[0.06em] text-foreground">
                          Indicative entry cost
                        </span>
                        <span className="mt-0.5 block max-w-[15rem] font-sans text-[10.5px] leading-snug text-muted">
                          Land + roll-back + site prep. Blank where any term is unrecorded — a
                          total missing a term would compare two different things.
                        </span>
                      </th>
                      {totals.map((t, i) => (
                        <Cell key={rows[i].parcel.parcel_key}>
                          {t.entryLow == null
                            ? "—"
                            : `${usd(t.entryLow)} – ${usd(t.entryHigh)}`}
                        </Cell>
                      ))}
                    </tr>
                  </>
                )}

                {axis === "timing" && (
                  <>
                    <Row label="Energization window" note="Projected in-service dates for active upgrades in the serving area.">
                      {rows.map((c) => (
                        <Cell key={c.parcel.parcel_key}>
                          {metric(c, "rtep_area_energization_range")?.text_value ?? "—"}
                        </Cell>
                      ))}
                    </Row>
                    <Row label="Active upgrades (area)">
                      {rows.map((c) => (
                        <Cell key={c.parcel.parcel_key}>
                          {num(c, "rtep_area_active_upgrades") ?? "—"}
                        </Cell>
                      ))}
                    </Row>
                    <Row label="Median slip" note="Track record, not forecast. Negative means delivered early.">
                      {rows.map((c) => {
                        const v = num(c, "rtep_area_schedule_slip_median_days");
                        return <Cell key={c.parcel.parcel_key}>{v == null ? "—" : `${v > 0 ? "+" : ""}${v} d`}</Cell>;
                      })}
                    </Row>
                    <Row label="p90 slip" note="The tail a schedule should be underwritten against.">
                      {rows.map((c) => {
                        const v = num(c, "rtep_area_schedule_slip_p90_days");
                        return <Cell key={c.parcel.parcel_key}>{v == null ? "—" : `${v > 0 ? "+" : ""}${v} d`}</Cell>;
                      })}
                    </Row>
                    <Row label="Delivered on time">
                      {rows.map((c) => {
                        const v = num(c, "rtep_area_on_time_pct");
                        return <Cell key={c.parcel.parcel_key}>{v == null ? "—" : `${v}%`}</Cell>;
                      })}
                    </Row>
                    <Row label="Latency floor" note="Round trip light needs to the nearest facility. Cannot be beaten; real routes run 1.3-1.5x longer.">
                      {rows.map((c) => {
                        const v = num(c, "ixp_latency_floor_ms");
                        return <Cell key={c.parcel.parcel_key}>{v == null ? "—" : `${v.toFixed(2)} ms`}</Cell>;
                      })}
                    </Row>
                    <Row label="Nearest interconnection" note="Closest carrier hotel or colocation facility.">
                      {rows.map((c) => {
                        const d = num(c, "ixp_nearest_distance_miles");
                        const n = num(c, "ixp_networks_at_nearest");
                        return (
                          <Cell key={c.parcel.parcel_key}>
                            {d == null ? "—" : `${d.toFixed(1)} mi`}
                            {n != null && (
                              <span className="block font-mono text-[9.5px] text-muted">
                                {n.toLocaleString()} networks there
                              </span>
                            )}
                          </Cell>
                        );
                      })}
                    </Row>
                    <Row label="Peering in reach" note="Best facility within 25 miles — the nearest is often not the significant one.">
                      {rows.map((c) => {
                        const best = num(c, "ixp_best_facility_networks_within_25mi");
                        const tot = num(c, "ixp_networks_within_25mi");
                        const fac = num(c, "ixp_facilities_within_25mi");
                        return (
                          <Cell key={c.parcel.parcel_key}>
                            {best == null ? "—" : `${best.toLocaleString()} networks`}
                            {tot != null && fac != null && (
                              <span className="block font-mono text-[9.5px] text-muted">
                                {tot.toLocaleString()} across {fac} facilities
                              </span>
                            )}
                          </Cell>
                        );
                      })}
                    </Row>
                    <Row label="Upgrade cost (area)" note="PJM's own Board-approved estimates, not spend, and not this parcel's bill.">
                      {rows.map((c) => {
                        const v = num(c, "rtep_area_upgrade_cost_musd");
                        return <Cell key={c.parcel.parcel_key} dim>{v == null ? "—" : `$${v.toLocaleString()}M`}</Cell>;
                      })}
                    </Row>
                  </>
                )}

                {axis === "evidence" && (
                  <>
                    <Row label="Observed" note="Read from a source record.">
                      {rows.map((c) => <Cell key={c.parcel.parcel_key}>{c.evidence.observed}</Cell>)}
                    </Row>
                    <Row label="Derived" note="Computed from observed inputs.">
                      {rows.map((c) => <Cell key={c.parcel.parcel_key}>{c.evidence.derived}</Cell>)}
                    </Row>
                    <Row label="Estimated" note="Modelled against a named assumption. Treat with the least confidence.">
                      {rows.map((c) => (
                        <Cell key={c.parcel.parcel_key} dim={c.evidence.estimated === 0}>
                          {c.evidence.estimated}
                        </Cell>
                      ))}
                    </Row>
                    <Row label="Gates still unproven" note="Awaiting source data — not a failure, but not a pass either.">
                      {rows.map((c) => (
                        <Cell key={c.parcel.parcel_key} dim={c.evidence.unknownGates === 0}>
                          {c.evidence.unknownGates}
                        </Cell>
                      ))}
                    </Row>
                    {/* Decision state is context, not evidence: it never
                        feeds a score or a coverage figure, and a stale
                        decision says so rather than hiding. Mixed
                        authorship renders as what it is — several people,
                        several calls, each attributed. */}
                    <Row label="Team decision" note="Recorded against the evidence as it stood. Flagged when a republish has moved a gate since.">
                      {rows.map((c) => {
                        const standing = standingOn(c.parcel.parcel_key);
                        if (standing.length === 0) {
                          return (
                            <td key={c.parcel.parcel_key} className="py-2.5 pr-5 text-right font-mono text-[11.5px] text-muted">
                              —
                            </td>
                          );
                        }
                        return (
                          <td key={c.parcel.parcel_key} className="py-2.5 pr-5 text-right font-mono text-[11px] leading-snug">
                            {standing.map((d, i) => (
                              <span key={d.id} className="block">
                                <span className={d.is_stale ? "text-warning dark:text-warning-night" : "text-foreground"}>
                                  {DECISION_LABELS[d.decision]}
                                  {d.decision === "override" && d.override_status
                                    ? ` ${d.override_status}`
                                    : ""}
                                </span>
                                {d.is_stale && (
                                  <span className="text-warning dark:text-warning-night" title="Evidence changed since this decision — open the dossier to see which gates moved">
                                    {" "}· stale
                                  </span>
                                )}
                                <span className="block text-[9.5px] text-muted">
                                  {d.decided_by_email ?? "team member"}
                                  {i < standing.length - 1 ? "" : ""}
                                </span>
                              </span>
                            ))}
                          </td>
                        );
                      })}
                    </Row>
                  </>
                )}

                {axis === "risk" && (
                  <>
                    <Row label="Failing gates" note="Any one of these disqualifies the site as it stands.">
                      {rows.map((c) => {
                        const f = c.qualification?.gates.filter((g) => g.status === "FAIL") ?? [];
                        return (
                          <Cell key={c.parcel.parcel_key} dim={f.length === 0}>
                            {f.length === 0 ? "none" : f.length}
                          </Cell>
                        );
                      })}
                    </Row>
                    <Row label="What fails">
                      {rows.map((c) => {
                        const f = c.qualification?.gates.filter((g) => g.status === "FAIL") ?? [];
                        return (
                          <td key={c.parcel.parcel_key} className="py-2.5 pr-5 text-right font-sans text-[11px] leading-snug text-danger dark:text-danger-night">
                            {f.length === 0 ? <span className="text-muted">—</span>
                              : f.map((g) => g.gate_key.replace(/_/g, " ")).join(", ")}
                          </td>
                        );
                      })}
                    </Row>
                    <Row label="Conditional gates" note="Passable, but only with work.">
                      {rows.map((c) => {
                        const n = c.qualification?.gates.filter((g) => g.status === "CONDITIONAL").length ?? 0;
                        return <Cell key={c.parcel.parcel_key} dim={n === 0}>{n === 0 ? "none" : n}</Cell>;
                      })}
                    </Row>
                    <Row label="In land-use deferral" note="Conversion triggers roll-back tax under Code of Virginia 58.1-3237.">
                      {rows.map((c) => {
                        const t = metric(c, "in_land_use_deferral")?.text_value;
                        return (
                          <Cell key={c.parcel.parcel_key} dim={t !== "yes"}>
                            {t == null ? "—" : t}
                          </Cell>
                        );
                      })}
                    </Row>
                  </>
                )}
              </tbody>
            </table>

            {/* Jurisdiction programs. Grouped by statute rather than shown
                once, because a shortlist may now span states — and a
                program listed above a site it does not govern is worse than
                no program at all. */}
            {stateCodes.map((code) => {
              const programs = programsByState[code] ?? [];
              if (programs.length === 0) return null;
              const sites = parcels.filter((p) => p.state_code === code);
              return (
              <div key={code} className="mt-6 border-t border-border pt-4">
                <h4 className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
                  Statutory programs · {code} ·{" "}
                  {mixedJurisdictions
                    ? `applies to ${sites.length} of ${parcels.length} ${
                        parcels.length === 1 ? "site" : "sites"
                      } here`
                    : "same for every site here"}
                </h4>
                <div className="mt-3 space-y-2.5">
                  {programs.map((p) => (
                    <div key={p.program_key}
                      className={`border border-border/60 border-l-[3px] px-4 py-3 ${
                        p.kind === "levy"
                          ? "border-l-danger bg-danger/[0.05] dark:border-l-danger-night dark:bg-danger-night/[0.07]"
                          : "border-l-success bg-success/[0.05] dark:border-l-success-night dark:bg-success-night/[0.07]"
                      }`}>
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="font-mono text-[11px] font-semibold text-foreground">
                          {p.program_name}
                        </span>
                        <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-muted">
                          {p.kind === "levy" ? "cost" : p.kind} · {p.authority}
                        </span>
                      </div>
                      <p className="mt-1.5 max-w-prose font-sans text-[11.5px] leading-[1.5] text-muted">
                        {p.summary}
                      </p>
                      {p.policy_risk && (
                        <p className="mt-1.5 max-w-prose font-sans text-[11.5px] leading-[1.5] text-foreground/90">
                          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-muted">
                            Policy risk ·{" "}
                          </span>
                          {p.policy_risk}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
              );
            })}

            <p className="mt-5 max-w-prose border-t border-border pt-3 font-sans text-[11.5px] leading-[1.55] text-muted">
              A dash means the source recorded no value — never zero. Estimated
              figures carry the assumption that produced them; open a site&rsquo;s
              dossier to see it.
            </p>
          </>
        )}
      </div>
    </div>
  );
};
