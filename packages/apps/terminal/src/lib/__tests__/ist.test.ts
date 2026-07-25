/**
 * ist.test.ts — the IST time/date module.
 *
 * Every case pins a FIXED instant and asserts a FIXED expectation, so the suite
 * proves the same thing whatever timezone the machine (or the CI runner) is set
 * to. Nothing here reads the host clock or the host zone.
 */

import { describe, it, expect, vi, afterEach } from "vitest";

import {
  IST_OFFSET_MINUTES,
  fmtDuration,
  fmtIstClock,
  fromIstParts,
  istMinutes,
  istNow,
  istParts,
  istToday,
  splitDuration,
  toIstIsoDate,
} from "../ist";

/**
 * 2026-07-25 20:30 UTC — late evening across Europe, and 02:00 IST on the
 * NEXT day (Sunday 26 July). The UTC calendar day and the IST calendar day
 * disagree here, which is the whole point of the module.
 */
const IST_EVENING_ROLLOVER = new Date("2026-07-25T20:30:00Z");

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("IST_OFFSET_MINUTES", () => {
  it("is UTC+05:30, the fixed offset India observes all year", () => {
    expect(IST_OFFSET_MINUTES).toBe(330);
  });
});

describe("istParts", () => {
  it("reads the IST wall clock of a fixed instant", () => {
    expect(istParts(new Date("2026-07-25T04:05:06Z"))).toEqual({
      year: 2026,
      month: 6, // July
      day: 25,
      hour: 9,
      minute: 35,
      second: 6,
      weekday: 6, // Saturday
    });
  });

  it("carries the date forward when the +05:30 shift crosses midnight", () => {
    // 20:30 UTC on Saturday the 25th is 02:00 IST on Sunday the 26th.
    expect(istParts(IST_EVENING_ROLLOVER)).toMatchObject({
      year: 2026,
      month: 6,
      day: 26,
      hour: 2,
      minute: 0,
      weekday: 0, // Sunday
    });
  });

  it("defaults to now", () => {
    vi.setSystemTime(IST_EVENING_ROLLOVER);
    expect(istParts()).toEqual(istParts(IST_EVENING_ROLLOVER));
  });

  it("never consults the host's timezone offset", () => {
    // The module must be pure epoch arithmetic. If it ever reached for the
    // browser's own zone, the terminal would show a different trading day to
    // every operator.
    const spy = vi.spyOn(Date.prototype, "getTimezoneOffset");
    istParts(IST_EVENING_ROLLOVER);
    istMinutes(IST_EVENING_ROLLOVER);
    toIstIsoDate(IST_EVENING_ROLLOVER);
    fromIstParts(2026, 6, 25, 15, 30);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("istMinutes", () => {
  it("counts minutes since IST midnight", () => {
    // 09:15 IST — the NSE open.
    expect(istMinutes(new Date("2026-07-25T03:45:00Z"))).toBe(9 * 60 + 15);
  });

  it("carries seconds as a fraction so progress bars move smoothly", () => {
    expect(istMinutes(new Date("2026-07-25T03:45:30Z"))).toBeCloseTo(555.5, 6);
  });

  it("wraps back towards zero after IST midnight", () => {
    // 01:00 IST — inside the US session, which closes at 25:30.
    expect(istMinutes(new Date("2026-07-25T19:30:00Z"))).toBe(60);
  });
});

describe("toIstIsoDate / istToday", () => {
  it("REGRESSION: returns the IST trading day, not the UTC day", () => {
    // The bug this replaces: both calendars derived "today" from
    // `toISOString().slice(0, 10)`, which is the UTC calendar day. At this
    // instant that is still the 25th while India has already moved to the 26th,
    // so today's events lost their "Today" heading and rendered as past.
    expect(IST_EVENING_ROLLOVER.toISOString().slice(0, 10)).toBe("2026-07-25");
    expect(toIstIsoDate(IST_EVENING_ROLLOVER)).toBe("2026-07-26");
  });

  it("istToday reads the IST day from the current instant", () => {
    vi.setSystemTime(IST_EVENING_ROLLOVER);
    expect(istToday()).toBe("2026-07-26");
  });

  it("holds the IST day steady through the UTC rollover", () => {
    // 23:00 UTC and 01:00 UTC straddle UTC midnight but sit inside one IST day.
    expect(toIstIsoDate(new Date("2026-07-25T23:00:00Z"))).toBe("2026-07-26");
    expect(toIstIsoDate(new Date("2026-07-26T01:00:00Z"))).toBe("2026-07-26");
  });
});

describe("istNow", () => {
  it("spells out the current IST wall clock in its UTC fields", () => {
    vi.setSystemTime(IST_EVENING_ROLLOVER);
    const shifted = istNow();
    expect(shifted.getUTCFullYear()).toBe(2026);
    expect(shifted.getUTCDate()).toBe(26);
    expect(shifted.getUTCHours()).toBe(2);
  });

  it("is offset from the real instant by exactly the IST offset", () => {
    vi.setSystemTime(IST_EVENING_ROLLOVER);
    expect(istNow().getTime() - IST_EVENING_ROLLOVER.getTime()).toBe(
      IST_OFFSET_MINUTES * 60_000,
    );
  });
});

describe("fromIstParts", () => {
  it("builds the real instant of an IST wall-clock reading", () => {
    // 15:30 IST — the NSE close — is 10:00 UTC.
    expect(fromIstParts(2026, 6, 30, 15, 30).toISOString()).toBe("2026-07-30T10:00:00.000Z");
  });

  it("round-trips through istParts", () => {
    const instant = fromIstParts(2026, 11, 31, 15, 30, 45);
    expect(istParts(instant)).toMatchObject({
      year: 2026,
      month: 11,
      day: 31,
      hour: 15,
      minute: 30,
      second: 45,
    });
  });

  it("rolls day overflow into the next month, so `day + 7` steps a week", () => {
    // 30 July + 7 days = 6 August.
    expect(toIstIsoDate(fromIstParts(2026, 6, 30 + 7, 15, 30))).toBe("2026-08-06");
  });

  it("defaults to IST midnight", () => {
    expect(fromIstParts(2026, 6, 26).toISOString()).toBe("2026-07-25T18:30:00.000Z");
  });
});

describe("fmtIstClock", () => {
  it("renders a zero-padded 24-hour IST clock", () => {
    expect(fmtIstClock(new Date("2026-07-25T04:05:06Z"))).toBe("09:35:06");
  });

  it("renders IST midnight as 00, not 24", () => {
    expect(fmtIstClock(new Date("2026-07-25T18:30:00Z"))).toBe("00:00:00");
  });
});

describe("splitDuration", () => {
  it("decomposes a duration into days, hours, minutes and seconds", () => {
    const ms = ((3 * 24 + 4) * 60 + 12) * 60_000 + 30_000;
    expect(splitDuration(ms)).toEqual({
      days: 3,
      hours: 4,
      minutes: 12,
      seconds: 30,
      totalMs: ms,
    });
  });

  it("clamps a negative duration to zero", () => {
    expect(splitDuration(-5_000)).toMatchObject({ days: 0, hours: 0, minutes: 0, seconds: 0 });
  });
});

describe("fmtDuration", () => {
  it("drops units as they empty", () => {
    expect(fmtDuration(((3 * 24 + 4) * 60 + 12) * 60_000)).toBe("3d 04h 12m");
    expect(fmtDuration((4 * 60 + 12) * 60_000)).toBe("4h 12m");
    expect(fmtDuration(12 * 60_000 + 30_000)).toBe("12m 30s");
    expect(fmtDuration(30_000)).toBe("30s");
  });

  it("keeps the seconds field for expiry countdowns", () => {
    expect(fmtDuration((4 * 60 + 12) * 60_000 + 30_000, { withSeconds: true }))
      .toBe("04h 12m 30s");
    expect(fmtDuration(30_000, { withSeconds: true })).toBe("00h 00m 30s");
  });

  it("renders a negative or zero duration as 0s", () => {
    expect(fmtDuration(-1)).toBe("0s");
    expect(fmtDuration(0)).toBe("0s");
  });
});
