import { describe, expect, it } from "vitest";
import { fromIstParts } from "@/lib/ist";
import { getTimeContext } from "./DailyWelcome";

describe("desk greeting", () => {
  it("drops the market line before the cash open", () => {
    const ctx = getTimeContext(fromIstParts(2026, 8, 10, 8, 0));
    expect(ctx?.greeting).toBe("Good morning");
    expect(ctx?.message).toBe("");
    expect(ctx?.message).not.toMatch(/market/i);
  });

  it("drops the market line after the cash close", () => {
    const ctx = getTimeContext(fromIstParts(2026, 8, 10, 18, 0));
    expect(ctx?.greeting).toBe("Good afternoon");
    expect(ctx?.message).not.toMatch(/market/i);
  });

  it("drops the weekend market line", () => {
    const ctx = getTimeContext(fromIstParts(2026, 7, 15, 11, 0));
    expect(ctx?.greeting).toBe("Happy weekend");
    expect(ctx?.message).toBe("");
  });
});
