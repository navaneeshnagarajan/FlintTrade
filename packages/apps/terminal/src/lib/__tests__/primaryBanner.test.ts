import { describe, expect, it } from "vitest";
import {
  FEED_DISCONNECTED_BANNER,
  LIVE_RISK_BANNER,
  primaryBannerCopy,
  selectPrimaryBanner,
} from "../primaryBanner";

describe("incident banner under the Mode line", () => {
  it("Explore never takes the incident slot", () => {
    expect(
      selectPrimaryBanner({
        mode: "explore",
        liveRiskActive: true,
        feedDisconnected: true,
      }),
    ).toBeNull();
  });

  it("Practice never takes the incident slot", () => {
    expect(selectPrimaryBanner({ mode: "practice", feedDisconnected: true })).toBeNull();
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

  it("Live feed disconnect is the fallback incident", () => {
    expect(
      selectPrimaryBanner({
        mode: "live",
        liveRiskActive: false,
        feedDisconnected: true,
      }),
    ).toBe("feed_disconnected");
    expect(primaryBannerCopy("feed_disconnected")).toBe(FEED_DISCONNECTED_BANNER);
  });

  it("Live with no risk and a connected feed has no incident banner", () => {
    expect(
      selectPrimaryBanner({
        mode: "live",
        liveRiskActive: false,
        feedDisconnected: false,
      }),
    ).toBeNull();
  });
});
