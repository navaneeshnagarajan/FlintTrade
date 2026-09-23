import { describe, expect, it } from "vitest";
import { classifyOperatorSignals } from "../operatorIncident";
import { brokerSurfaceLabel, chatSurfaceLabel, decisionSurfaceLabel } from "../deskStatus";

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
