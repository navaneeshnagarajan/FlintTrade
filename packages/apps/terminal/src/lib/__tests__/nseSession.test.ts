/**
 * nseSession.test.ts
 *
 * CAS-aware NSE cash session clock (as of Aug 2026).
 * Phase chips are Continuous · CAS · Matching · Post-close · Closed.
 * Cash is never green "open" after 15:15; CAS is not Closed.
 */

import { describe, expect, it } from "vitest";
import {
  CAS_SCHEDULE_NOTE,
  NSE_CASH_TIMELINE_NOTE,
  INDEX_UNDERLYINGS,
  derivativeContractCloseMin,
  formatNseCashSessionTitle,
  nseCashPhaseAtMinutes,
  nseCashSchedule,
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
    expect(formatNseCashSessionTitle("cas", weekday(15 * 60 + 20))).toBe(
      "CAS · 15:15–15:35 (as of Aug 2026)",
    );
    expect(resolveNseCashSession(weekday(15 * 60 + 20)).title).toBe(
      "CAS · 15:15–15:35 (as of Aug 2026)",
    );
  });

  it("titles every chip with its window", () => {
    const on = weekday(12 * 60);
    expect(formatNseCashSessionTitle("continuous", on)).toBe(
      "Continuous · 09:15–15:15 (as of Aug 2026)",
    );
    expect(formatNseCashSessionTitle("matching", on)).toBe(
      "Matching · 15:35–15:50 (as of Aug 2026)",
    );
    expect(formatNseCashSessionTitle("post-close", on)).toBe(
      "Post-close · 15:50–16:00 (as of Aug 2026)",
    );
    expect(formatNseCashSessionTitle("closed", on)).toMatch(/as of Aug 2026/);
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

function onDate(year: number, month: number, day: number, minutes: number): Date {
  const utcMs = Date.UTC(year, month - 1, day, 0, 0, 0, 0) - (5 * 60 + 30) * 60_000;
  return new Date(utcMs + minutes * 60_000);
}

describe("dated cash phase", () => {
  it("requires the session date instead of the pre-revision clock", () => {
    expect(() => nseCashPhaseAtMinutes(15 * 60 + 20, undefined as unknown as Date)).toThrow(
      /session date/,
    );
  });

  it("keeps 15:20 on 6 Dec 2026 in CAS, not green continuous", () => {
    const at = onDate(2026, 12, 6, 15 * 60 + 20);
    expect(nseCashPhaseAtMinutes(15 * 60 + 20, at)).toBe("cas");
    expect(nseCashPhaseAtMinutes(15 * 60 + 20, at)).not.toBe("continuous");
    expect(resolveNseCashSession(at).isGreenOpen).toBe(false);
  });
});

describe("schedule boundary — 6 Dec 2026 keeps today's clock, 7 Dec 2026 uses the revision", () => {
  it("keeps the August 2026 auction and the till 15:40 label on 6 Dec", () => {
    const now = onDate(2026, 12, 6, 15 * 60 + 20);
    const schedule = nseCashSchedule(now);
    expect(schedule.casStart).toBe(15 * 60 + 15);
    expect(schedule.casEnd).toBe(15 * 60 + 35);
    expect(schedule.foClose).toBe(15 * 60 + 40);
    expect(schedule.foSecondaryLabel).toBe("F&O open · till 15:40");
    expect(schedule.timelineNote).toContain("CAS 15:15–15:35");
  });

  it("moves cash continuous to 15:30, the auction to 15:30–15:40, and F&O to 15:45 on 7 Dec", () => {
    const duringAuction = onDate(2026, 12, 7, 15 * 60 + 32);
    const session = resolveNseCashSession(duringAuction);
    expect(session.phase).toBe("cas");
    expect(session.label).toBe("CAS");
    expect(session.title).toBe("CAS · 15:30–15:40 (from 7 Dec 2026)");
    expect(session.isGreenOpen).toBe(false);
    expect(session.foSecondary).toBe("F&O open · till 15:45");

    const stillContinuous = resolveNseCashSession(onDate(2026, 12, 7, 15 * 60 + 20));
    expect(stillContinuous.phase).toBe("continuous");
    expect(stillContinuous.isGreenOpen).toBe(true);
    expect(stillContinuous.foSecondary).toBeNull();

    const matching = resolveNseCashSession(onDate(2026, 12, 7, 15 * 60 + 42));
    expect(matching.phase).toBe("matching");
    expect(matching.title).toBe("Matching · 15:40–15:45 (from 7 Dec 2026)");
    expect(nseCashSchedule(duringAuction).timelineNote).toContain("Match 15:40–15:45");
    expect(matching.foSecondary).toBe("F&O open · till 15:45");

    const transition = resolveNseCashSession(onDate(2026, 12, 7, 15 * 60 + 47));
    expect(transition.phase).toBe("transition");
    expect(transition.title).toBe("Transition · 15:45–15:50 (from 7 Dec 2026)");
    expect(transition.foSecondary).toBeNull();

    const postClose = resolveNseCashSession(onDate(2026, 12, 7, 15 * 60 + 50));
    expect(postClose.phase).toBe("post-close");
    expect(postClose.foSecondary).toBeNull();
  });
});

describe("NFO contract close from 7 Dec 2026", () => {
  const calendar = ["2026-12-10", "2026-12-17"];

  it("closes an expiring index contract at 15:30 and leaves the next index contract until 15:45", () => {
    const expiryDay = onDate(2026, 12, 10, 12 * 60);
    expect(derivativeContractCloseMin(expiryDay, "NIFTY10DEC2624000CE", calendar)).toBe(15 * 60 + 30);
    expect(derivativeContractCloseMin(expiryDay, "NIFTY17DEC2624000CE", calendar)).toBe(15 * 60 + 45);
  });

  it("keeps stock derivatives open until 15:45, including on their expiry day", () => {
    const expiryDay = onDate(2026, 12, 10, 15 * 60 + 40);
    expect(derivativeContractCloseMin(expiryDay, "RELIANCE10DEC26FUT", calendar)).toBe(15 * 60 + 45);
    expect(derivativeContractCloseMin(onDate(2026, 12, 8, 12 * 60), "RELIANCE10DEC26FUT", calendar)).toBe(
      15 * 60 + 45,
    );
  });

  it("reads the expiry on the symbol and fails closed when a calendar does not confirm it", () => {
    const expiryDay = onDate(2026, 12, 10, 12 * 60);
    expect(derivativeContractCloseMin(expiryDay, "NIFTY10DEC2624000CE", undefined)).toBe(15 * 60 + 30);
    expect(derivativeContractCloseMin(expiryDay, "NIFTY17DEC2624000CE", undefined)).toBe(15 * 60 + 45);
    expect(derivativeContractCloseMin(expiryDay, "NIFTY10DEC2624000CE", [])).toBeNull();
    expect(derivativeContractCloseMin(expiryDay, "NIFTY10DEC2624000CE", ["2026-12-17"])).toBeNull();
    expect(derivativeContractCloseMin(expiryDay, "NIFTY", calendar)).toBeNull();
    expect(derivativeContractCloseMin(expiryDay, "NOT A CONTRACT", calendar)).toBeNull();
  });

  it("closes every listed index at 15:30 on its own expiry and rejects the following day", () => {
    const expiryDay = onDate(2026, 12, 10, 12 * 60);
    const nextDay = onDate(2026, 12, 11, 11 * 60);
    const previousDay = onDate(2026, 12, 9, 11 * 60);
    for (const name of INDEX_UNDERLYINGS) {
      const symbol = `${name}10DEC26FUT`;
      expect(derivativeContractCloseMin(expiryDay, symbol, undefined, "NFO")).toBe(15 * 60 + 30);
      expect(derivativeContractCloseMin(expiryDay, symbol, undefined, "BFO")).toBe(15 * 60 + 30);
      expect(derivativeContractCloseMin(previousDay, symbol, undefined, "NFO")).toBe(15 * 60 + 45);
      expect(derivativeContractCloseMin(nextDay, symbol, undefined, "NFO")).toBeNull();
    }
  });

  it("closes an expiring BSE index contract at 15:30 and keeps a stock contract until 15:45", () => {
    const expiryDay = onDate(2026, 12, 10, 12 * 60);
    expect(derivativeContractCloseMin(expiryDay, "SENSEX10DEC2680000CE", calendar, "BFO")).toBe(15 * 60 + 30);
    expect(derivativeContractCloseMin(expiryDay, "RELIANCE10DEC26FUT", calendar, "BFO")).toBe(15 * 60 + 45);
    expect(derivativeContractCloseMin(expiryDay, "SENSEX", calendar, "BFO")).toBeNull();
  });

  it("lets the Muhurat session override an index expiry close", () => {
    expect(
      derivativeContractCloseMin(onDate(2026, 11, 8, 15 * 60), "NIFTY08NOV2624000CE", ["2026-11-08"], "NFO"),
    ).toBe(15 * 60 + 40);
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
