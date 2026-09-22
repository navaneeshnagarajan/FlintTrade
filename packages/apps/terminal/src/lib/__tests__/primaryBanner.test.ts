import { describe, expect, it } from "vitest";
import { classifyOperatorSignals, type OperatorSignals } from "../operatorIncident";
import {
  FEED_DISCONNECTED_BANNER,
  LIVE_RISK_BANNER,
  primaryBannerCopy,
  selectPrimaryBanner,
} from "../primaryBanner";

function closedHost(): OperatorSignals {
  return {
    feedDisconnected: true,
    localPing: "ok",
    transportReason: null,
    health: "unhealthy",
    publicSite: "ok",
    publicInternet: "unknown",
    nativeHttpFreeze: false,
    brokerRateLimited: false,
    brokerReject: null,
    activeAccount: null,
    wsFailure: null,
    llmChrome: "ready",
    sessionClockClosed: false,
  };
}

describe("FT-UX-001 primary banner priority", () => {
  it("Explore leaves the incident slot empty", () => {
    expect(
      selectPrimaryBanner({
        mode: "explore",
        liveRiskActive: true,
        feedDisconnected: true,
      }),
    ).toBeNull();
  });

  it("Practice leaves the incident slot empty", () => {
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

  it("a money-path incident outranks a disconnected feed, and Live risk still wins", () => {
    const incident = classifyOperatorSignals(closedHost());
    expect(incident?.failureClass).toBe("host_unhealthy");
    expect(
      selectPrimaryBanner({
        mode: "live",
        liveRiskActive: false,
        feedDisconnected: true,
        incident,
      }),
    ).toBe("host_unhealthy");
    expect(
      selectPrimaryBanner({
        mode: "live",
        liveRiskActive: true,
        feedDisconnected: true,
        incident,
      }),
    ).toBe("live_risk");
    expect(
      selectPrimaryBanner({
        mode: "explore",
        liveRiskActive: true,
        feedDisconnected: true,
        incident,
      }),
    ).toBeNull();
  });

  it("Chat and a public-site outage do not hide a disconnected feed", () => {
    const llm = classifyOperatorSignals({ ...closedHost(), health: "healthy", llmChrome: "error" });
    expect(llm?.failureClass).toBe("llm_provider");
    expect(
      selectPrimaryBanner({
        mode: "live",
        feedDisconnected: true,
        incident: llm,
      }),
    ).toBe("feed_disconnected");
    const edge = classifyOperatorSignals({
      ...closedHost(),
      health: "healthy",
      publicSite: "unreachable",
      localPing: "ok",
    });
    expect(edge?.failureClass).toBe("edge");
    expect(
      selectPrimaryBanner({
        mode: "live",
        feedDisconnected: true,
        incident: edge,
      }),
    ).toBe("feed_disconnected");
  });

  it("a broker-trust incident outranks a disconnected feed and loses to Live risk", () => {
    const incident = classifyOperatorSignals({
      ...closedHost(),
      health: "healthy",
      brokerRateLimited: true,
    });
    expect(incident?.failureClass).toBe("broker_rate_limit");
    expect(
      selectPrimaryBanner({
        mode: "live",
        feedDisconnected: true,
        incident,
      }),
    ).toBe("broker_rate_limit");
    expect(
      selectPrimaryBanner({
        mode: "live",
        liveRiskActive: true,
        feedDisconnected: true,
        incident,
      }),
    ).toBe("live_risk");
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
