/**
 * nseSession.test.ts
 *
 * CAS-aware NSE cash session clock (FT-CORE-001, as of Aug 2026).
 * Phase chips are Continuous · CAS · Matching · Post-close · Closed.
 * Cash is never green "open" after 15:15; CAS is not Closed.
 */

import { describe, expect, it } from "vitest";
import {
  CAS_SCHEDULE_NOTE,
  NSE_CASH_TIMELINE_NOTE,
  formatNseCashSessionTitle,
  resolveNseCashSession,
} from "../nseSession";

function weekday(minutes: number): Date {
  // Tuesday 18 Aug 2026 — after CAS go-live (3 Aug 2026).
  const utcMs = Date.UTC(2026, 7, 18, 0, 0, 0, 0) - (5 * 60 + 30) * 60 * 1000;
  return new Date(utcMs + minutes * 60_000);
}

function saturday(minutes: number): Date {
  const utcMs = Date.UTC(2026, 7, 22, 0, 0, 0, 0) - (5 * 60 + 30) * 60 * 1000;
  return new Date(utcMs + minutes * 60_000);
}

describe("resolveNseCashSession phase boundaries", () => {
  it.each([
    [9 * 60 + 15, "continuous", "Continuous"],
    [12 * 60, "continuous", "Continuous"],
    [15 * 60 + 14, "continuous", "Continuous"],
    [15 * 60 + 15, "cas", "CAS"],
    [15 * 60 + 20, "cas", "CAS"],
    [15 * 60 + 34, "cas", "CAS"],
    [15 * 60 + 35, "matching", "Matching"],
    [15 * 60 + 45, "matching", "Matching"],
    [15 * 60 + 49, "matching", "Matching"],
    [15 * 60 + 50, "post-close", "Post-close"],
    [15 * 60 + 59, "post-close", "Post-close"],
    [16 * 60, "closed", "Closed"],
    [9 * 60 + 14, "closed", "Closed"],
    [18 * 60, "closed", "Closed"],
  ] as const)("at %s minutes IST is %s (%s)", (minutes, phase, label) => {
    const session = resolveNseCashSession(weekday(minutes));
    expect(session.phase).toBe(phase);
    expect(session.label).toBe(label);
  });

  it("is Closed on Saturday even during weekday session hours", () => {
    const session = resolveNseCashSession(saturday(12 * 60));
    expect(session.phase).toBe("closed");
    expect(session.label).toBe("Closed");
    expect(session.isGreenOpen).toBe(false);
  });
});

describe("cash honesty — never green open after 15:15; CAS is not Closed", () => {
  it("is green open only during Continuous", () => {
    expect(resolveNseCashSession(weekday(10 * 60)).isGreenOpen).toBe(true);
    expect(resolveNseCashSession(weekday(15 * 60 + 14)).isGreenOpen).toBe(true);
    expect(resolveNseCashSession(weekday(15 * 60 + 15)).isGreenOpen).toBe(false);
    expect(resolveNseCashSession(weekday(15 * 60 + 30)).isGreenOpen).toBe(false);
  });

  it("does not treat 15:20 or 15:30 as Closed", () => {
    expect(resolveNseCashSession(weekday(15 * 60 + 20)).phase).not.toBe("closed");
    expect(resolveNseCashSession(weekday(15 * 60 + 30)).phase).toBe("cas");
    expect(resolveNseCashSession(weekday(15 * 60 + 30)).label).toBe("CAS");
  });

  it("does not invent September 2026 consultation copy", () => {
    const session = resolveNseCashSession(weekday(15 * 60 + 20));
    expect(session.title).not.toMatch(/consult/i);
    expect(session.title).not.toMatch(/September 2026/i);
    expect(NSE_CASH_TIMELINE_NOTE).not.toMatch(/consult/i);
  });
});

describe("tooltip / title windows (as of Aug 2026)", () => {
  it("uses the locked CAS tooltip", () => {
    expect(formatNseCashSessionTitle("cas")).toBe(
      "CAS · 15:15–15:35 (as of Aug 2026)",
    );
    expect(resolveNseCashSession(weekday(15 * 60 + 20)).title).toBe(
      "CAS · 15:15–15:35 (as of Aug 2026)",
    );
  });

  it("titles every chip with its window", () => {
    expect(formatNseCashSessionTitle("continuous")).toBe(
      "Continuous · 09:15–15:15 (as of Aug 2026)",
    );
    expect(formatNseCashSessionTitle("matching")).toBe(
      "Matching · 15:35–15:50 (as of Aug 2026)",
    );
    expect(formatNseCashSessionTitle("post-close")).toBe(
      "Post-close · 15:50–16:00 (as of Aug 2026)",
    );
    expect(formatNseCashSessionTitle("closed")).toMatch(/as of Aug 2026/);
    expect(CAS_SCHEDULE_NOTE).toBe("as of Aug 2026");
  });
});

describe("F&O secondary chip", () => {
  it("shows F&O open · till 15:40 after cash continuous ends and before 15:40", () => {
    expect(resolveNseCashSession(weekday(15 * 60 + 15)).foSecondary).toBe(
      "F&O open · till 15:40",
    );
    expect(resolveNseCashSession(weekday(15 * 60 + 35)).foSecondary).toBe(
      "F&O open · till 15:40",
    );
    expect(resolveNseCashSession(weekday(15 * 60 + 39)).foSecondary).toBe(
      "F&O open · till 15:40",
    );
  });

  it("hides the secondary chip during Continuous and after F&O close", () => {
    expect(resolveNseCashSession(weekday(12 * 60)).foSecondary).toBeNull();
    expect(resolveNseCashSession(weekday(15 * 60 + 40)).foSecondary).toBeNull();
    expect(resolveNseCashSession(weekday(16 * 60)).foSecondary).toBeNull();
  });

  it("never implies cash continuous after 15:15 via the secondary chip", () => {
    const session = resolveNseCashSession(weekday(15 * 60 + 20));
    expect(session.label).not.toMatch(/continuous/i);
    expect(session.foSecondary).toBe("F&O open · till 15:40");
  });
});

describe("Market Clock timeline copy", () => {
  it("states the full CAS-aware cash timeline and the non-CAS CTS note", () => {
    expect(NSE_CASH_TIMELINE_NOTE).toContain("Continuous (~09:15–15:15)");
    expect(NSE_CASH_TIMELINE_NOTE).toContain("CAS 15:15–15:35");
    expect(NSE_CASH_TIMELINE_NOTE).toMatch(/Match/);
    expect(NSE_CASH_TIMELINE_NOTE).toContain("Post-close 15:50–16:00");
    expect(NSE_CASH_TIMELINE_NOTE).toContain("Non-CAS cash still CTS to 15:30");
    expect(NSE_CASH_TIMELINE_NOTE).not.toMatch(/Market open until 15:30/);
    expect(NSE_CASH_TIMELINE_NOTE).not.toMatch(/VWAP last 30 min/);
  });
});
