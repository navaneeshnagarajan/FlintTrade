import { describe, expect, it } from "vitest";
import {
  MUHURAT_FUNDS_NOTE,
  equitySessionWindow,
  foSessionState,
  foSessionWindow,
  muhuratAmoNote,
  muhuratEquityPhase,
  muhuratFundsNote,
  shippedMuhuratHolidays,
} from "../muhuratSession";

function ist(hour: number, minute: number): Date {
  const utcMs = Date.UTC(2026, 10, 8, hour, minute, 0, 0) - (5 * 60 + 30) * 60 * 1000;
  return new Date(utcMs);
}

const shipped = shippedMuhuratHolidays();

describe("F&O Muhurat session on 8 Nov 2026", () => {
  it("is open during 14:20–15:40 IST for F&O and closes equity at 15:30", () => {
    expect(foSessionState(ist(14, 20), shipped)).toBe("open");
    expect(foSessionState(ist(15, 0))).toBe("open");
    expect(foSessionState(ist(15, 40), shipped)).toBe("open");
    expect(foSessionWindow(ist(15, 0), shipped)?.closeMin).toBe(15 * 60 + 40);
    expect(equitySessionWindow(ist(15, 0), shipped)?.closeMin).toBe(15 * 60 + 30);
    expect(muhuratEquityPhase(ist(15, 0), shipped)).toBe("continuous");
    expect(muhuratEquityPhase(ist(15, 16), shipped)).toBe("non-cas");
    expect(muhuratEquityPhase(ist(15, 22), shipped)).toBe("cas");
    expect(muhuratEquityPhase(ist(15, 40), shipped)).toBe("closed");
  });

  it("is closed outside that window on the same Sunday", () => {
    expect(ist(12, 0).getUTCDay()).toBe(0);
    expect(foSessionState(ist(10, 0), shipped)).toBe("closed");
    expect(foSessionState(ist(14, 10), shipped)).toBe("closed");
    expect(foSessionState(ist(14, 19), shipped)).toBe("closed");
    expect(foSessionState(ist(15, 41), shipped)).toBe("closed");
    expect(foSessionState(ist(18, 30), shipped)).toBe("closed");
  });

  it("fails closed when special-session data is absent", () => {
    expect(foSessionState(ist(15, 0), [])).toBe("absent");
    expect(muhuratAmoNote(ist(14, 0), [])).toBeNull();
    expect(muhuratFundsNote(ist(15, 0), [])).toBeNull();
  });

  it("aligns after-market-order and funds notes with the window", () => {
    const early = muhuratAmoNote(ist(14, 0), shipped);
    expect(early).toContain("14:02 IST, 3 minutes before pre-open");
    expect(early).toContain("14:16 IST, 4 minutes before the 14:20 normal open");
    expect(early).toContain("14:03 IST, 2 minutes before the 14:05 equity pre-open");

    expect(muhuratAmoNote(ist(14, 3), shipped)).toContain("pre-open have closed");
    expect(muhuratAmoNote(ist(14, 10), shipped)).toContain(
      "Equity after-market orders for the Muhurat session have closed",
    );
    expect(muhuratAmoNote(ist(14, 17), shipped)).toBe(
      "After-market orders for the Muhurat session have closed. F&O opens at 14:20 IST.",
    );
    expect(muhuratAmoNote(ist(15, 0), shipped)).toBeNull();
    expect(muhuratAmoNote(ist(16, 0), shipped)).toBeNull();

    expect(muhuratFundsNote(ist(15, 0), shipped)).toBe(MUHURAT_FUNDS_NOTE);
    expect(muhuratFundsNote(ist(14, 0), shipped)).toBeNull();
    expect(muhuratFundsNote(ist(15, 41), shipped)).toBeNull();
    expect(MUHURAT_FUNDS_NOTE).toContain("6 November 2026");
    expect(MUHURAT_FUNDS_NOTE).toContain("not included in available funds");
    expect(MUHURAT_FUNDS_NOTE).toContain("settlement holiday");
  });
});
