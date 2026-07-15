import { describe, expect, it } from "vitest";

import { resolveAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";

describe("resolveAccountReadsEnabled", () => {
  it("keeps Explore on its labelled sample feed", () => {
    expect(resolveAccountReadsEnabled("explore", false)).toBe(false);
    expect(resolveAccountReadsEnabled("explore", true)).toBe(false);
  });

  it("reads the local sandbox in Practice without a broker connection", () => {
    expect(resolveAccountReadsEnabled("practice", false)).toBe(true);
    expect(resolveAccountReadsEnabled("practice", true)).toBe(true);
  });

  it("requires a connected broker for Live account reads", () => {
    expect(resolveAccountReadsEnabled("live", false)).toBe(false);
    expect(resolveAccountReadsEnabled("live", true)).toBe(true);
  });
});
