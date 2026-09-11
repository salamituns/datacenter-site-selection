/**
 * Parcel decisions — what a person concluded about a parcel, recorded
 * against the evidence it was concluded from.
 *
 * Two rules from docs/parcel-decisions-brief.md shape everything here:
 *
 *   1. A decision is a claim about a parcel at a point in evidence. The
 *      row stores the run and the gate fingerprint it was made against;
 *      the view compares that to the current run and flags staleness.
 *      Nothing in this module ever recomputes or refreshes a stored
 *      fingerprint — the record stays exactly as it was made.
 *   2. An override never mutates a gate verdict. It is submitted as a
 *      decision with a named gate; the server reads that gate's current
 *      verdict and stores it beside the override. The gate itself is
 *      never written, and no score or coverage reads a decision.
 *
 * Every write goes through the record_parcel_decision RPC: authorship
 * comes from the session server-side, the fingerprint is computed
 * server-side from the run it claims, and superseding is atomic with
 * the replacement insert. There is no client path that writes a
 * decision row directly.
 */

import { supabase } from "@/lib/supabase";
import { DecisionKind, GateStatus, ParcelDecision } from "@/types/parcel";

/** The floor the database enforces on rationale, checked in the UI too —
 *  a form that submits and fails on a CHECK is a worse experience than
 *  one that asks. Ten characters of trimmed text, matching the server. */
export const RATIONALE_FLOOR = 10;

export function rationaleMeetsFloor(rationale: string): boolean {
  return rationale.trim().length >= RATIONALE_FLOOR;
}

export const DECISION_LABELS: Record<DecisionKind, string> = {
  approve: "Approved",
  reject: "Rejected",
  hold: "Held",
  override: "Overridden",
};

/** A gate as the decision surfaces read it — the subset the approve
 *  prompt needs, satisfied by the ParcelGateRow the dossier shows. */
export interface DecisionGate {
  gate_key: string;
  status: GateStatus;
}

/** What an approval of this evidence would be approved despite: every
 *  gate not PASS on the rows the dossier is showing. Empty for a clean
 *  pass — and no prompt. */
export function nonPassingGates(gates: DecisionGate[]): DecisionGate[] {
  return gates.filter((g) => g.status !== "PASS");
}

/**
 * Decisions for a set of parcels, keyed by parcel_key. Anon receives an
 * empty object rather than an error: RLS denies anon silently (zero
 * rows), and the same quiet empty is the right answer for a signed-out
 * visitor — the map, dossier and comparison all render regardless.
 */
export async function fetchParcelDecisions(
  parcelKeys: string[]
): Promise<Record<string, ParcelDecision[]>> {
  const out: Record<string, ParcelDecision[]> = {};
  if (!supabase || parcelKeys.length === 0) return out;
  try {
    const PAGE = 200; // keep the `in` list inside URL length limits
    for (let i = 0; i < parcelKeys.length; i += PAGE) {
      const { data, error } = await supabase
        .from("v_parcel_decisions")
        .select(
          "id,parcel_key,decision,rationale,decided_by,decided_by_email," +
          "decided_at,run_id,verdict_at_decision,gates_not_passing," +
          "override_gate,override_status,superseded_by," +
          "is_current,is_stale,gates_moved"
        )
        .in("parcel_key", parcelKeys.slice(i, i + PAGE));
      if (error) {
        // A signed-out reader gets zero rows by design; anything else is
        // a real failure worth logging, but never worth breaking the
        // dossier over — decisions are context, not the survey.
        console.error("Failed to fetch parcel decisions:", error);
        return out;
      }
      for (const row of (data ?? []) as unknown as ParcelDecision[]) {
        (out[row.parcel_key] ??= []).push(row);
      }
    }
  } catch (err) {
    console.error("Failed to fetch parcel decisions:", err);
  }
  return out;
}

/** The decision currently standing on a parcel (the newest row nothing
 *  has superseded), or null. History is the rest of the list. */
export function currentDecision(
  decisions: ParcelDecision[] | undefined
): ParcelDecision | null {
  if (!decisions || decisions.length === 0) return null;
  return decisions.find((d) => d.is_current) ?? null;
}

export interface RecordDecisionInput {
  parcelKey: string;
  decision: DecisionKind;
  rationale: string;
  /** Only for an override: the FAIL/UNKNOWN gate being accepted. */
  overrideGate?: string | null;
  /** The current decision being replaced, if any. The server atomically
   *  sets superseded_by on it as part of inserting the replacement. */
  supersedes?: string | null;
}

export type RecordDecisionResult =
  | { ok: true; id: string }
  | { ok: false; error: string };

/**
 * Records a decision through the RPC. The server raises readable
 * messages for every refusal (unsigned, thin rationale, an override
 * naming a passing gate, superseding someone else's decision); those
 * messages are surfaced verbatim rather than translated, because they
 * are the product telling the truth about what it refused.
 */
export async function recordDecision(
  input: RecordDecisionInput
): Promise<RecordDecisionResult> {
  if (!supabase) return { ok: false, error: "Supabase is not configured." };
  try {
    const { data, error } = await supabase.rpc("record_parcel_decision", {
      p_parcel_key: input.parcelKey,
      p_decision: input.decision,
      p_rationale: input.rationale,
      p_override_gate: input.overrideGate ?? null,
      p_supersedes: input.supersedes ?? null,
    });
    if (error) return { ok: false, error: error.message };
    return { ok: true, id: String(data) };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : "Recording failed.",
    };
  }
}

/**
 * "wetlands: PASS → FAIL", one line per moved gate, for the staleness
 * warning. A gate present on only one side reads "added"/"removed"
 * rather than pretending a status existed.
 */
export function movedGatesLines(
  moved: ParcelDecision["gates_moved"]
): string[] {
  if (!moved || moved.length === 0) return [];
  return moved.map((m) => {
    if (m.was == null) return `${m.gate_key}: added, now ${m.now}`;
    if (m.now == null) return `${m.gate_key}: removed, was ${m.was}`;
    return `${m.gate_key}: ${m.was} → ${m.now}`;
  });
}
