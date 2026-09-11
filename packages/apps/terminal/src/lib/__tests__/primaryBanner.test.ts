import { describe, expect, it } from "vitest";
import {
  EXPLORE_SAMPLE_BANNER,
  FEED_DISCONNECTED_BANNER,
  LIVE_RISK_BANNER,
  primaryBannerCopy,
  selectPrimaryBanner,
} from "../primaryBanner";

describe("FT-UX-001 primary banner priority", () => {
  it("Explore always wins over live risk and feed disconnected", () => {
    expect(
      selectPrimaryBanner({
        mode: "explore",
        liveRiskActive: true,
        feedDisconnected: true,
      }),
    ).toBe("explore_sample");
    expect(primaryBannerCopy("explore_sample")).toBe(EXPLORE_SAMPLE_BANNER);
  });

  it("Practice shows the simulated-results banner only", () => {
    expect(selectPrimaryBanner({ mode: "practice", feedDisconnected: true })).toBe(
      "practice_sample",
    );
  });

  it("Live risk beats feed disconnected", () => {
    expect(
      selectPrimaryBanner({
        mode: "live",
        liveRiskActive: true,
        feedDisconnected: true,
      }),
    ).toBe("live_risk");
    expect(primaryBannerCopy("live_risk")).toBe(LIVE_RISK_BANNER);
  });

  it("Live feed disconnect is the fallback primary", () => {
    expect(
      selectPrimaryBanner({
        mode: "live",
        liveRiskActive: false,
        feedDisconnected: true,
      }),
    ).toBe("feed_disconnected");
    expect(primaryBannerCopy("feed_disconnected")).toBe(FEED_DISCONNECTED_BANNER);
  });

  it("Live with no risk and a connected feed has no primary banner", () => {
    expect(
      selectPrimaryBanner({
        mode: "live",
        liveRiskActive: false,
        feedDisconnected: false,
      }),
    ).toBeNull();
  });
});
