/**
 * The region list used to be hardcoded here, and it drifted: three Ohio
 * counties were published and the selector never offered them. It is now
 * derived from v_survey_regions, so these tests cover the only judgement
 * left in this file — how a region is labelled.
 */
import { describe, it, expect } from "vitest";
import { operatorTag, shortTag } from "../regions";

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
