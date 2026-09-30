import { describe, expect, it } from "vitest";
import { classifyOperatorSignals } from "../operatorIncident";
import {
  brokerSurfaceLabel,
  chatSurfaceLabel,
  decisionSurfaceLabel,
  summariseDeskStatus,
} from "../deskStatus";

describe("desk status surfaces", () => {
  it("keeps broker, Laya, and LLM on separate labels", () => {
    const incident = classifyOperatorSignals({
      feedDisconnected: false,
      localPing: "ok",
      transportReason: null,
      health: "healthy",
      publicSite: "ok",
      publicInternet: "unknown",
      nativeHttpFreeze: false,
      brokerRateLimited: false,
      brokerReject: null,
      activeAccount: null,
      wsFailure: null,
      llmChrome: "ready",
      decisionStatus: "down",
      sessionClockClosed: false,
    });
    expect(brokerSurfaceLabel({
      connected: true,
      connectedRead: false,
      incident,
    })).toBe("Connected");
    expect(decisionSurfaceLabel("down")).toBe("Down");
    expect(chatSurfaceLabel("ready")).toBe("Connected (suggest only)");
    expect(chatSurfaceLabel("ready")).not.toBe(decisionSurfaceLabel("down"));
  });

  it("shows Chat as not configured until a provider is connected", () => {
    expect(chatSurfaceLabel(null)).toBe("Not configured");
    expect(chatSurfaceLabel("unconfigured")).toBe("Not configured");
  });

  it("names Degraded without treating it as Down", () => {
    expect(decisionSurfaceLabel("degraded")).toBe("Degraded");
    expect(decisionSurfaceLabel("ready")).toBe("Ready");
  });

  it("treats a missing Laya heartbeat as Degraded", () => {
    expect(decisionSurfaceLabel(null)).toBe("Degraded");
    expect(decisionSurfaceLabel(undefined)).toBe("Degraded");
    expect(decisionSurfaceLabel(null)).not.toBe("Ready");
  });
});

describe("summariseDeskStatus", () => {
  const ready = { broker: "Connected", decision: "Ready" as const, chat: "Connected (suggest only)" };

  it("keeps Example data neutral even though nothing is connected", () => {
    expect(summariseDeskStatus({ mode: "explore", broker: "Unavailable", decision: "Down", chat: "Not configured" }))
      .toEqual({ tone: "neutral", label: "Example data only" });
  });

  it("puts a down Laya first", () => {
    expect(summariseDeskStatus({ ...ready, mode: "practice", decision: "Down" }))
      .toEqual({ tone: "down", label: "Laya down" });
  });

  it("treats a missing broker as normal in Practice and as the first fix in Live", () => {
    expect(summariseDeskStatus({ ...ready, mode: "practice", broker: "Unavailable" }).tone).toBe("ok");
    expect(summariseDeskStatus({ ...ready, mode: "live", broker: "Unavailable" }))
      .toEqual({ tone: "down", label: "No broker connected" });
  });

  it("separates blocked and degraded broker incidents", () => {
    expect(summariseDeskStatus({ ...ready, mode: "live", broker: "Unavailable — order path" }).tone).toBe("down");
    expect(summariseDeskStatus({ ...ready, mode: "live", broker: "Degraded — rate limit" }))
      .toEqual({ tone: "warn", label: "Broker degraded" });
  });

  it("warns on a failing LLM but stays quiet when it is simply not configured", () => {
    expect(summariseDeskStatus({ ...ready, mode: "practice", chat: "Error" }).tone).toBe("warn");
    expect(summariseDeskStatus({ ...ready, mode: "practice", chat: "Not configured" }))
      .toEqual({ tone: "ok", label: "All systems ready" });
  });
});
