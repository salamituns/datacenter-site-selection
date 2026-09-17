/**
 * The region list used to be hardcoded here, and it drifted: three Ohio
 * counties were published and the selector never offered them. It is now
 * derived from v_survey_regions, so these tests cover the only judgements
 * left in this file — how a region is labelled, and which ones the
 * selector offers first. After the PJM sweep there will be hundreds of
 * screening-only counties; the surveyed ten must not be buried in them.
 */
import { describe, it, expect } from "vitest";
import { filterRegions, isSurveyed, operatorTag, shortTag, type Region } from "../regions";

const region = (over: Partial<Region>): Region => ({
  code: "VA-LOUDOUN",
  label: "Loudoun VA · PJM",
  short: "LOUD",
  operator: "PJM",
  cells: 300,
  parcels: 100,
  surveyed: true,
  ...over,
});

describe("isSurveyed", () => {
  it("is true for a region with active parcels", () => {
    expect(isSurveyed(region({}))).toBe(true);
  });

  it("is false for a screening-only region like Morrow", () => {
    expect(
      isSurveyed(region({ code: "OR-MORROW", parcels: 0, surveyed: false })),
    ).toBe(false);
  });

  it("never strands the home region, whatever the counts say", () => {
    expect(isSurveyed(region({ parcels: 0, surveyed: false }))).toBe(true);
  });
});

describe("filterRegions", () => {
  const surveyed = [
    region({ code: "OH-FRANKLIN", label: "Franklin OH · PJM", short: "FRAN" }),
    region({ code: "OH-LICKING", label: "Licking OH · PJM", short: "LICK" }),
  ];
  const screening = [
    region({ code: "IL-COOK", label: "Cook IL · PJM", short: "COOK", parcels: 0, surveyed: false }),
    region({ code: "OR-MORROW", label: "Morrow OR · BPA", short: "MORR", parcels: 0, surveyed: false }),
  ];
  const all = [...screening, ...surveyed];

  it("offers only surveyed counties by default, in region-key order", () => {
    expect(filterRegions(all, "").map((r) => r.code)).toEqual([
      "OH-FRANKLIN",
      "OH-LICKING",
    ]);
  });

  it("surfaces screening counties behind search, after surveyed matches", () => {
    const matches = filterRegions(all, "or");
    // Morrow (screening) matches; the surveyed list itself has no "or",
    // so the search is the only way to reach it.
    expect(matches.map((r) => r.code)).toEqual(["OR-MORROW"]);
  });

  it("ranks a surveyed match ahead of a screening match", () => {
    const matches = filterRegions(all, "o");
    expect(matches[0].code).toBe("OH-FRANKLIN");
    expect(matches.some((r) => r.code === "IL-COOK")).toBe(true);
  });

  it("matches the state half of a region code case-insensitively", () => {
    expect(filterRegions(all, "il").map((r) => r.code)).toEqual(["IL-COOK"]);
  });
});

describe("operatorTag", () => {
  it("shortens the operators we actually serve", () => {
    expect(operatorTag("PJM Interconnection")).toBe("PJM");
    expect(operatorTag("Bonneville Power Administration")).toBe("BPA");
    expect(operatorTag("ERCOT")).toBe("ERCOT");
  });

  it("passes an unrecognised operator through rather than guessing", () => {
    // A region served by an operator nobody has tagged should read oddly,
    // not read wrongly.
    expect(operatorTag("Midcontinent ISO")).toBe("Midcontinent ISO");
  });

  it("does not invent an operator for a region that has none", () => {
    expect(operatorTag(null)).toBe("—");
  });
});

describe("shortTag", () => {
  it("distinguishes counties the old hand-picked codes collided on", () => {
    // The previous short codes were VA, TX, OH, LICK, PW, OR — "OH" stopped
    // being unambiguous the moment a second Ohio county arrived, and there
    // are five now.
    const ohio = ["Franklin", "Licking", "Fairfield", "Union", "Delaware"];
    const tags = ohio.map(shortTag);
    expect(new Set(tags).size).toBe(ohio.length);
    expect(tags).toEqual(["FRAN", "LICK", "FAIR", "UNIO", "DELA"]);
  });

  it("handles a two-word county", () => {
    expect(shortTag("Prince William")).toBe("PRIN");
  });

  it("strips punctuation rather than emitting it", () => {
    expect(shortTag("St. Louis")).toBe("STLO");
  });
});
