import { afterEach, describe, expect, it } from "vitest";

import { formatExchangeClock } from "./exchangeClock";

const originalZone = process.env.TZ;

describe("formatExchangeClock", () => {
  afterEach(() => {
    if (originalZone === undefined) delete process.env.TZ;
    else process.env.TZ = originalZone;
  });

  it("labels 14:18:05 IST when the machine zone is New York", () => {
    process.env.TZ = "America/New_York";
    const date = new Date("2026-01-15T08:48:05.000Z");
    expect(formatExchangeClock(date)).toBe("14:18:05 IST");
    const local = new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }).format(date);
    expect(local).toBe("03:48:05");
  });
});
