import { describe, expect, it } from "vitest";
import {
  DECISION_LABELS,
  RATIONALE_FLOOR,
  currentDecision,
  fetchParcelDecisions,
  movedGatesLines,
  nonPassingGates,
  rationaleMeetsFloor,
} from "@/lib/decisions";
import { DecisionKind, ParcelDecision } from "@/types/parcel";

/** Neutral fixture id — the helpers under test treat it as opaque. */
const FIXTURE_PARCEL_KEY = "TEST-PARCEL-KEY";

function decision(over: Partial<ParcelDecision>): ParcelDecision {
  return {
    id: "d1",
    parcel_key: FIXTURE_PARCEL_KEY,
    decision: "approve",
    rationale: "a rationale long enough to record",
    decided_by: "u1",
    decided_by_email: "a@example.com",
    decided_at: "2026-09-11T00:00:00Z",
    run_id: "r1",
    verdict_at_decision: "PASS",
    gates_not_passing: [],
    override_gate: null,
    override_status: null,
    superseded_by: null,
    is_current: true,
    is_stale: false,
    gates_moved: null,
    ...over,
  };
}

describe("rationaleMeetsFloor", () => {
  it("matches the database floor exactly", () => {
    expect(RATIONALE_FLOOR).toBe(10);
  });

  it("rejects empty and whitespace-only rationale", () => {
    expect(rationaleMeetsFloor("")).toBe(false);
    expect(rationaleMeetsFloor("          ")).toBe(false);
  });

  it("rejects below the floor, accepts at and above it", () => {
    expect(rationaleMeetsFloor("nine chr")).toBe(false);
    expect(rationaleMeetsFloor("exactly ten")).toBe(true);
    expect(rationaleMeetsFloor("   padded but sufficient   ")).toBe(true);
  });
});

describe("movedGatesLines", () => {
  it("names a moved gate with its two statuses", () => {
    expect(
      movedGatesLines([{ gate_key: "wetlands", was: "PASS", now: "FAIL" }])
    ).toEqual(["wetlands: PASS → FAIL"]);
  });

  it("reads a gate on only one side as added or removed, not as a status that existed", () => {
    expect(movedGatesLines([{ gate_key: "slope", was: null, now: "FAIL" }]))
      .toEqual(["slope: added, now FAIL"]);
    expect(movedGatesLines([{ gate_key: "slope", was: "PASS", now: null }]))
      .toEqual(["slope: removed, was PASS"]);
  });

  it("returns nothing when the view reported no movement", () => {
    expect(movedGatesLines(null)).toEqual([]);
    expect(movedGatesLines([])).toEqual([]);
  });
});

describe("currentDecision", () => {
  it("returns the standing decision, not the history", () => {
    const superseded = decision({ id: "old", is_current: false, superseded_by: "new" });
    const standing = decision({ id: "new", decision: "reject" });
    expect(currentDecision([superseded, standing])?.id).toBe("new");
  });

  it("returns null with no decisions rather than a synthetic one", () => {
    expect(currentDecision([])).toBeNull();
    expect(currentDecision(undefined)).toBeNull();
  });

  it("returns null when everything has been superseded — an all-history list has no standing verdict", () => {
    expect(
      currentDecision([decision({ is_current: false, superseded_by: "x" })])
    ).toBeNull();
  });
});

describe("nonPassingGates", () => {
  it("keeps every gate that is not PASS, in the order the dossier shows", () => {
    const gates = [
      { gate_key: "wetlands", status: "PASS" as const },
      { gate_key: "protected_land", status: "FAIL" as const },
      { gate_key: "power_capacity", status: "UNKNOWN" as const },
      { gate_key: "slope", status: "CONDITIONAL" as const },
    ];
    expect(nonPassingGates(gates).map((g) => g.gate_key)).toEqual([
      "protected_land",
      "power_capacity",
      "slope",
    ]);
  });

  it("is empty for a clean pass — nothing to prompt about, nothing approved despite", () => {
    expect(nonPassingGates([{ gate_key: "wetlands", status: "PASS" }]))
      .toEqual([]);
    expect(nonPassingGates([])).toEqual([]);
  });
});

describe("DECISION_LABELS", () => {
  it("labels exactly the four kinds the database CHECK allows", () => {
    expect(Object.keys(DECISION_LABELS).sort()).toEqual(
      (["approve", "reject", "hold", "override"] as DecisionKind[]).sort()
    );
  });
});

describe("fetchParcelDecisions", () => {
  it("asks nothing of the network for an empty key set", async () => {
    // With no keys the function returns before touching the client —
    // and without env credentials the client is null anyway, which must
    // also produce a quiet empty rather than a throw: decisions are
    // context, never a reason the dossier fails to render.
    await expect(fetchParcelDecisions([])).resolves.toEqual({});
  });
});
