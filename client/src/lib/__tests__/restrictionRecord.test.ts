import { describe, expect, it } from "vitest";
import { ParcelGateRow, GateStatus } from "@/types/parcel";
import {
  levelName,
  levelStatusText,
  restrictionRecord,
} from "@/lib/restrictionRecord";

function gate(
  details: Record<string, unknown> | null | undefined,
  gate_key = "moratorium_status"
): ParcelGateRow {
  return { gate_key, status: "CONDITIONAL" as GateStatus, affected_area_pct: null, rationale: null, details };
}

describe("restrictionRecord", () => {
  it("lifts the instrument, dates and source out of a binding row", () => {
    const r = restrictionRecord(
      gate({
        instrument: "Emergency Ordinance 26-026",
        adopting_body: "Snohomish County Council",
        adopted_date: "2026-06-24",
        effective_date: "2026-06-24T00:00:00Z",
        expires_date: "2026-12-24",
        scope: "new or expanded data centres, unincorporated areas",
        source_url: "https://snohomishcounty.gov/ordinance-26-026",
        reviewed_at: "2026-09-01",
        evaluation_date: "2026-09-12T00:00:00Z",
        levels: {},
      })
    )!;
    expect(r.instrument).toBe("Emergency Ordinance 26-026");
    expect(r.adoptingBody).toBe("Snohomish County Council");
    // A timestamp still reads as its date — PostgREST returns DATE
    // columns bare but a timestamp only loses its tail.
    expect(r.effectiveDate).toBe("2026-06-24");
    expect(r.evaluationDate).toBe("2026-09-12");
    expect(r.expiresDate).toBe("2026-12-24");
    expect(r.noExpiry).toBe(false);
    expect(r.sourceUrl).toContain("snohomishcounty.gov");
    expect(r.levels).toEqual([]);
  });

  it("reads an instrument with no expiry as a finding, not a blank", () => {
    // A use-table amendment does not lapse; the dossier must say so
    // rather than rendering nothing where the expiry chip would sit.
    const r = restrictionRecord(
      gate({ instrument: "Zoning text amendment 2026-4", expires_date: null })
    )!;
    expect(r.noExpiry).toBe(true);
    expect(r.expiresDate).toBeNull();
  });

  it("orders the levels county outward, the order a reader checks them in", () => {
    const r = restrictionRecord(
      gate({
        evaluation_date: "2026-09-12",
        levels: {
          township: {
            jurisdiction: "Jersey township",
            status: "unreviewed",
            reviewed_at: null,
          },
          place: {
            jurisdiction: "Pataskala city",
            status: "pending",
            reviewed_at: "2026-09-10",
          },
          county: {
            jurisdiction: "Licking County",
            status: "none_found",
            reviewed_at: "2026-09-08",
          },
        },
      })
    )!;
    expect(r.levels.map((l) => l.kind)).toEqual(["county", "place", "township"]);
    expect(r.levels[0].status).toBe("none_found");
    expect(r.levels[1].reviewedAt).toBe("2026-09-10");
    expect(r.levels[2].jurisdiction).toBe("Jersey township");
  });

  it("returns null for a gate with no restriction content", () => {
    // A bare UNKNOWN row (restrictions layer missing) carries nothing
    // to cite — the dossier renders nothing rather than an empty frame.
    expect(restrictionRecord(gate({ restrictions_layer: "missing" }))).toBeNull();
    expect(restrictionRecord(gate(null))).toBeNull();
    expect(restrictionRecord(gate(undefined))).toBeNull();
  });

  it("returns null for another gate's details", () => {
    // The zoning gate's details share the dict shape but carry no
    // instrument or levels; they are not a restriction record.
    expect(
      restrictionRecord(
        gate({ zone: "A-1", ordinance: "Bennington Township Zoning Resolution" }, "zoning_dc_use")
      )
    ).toBeNull();
  });

  it("defaults a level's missing status to unreviewed", () => {
    const r = restrictionRecord(
      gate({ levels: { township: { jurisdiction: "Harrison township" } } })
    )!;
    expect(r.levels[0].status).toBe("unreviewed");
    expect(levelStatusText("unreviewed")).toBe("not yet reviewed");
    expect(levelStatusText("none_found")).toBe("reviewed — none found");
    expect(levelName("place")).toBe("Incorporated place");
  });
});
