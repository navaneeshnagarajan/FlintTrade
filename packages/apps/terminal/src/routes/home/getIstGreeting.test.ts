/**
 * getIstGreeting.test.ts — IST time-of-day buckets for the home Welcome card.
 *
 * Pins FIXED Asia/Kolkata instants via {@link fromIstParts} so the suite
 * proves the same greeting whichever timezone the machine (or CI) is set to.
 * FT-HOME-001: noon IST must be Good afternoon, not Good evening from a
 * non-IST browser clock.
 */

import { describe, expect, it } from "vitest";

import { fromIstParts } from "@/lib/ist";

import { getIstGreeting } from "./getIstGreeting";

describe("getIstGreeting", () => {
  it("says Good morning before noon IST", () => {
    expect(getIstGreeting(fromIstParts(2026, 8, 10, 11, 59))).toBe("Good morning");
  });

  it("says Good afternoon at noon IST", () => {
    expect(getIstGreeting(fromIstParts(2026, 8, 10, 12, 0))).toBe("Good afternoon");
  });

  it("says Good afternoon at 12:01 IST (FT-HOME-001)", () => {
    expect(getIstGreeting(fromIstParts(2026, 8, 10, 12, 1))).toBe("Good afternoon");
  });

  it("says Good afternoon just before 17:00 IST", () => {
    expect(getIstGreeting(fromIstParts(2026, 8, 10, 16, 59))).toBe("Good afternoon");
  });

  it("says Good evening from 17:00 IST", () => {
    expect(getIstGreeting(fromIstParts(2026, 8, 10, 17, 0))).toBe("Good evening");
  });

  it("says Good evening later in the IST night", () => {
    expect(getIstGreeting(fromIstParts(2026, 8, 10, 20, 0))).toBe("Good evening");
  });

  it("says Good morning at midnight IST", () => {
    expect(getIstGreeting(fromIstParts(2026, 8, 10, 0, 0))).toBe("Good morning");
  });
});
