"use client";

/**
 * The decision surface of the dossier — where a person records what
 * they concluded about this parcel, against the evidence as it stands.
 *
 * The panel is visible to everyone, signed out included: the buttons
 * render inert with an explanation rather than hiding, because a
 * product that looks like it lacks the feature is worse than one that
 * says why it needs you. Signing in buys the ability to record a
 * decision and nothing else — the dossier around this panel is
 * identical either way.
 *
 * Data rules (docs/parcel-decisions-brief.md):
 *   - a decision is a claim at a point in evidence: staleness is shown,
 *     never auto-voided, never silently refreshed;
 *   - an override names the FAIL/UNKNOWN gate it accepts; the gate's
 *     verdict stays exactly as the evidence left it — the panel renders
 *     "FAIL · overridden by [author]", the data still says FAIL;
 *   - changing your mind supersedes: a new row, the old row pointed at
 *     it, nothing edited in place, nothing deleted.
 */

import React, { useEffect, useMemo, useState } from "react";
import { Mail, AlertTriangle } from "lucide-react";
import {
  LandParcel,
  ParcelGateRow,
  DecisionKind,
  ParcelDecision,
} from "@/types/parcel";
import { useSession, sendMagicLink } from "@/lib/auth";
import {
  DECISION_LABELS,
  movedGatesLines,
  rationaleMeetsFloor,
  RATIONALE_FLOOR,
  fetchParcelDecisions,
  recordDecision,
} from "@/lib/decisions";
import { gateLabel } from "@/components/ParcelQualificationModal";

interface DecisionPanelProps {
  parcel: LandParcel;
  /** This parcel's current gates — an override offers only the FAIL and
   *  UNKNOWN ones, read from the same rows the dossier is displaying. */
  gates: ParcelGateRow[];
}

const DECISION_TONE: Record<DecisionKind, string> = {
  approve: "text-success dark:text-success-night border-success dark:border-success-night",
  reject: "text-danger dark:text-danger-night border-danger dark:border-danger-night",
  hold: "text-power dark:text-power-night border-power dark:border-power-night",
  override: "text-accent-700 dark:text-accent-300 border-accent-600 dark:border-accent-400",
};

function DecisionChip({ kind }: { kind: DecisionKind }) {
  return (
    <span
      className={`shrink-0 border px-1.5 py-px font-mono text-[8.5px] font-semibold uppercase tracking-[0.14em] ${DECISION_TONE[kind]}`}
    >
      {DECISION_LABELS[kind]}
    </span>
  );
}

function fmtWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** One recorded decision: the verdict, who made it, when, and why — the
 *  rationale is the record, so it always renders, never truncated away. */
function DecisionCard({ d, isYours }: { d: ParcelDecision; isYours: boolean }) {
  const moved = movedGatesLines(d.gates_moved);
  return (
    <div className="rounded-xl bg-surface-raised/40 p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <DecisionChip kind={d.decision} />
        <span className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted">
          {d.decided_by_email ?? "team member"} · {fmtWhen(d.decided_at)}
          {isYours ? " · yours" : ""}
        </span>
        {d.superseded_by && (
          <span className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted">
            superseded
          </span>
        )}
      </div>
      <p className="mt-2 max-w-prose font-sans text-[12.5px] leading-[1.6] text-foreground/90">
        {d.rationale}
      </p>
      {d.decision === "override" && d.override_gate && (
        <p className="mt-2 font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted">
          {gateLabel(d.override_gate)} reads {d.override_status} — accepted
          with eyes open. The gate itself is unchanged.
        </p>
      )}
      {d.is_stale && moved.length > 0 && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-warning/10 p-2.5 dark:bg-warning-night/10">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning dark:text-warning-night" />
          <div className="font-sans text-[11.5px] leading-[1.55] text-foreground/90">
            <span className="font-semibold">Evidence changed since this decision.</span>{" "}
            The verdict was correct against what was known; it has not been
            voided or refreshed. Moved gates:
            <ul className="mt-1 list-inside list-disc font-mono text-[10.5px] text-muted">
              {moved.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

/** Signed-out state: the same buttons, inert, with the reason and a
 *  sign-in form right there. Never hidden — the feature exists. */
function SignedOutForm() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<
    { kind: "idle" } | { kind: "sending" } | { kind: "sent" } | { kind: "error"; message: string }
  >({ kind: "idle" });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || status.kind === "sending") return;
    setStatus({ kind: "sending" });
    const result = await sendMagicLink(email);
    setStatus(result.ok ? { kind: "sent" } : { kind: "error", message: result.error });
  };

  return (
    <div className="rounded-xl bg-surface-raised/40 p-5">
      <p className="font-sans text-[12.5px] leading-[1.6] text-muted">
        Recording a decision needs a named author, so it can be reviewed
        later. Sign in below — nothing else on this site needs an account,
        and this dossier is identical signed out.
      </p>
      <form onSubmit={submit} className="mt-3 flex gap-2">
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          aria-label="Email address"
          className="h-8 min-w-0 flex-1 rounded-[2px] border border-border-strong bg-background px-2 font-mono text-[11px] text-foreground placeholder:text-muted focus:border-accent-600 focus:outline-none"
        />
        <button
          type="submit"
          disabled={status.kind === "sending"}
          className="flex h-8 shrink-0 items-center gap-1.5 rounded-[2px] bg-foreground px-3 font-mono text-[10px] uppercase tracking-[0.12em] text-background transition-opacity hover:opacity-80 disabled:opacity-60"
        >
          <Mail className="h-3 w-3" />
          {status.kind === "sending" ? "Sending…" : "Send link"}
        </button>
      </form>
      {status.kind === "sent" && (
        <p className="mt-3 font-sans text-[11.5px] leading-[1.55] text-success dark:text-success-night">
          Link sent — the session opens when you click it.
        </p>
      )}
      {status.kind === "error" && (
        <p className="mt-3 font-sans text-[11.5px] leading-[1.55] text-danger dark:text-danger-night">
          {status.message}
        </p>
      )}
    </div>
  );
}

export function DecisionPanel({ parcel, gates }: DecisionPanelProps) {
  const session = useSession();
  const [decisions, setDecisions] = useState<ParcelDecision[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [kind, setKind] = useState<DecisionKind>("approve");
  const [rationale, setRationale] = useState("");
  const [overrideGate, setOverrideGate] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Decisions load whenever the parcel changes or a session appears —
  // anon quietly gets none, a signed-in team member gets the record.
  useEffect(() => {
    let alive = true;
    setLoaded(false);
    fetchParcelDecisions([parcel.parcel_key]).then((byKey) => {
      if (!alive) return;
      setDecisions(byKey[parcel.parcel_key] ?? []);
      setLoaded(true);
    });
    return () => {
      alive = false;
    };
  }, [parcel.parcel_key, session.ready, session.userId]);

  const current = useMemo(
    () => decisions.filter((d) => d.is_current),
    [decisions]
  );
  const history = useMemo(
    () => decisions.filter((d) => !d.is_current),
    [decisions]
  );
  const mine = current.find((d) => d.decided_by === session.userId) ?? null;
  const theirs = current.filter((d) => d.decided_by !== session.userId);

  // An override may only accept a gate that is currently failing or
  // unproven — the same rows the Gates tab shows, filtered to the two
  // statuses an override is defined against.
  const overridable = gates.filter(
    (g) => g.status === "FAIL" || g.status === "UNKNOWN"
  );
  useEffect(() => {
    if (kind !== "override" || overrideGate) return;
    setOverrideGate(overridable[0]?.gate_key ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, gates]);

  const rationaleOk = rationaleMeetsFloor(rationale);
  const canSubmit =
    session.email != null &&
    !submitting &&
    rationaleOk &&
    (kind !== "override" || overrideGate != null);

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    const result = await recordDecision({
      parcelKey: parcel.parcel_key,
      decision: kind,
      rationale,
      overrideGate: kind === "override" ? overrideGate : null,
      // Replacing your own standing decision supersedes it; a teammate's
      // decision is never superseded by yours — both stand, attributed.
      supersedes: mine?.id ?? null,
    });
    setSubmitting(false);
    if (!result.ok) {
      // The server's refusals are readable sentences; show them verbatim.
      setError(result.error);
      return;
    }
    setRationale("");
    setError(null);
    const byKey = await fetchParcelDecisions([parcel.parcel_key]);
    setDecisions(byKey[parcel.parcel_key] ?? []);
  };

  return (
    <div>
      {/* Standing decisions — the team's, then yours, so mixed
          authorship reads as what it is: several people, several calls. */}
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <h4 className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
          Decision
        </h4>
        {loaded && current.length > 0 && (
          <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.1em] text-muted">
            {current.length} standing
          </span>
        )}
      </div>

      {session.email == null ? (
        <>
          {/* Inert on purpose, and saying so: hiding the control would
              make the product look like it lacks the feature. */}
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {(Object.keys(DECISION_LABELS) as DecisionKind[]).map((k) => (
              <button
                key={k}
                disabled
                aria-disabled="true"
                title="Sign in to record a decision"
                className="cursor-not-allowed rounded-lg border border-border-strong px-3 py-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted opacity-55"
              >
                {DECISION_LABELS[k]}
              </button>
            ))}
          </div>
          <SignedOutForm />
        </>
      ) : (
        <>
          {current.length === 0 && loaded && (
            <p className="mb-4 font-sans text-[12.5px] leading-[1.6] text-muted">
              No decision recorded for this parcel yet.
            </p>
          )}
          {current.length > 0 && (
            <div className="mb-4 space-y-3">
              {theirs.map((d) => (
                <DecisionCard key={d.id} d={d} isYours={false} />
              ))}
              {mine && <DecisionCard key={mine.id} d={mine} isYours />}
            </div>
          )}

          {/* Recording — the rationale is required here, not merely by
              the database: a form that asks beats a submit that fails. */}
          <div className="rounded-xl border border-border-strong p-4">
            <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted">
              {mine
                ? "Record a new decision (supersedes yours above)"
                : "Record a decision"}
            </p>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(Object.keys(DECISION_LABELS) as DecisionKind[]).map((k) => (
                <button
                  key={k}
                  onClick={() => setKind(k)}
                  aria-pressed={kind === k}
                  className={`rounded-lg border px-3 py-2 font-mono text-[10px] uppercase tracking-[0.12em] transition-colors ${
                    kind === k
                      ? "border-foreground bg-foreground text-background"
                      : "border-border-strong text-muted hover:border-foreground/60 hover:text-foreground"
                  }`}
                >
                  {DECISION_LABELS[k]}
                </button>
              ))}
            </div>

            {kind === "override" && (
              <div className="mt-3">
                {overridable.length === 0 ? (
                  <p className="font-sans text-[11.5px] leading-[1.55] text-muted">
                    An override accepts a FAIL or UNKNOWN gate with your
                    eyes open. This parcel has none to accept.
                  </p>
                ) : (
                  <label className="block">
                    <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted">
                      Gate being accepted despite its verdict
                    </span>
                    <select
                      value={overrideGate ?? ""}
                      onChange={(e) => setOverrideGate(e.target.value || null)}
                      className="mt-1.5 h-8 w-full rounded-[2px] border border-border-strong bg-background px-2 font-mono text-[11px] text-foreground focus:border-accent-600 focus:outline-none"
                    >
                      {overridable.map((g) => (
                        <option key={g.gate_key} value={g.gate_key}>
                          {gateLabel(g.gate_key)} — {g.status}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            )}

            <label className="mt-3 block">
              <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted">
                Rationale — required, reviewable later
              </span>
              <textarea
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                rows={3}
                placeholder={`Why this call, in your own words (at least ${RATIONALE_FLOOR} characters)`}
                className="mt-1.5 w-full resize-y rounded-[2px] border border-border-strong bg-background px-2 py-1.5 font-sans text-[12px] leading-[1.55] text-foreground placeholder:text-muted focus:border-accent-600 focus:outline-none"
              />
            </label>
            {rationale.length > 0 && !rationaleOk && (
              <p className="mt-1.5 font-sans text-[11px] leading-snug text-danger dark:text-danger-night">
                A decision with no stated reason cannot be reviewed later —
                {RATIONALE_FLOOR - rationale.trim().length} more character
                {RATIONALE_FLOOR - rationale.trim().length === 1 ? "" : "s"} needed.
              </p>
            )}

            {error && (
              <p className="mt-2 font-sans text-[11.5px] leading-[1.55] text-danger dark:text-danger-night">
                {error}
              </p>
            )}

            <div className="mt-3 flex items-center justify-between gap-3">
              <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-muted">
                Attributed to {session.email} · recorded against the current
                run
              </span>
              <button
                onClick={submit}
                disabled={!canSubmit}
                className="h-8 shrink-0 rounded-lg bg-foreground px-4 font-mono text-[10px] uppercase tracking-[0.14em] text-background transition-opacity hover:opacity-80 disabled:opacity-50"
              >
                {submitting ? "Recording…" : "Record decision"}
              </button>
            </div>
          </div>
        </>
      )}

      {/* History — superseded decisions stay readable: the history is
          the point of append-only. */}
      {history.length > 0 && (
        <div className="mt-5">
          <div className="mb-3 flex items-baseline justify-between gap-4">
            <h4 className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted">
              Superseded
            </h4>
            <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.1em] text-muted">
              {history.length}
            </span>
          </div>
          <div className="space-y-3 opacity-75">
            {history.map((d) => (
              <DecisionCard key={d.id} d={d} isYours={d.decided_by === session.userId} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
