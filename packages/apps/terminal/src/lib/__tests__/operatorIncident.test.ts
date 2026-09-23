import { describe, expect, it } from "vitest";
import { killAllArmed } from "@/routes/killAllGate";
import { mirrorStartArmed } from "@/routes/mirrorStartGate";
import {
  brokerSessionDarkened,
  classifyObservedFailure,
  classifyOperatorSignals,
  EDGE_STATUS_LINKS,
  honestBrokerStatus,
  liveWritesMuted,
  type OperatorSignals,
} from "../operatorIncident";

function signals(overrides: Partial<OperatorSignals> = {}): OperatorSignals {
  return {
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
    sessionClockClosed: false,
    ...overrides,
  };
}

const MONEY_PATH_FIXTURES: Array<{ name: string; signals: OperatorSignals }> = [
  {
    name: "exchange",
    signals: signals({
      brokerReject: {
        message: "Trading halted by exchange circuit breaker",
        httpStatus: 400,
        broker: "dhan",
      },
    }),
  },
  {
    name: "broker_auth",
    signals: signals({
      activeAccount: {
        broker: "dhan",
        status: "token_expired",
        errorMessage: "token expired",
        readSmokeOk: true,
        needsRelogin: true,
      },
    }),
  },
  {
    name: "broker_rest",
    signals: signals({
      brokerReject: {
        message: "Broker REST bad gateway",
        httpStatus: 502,
        broker: "dhan",
      },
    }),
  },
  {
    name: "broker_stream",
    signals: signals({
      activeAccount: {
        broker: "dhan",
        status: "connected",
        errorMessage: null,
        readSmokeOk: true,
        needsRelogin: false,
      },
      wsFailure: { kind: "network", reason: "socket closed" },
    }),
  },
  {
    name: "broker_rate_limit",
    signals: signals({ brokerRateLimited: true }),
  },
  {
    name: "broker_maintenance",
    signals: signals({
      activeAccount: {
        broker: "kotakneo",
        status: "error",
        errorMessage: "Broker under maintenance",
        readSmokeOk: false,
        needsRelogin: false,
      },
    }),
  },
  {
    name: "host_unhealthy",
    signals: signals({ health: "unhealthy", localPing: "ok" }),
  },
  {
    name: "network_local",
    signals: signals({
      localPing: "ok",
      publicInternet: "unreachable",
      publicSite: "unreachable",
    }),
  },
];

describe("operator incident classifier", () => {
  it.each(MONEY_PATH_FIXTURES)(
    "$name darkens Connected, mutes Live writes, and names the class plus rectify",
    ({ name, signals: fixture }) => {
      const incident = classifyOperatorSignals(fixture);
      expect(incident).not.toBeNull();
      expect(incident?.failureClass).toBe(name);
      expect(incident?.moneyPath).toBe(true);
      expect(incident?.level === "degraded" || incident?.level === "blocked").toBe(true);
      expect(liveWritesMuted(incident)).toBe(true);
      expect(incident?.rectify.length).toBeGreaterThan(0);
      expect(incident?.headline.toLowerCase()).toContain(incident?.plainClass.toLowerCase() ?? "");

      const chrome = honestBrokerStatus({
        connected: true,
        connectedRead: true,
        nativeMonday: true,
        incident,
      });
      expect(chrome).not.toMatch(/Connected/);
      expect(chrome === "Unavailable" || chrome?.startsWith("Unavailable —") || chrome?.startsWith("Degraded —")).toBe(
        true,
      );
    },
  );

  it("does not invent an exchange halt from the session clock", () => {
    expect(classifyOperatorSignals(signals({ sessionClockClosed: true }))).toBeNull();
  });

  it("does not invent a Neo stream incident", () => {
    const incident = classifyOperatorSignals(
      signals({
        activeAccount: {
          broker: "kotakneo",
          status: "connected",
          errorMessage: null,
          readSmokeOk: true,
          needsRelogin: false,
        },
        wsFailure: { kind: "network", reason: "socket closed" },
      }),
    );
    expect(incident?.failureClass).not.toBe("broker_stream");
  });

  it("keeps an edge outage off the money path when the desk ping is ok", () => {
    const incident = classifyOperatorSignals(
      signals({ publicSite: "unreachable", localPing: "ok" }),
    );
    expect(incident?.failureClass).toBe("edge");
    expect(incident?.plainClass).toBe("edge/CDN");
    expect(incident?.headline).toBe("Public site/CDN unreachable");
    expect(incident?.level).toBe("info");
    expect(incident?.moneyPath).toBe(false);
    expect(liveWritesMuted(incident)).toBe(false);
    expect(incident?.headline.toLowerCase()).not.toContain("cloudflare");
    expect(incident?.rectify.toLowerCase()).not.toContain("cloudflare");
    expect(EDGE_STATUS_LINKS.map((link) => link.href)).toEqual([
      "https://www.cloudflarestatus.com/",
      "https://www.vercel-status.com/",
    ]);
    expect(
      honestBrokerStatus({
        connected: true,
        connectedRead: true,
        nativeMonday: false,
        incident,
      }),
    ).toBe("Connected (read)");
  });

  it("does not paint network_local when the process itself did not answer", () => {
    const incident = classifyOperatorSignals(
      signals({
        localPing: "transport",
        transportReason: "timeout",
        publicSite: "unreachable",
        publicInternet: "unreachable",
        health: "unknown",
      }),
    );
    expect(incident?.failureClass).toBe("backend_unreachable");
  });

  it("paints network_local only when the process is up and the public internet failed", () => {
    const incident = classifyOperatorSignals(
      signals({
        localPing: "ok",
        publicInternet: "unreachable",
        publicSite: "unreachable",
      }),
    );
    expect(incident?.failureClass).toBe("network_local");
    expect(incident?.moneyPath).toBe(true);
  });

  it("keeps a site/CDN miss as edge/CDN when the public internet probe is still ok", () => {
    const incident = classifyOperatorSignals(
      signals({
        localPing: "ok",
        publicSite: "unreachable",
        publicInternet: "ok",
      }),
    );
    expect(incident?.failureClass).toBe("edge");
    expect(incident?.plainClass).toBe("edge/CDN");
  });

  it("does not invent network_local from a single broker timeout", () => {
    const incident = classifyOperatorSignals(
      signals({
        localPing: "ok",
        publicInternet: "ok",
        publicSite: "ok",
        brokerReject: {
          message: "Broker request timed out",
          httpStatus: null,
          broker: "dhan",
        },
      }),
    );
    expect(incident?.failureClass).not.toBe("network_local");
    expect(incident).toBeNull();
  });

  it("treats a same-origin failure with a reachable public site as backend unreachable", () => {
    const incident = classifyOperatorSignals(
      signals({
        localPing: "transport",
        transportReason: "connection_refused",
        publicSite: "ok",
        health: "unknown",
      }),
    );
    expect(incident?.failureClass).toBe("backend_unreachable");
    expect(incident?.moneyPath).toBe(true);
    expect(liveWritesMuted(incident)).toBe(true);
  });

  it("does not invent an ISP fault while the public-site probe is still unknown", () => {
    const incident = classifyOperatorSignals(
      signals({
        localPing: "transport",
        transportReason: "failed_fetch",
        publicSite: "unknown",
        health: "unknown",
      }),
    );
    expect(incident?.failureClass).toBe("backend_unreachable");
    expect(incident?.headline.toLowerCase()).not.toContain("isp");
  });

  it("surfaces the native HTTP freeze as a backend banner without muting the bridge path", () => {
    const incident = classifyOperatorSignals(signals({ nativeHttpFreeze: true }));
    expect(incident?.failureClass).toBe("backend_unreachable");
    expect(incident?.nativeHttpFreeze).toBe(true);
    expect(incident?.moneyPath).toBe(false);
    expect(liveWritesMuted(incident)).toBe(false);
    expect(incident?.rectify.toLowerCase()).toContain("cutover");
    expect(
      honestBrokerStatus({
        connected: true,
        connectedRead: true,
        nativeMonday: true,
        incident,
      }),
    ).toBe("Unavailable — backend unreachable");
    expect(
      honestBrokerStatus({
        connected: true,
        connectedRead: false,
        nativeMonday: false,
        incident,
      }),
    ).toBe("Connected");
  });

  it("closes Live when Laya is Down and leaves the broker Connected", () => {
    const incident = classifyOperatorSignals(signals({
      llmChrome: "ready",
      decisionStatus: "down",
    }));
    expect(incident?.failureClass).toBe("laya");
    expect(incident?.failureClass).not.toBe("llm_provider");
    expect(incident?.level).toBe("blocked");
    expect(incident?.moneyPath).toBe(true);
    expect(incident?.headline).toContain("Laya");
    expect(incident?.headline).not.toContain("Decision");
    expect(incident?.plainClass).toBe("Laya");
    expect(liveWritesMuted(incident)).toBe(true);
    expect(brokerSessionDarkened(incident)).toBe(false);
    expect(
      mirrorStartArmed({
        mode: "live",
        sourceAccount: "native:upstox:U1",
        targetCount: 1,
        activeAccountCount: 2,
        accountsLoadState: "ready",
        liveWriteBlock: incident?.rectify ?? null,
      }),
    ).toBe(false);
    expect(
      killAllArmed({
        mode: "live",
        riskLoadState: "ready",
        hasManagedAccounts: true,
      }),
    ).toBe(true);
    expect(
      honestBrokerStatus({
        connected: true,
        connectedRead: false,
        nativeMonday: false,
        incident,
      }),
    ).toBe("Connected");
  });

  it("lets a connected broker and a ready decision place while Chat is offline", () => {
    const incident = classifyOperatorSignals(signals({
      llmChrome: "disconnected",
      decisionStatus: "ready",
    }));
    expect(incident?.failureClass).toBe("llm_provider");
    expect(liveWritesMuted(incident)).toBe(false);
    expect(
      honestBrokerStatus({
        connected: true,
        connectedRead: false,
        nativeMonday: false,
        incident,
      }),
    ).toBe("Connected");
  });

  it("prefers Laya Down over a Chat incident", () => {
    const incident = classifyOperatorSignals(signals({
      llmChrome: "error",
      decisionStatus: "down",
    }));
    expect(incident?.failureClass).toBe("laya");
    expect(liveWritesMuted(incident)).toBe(true);
  });

  it("does not close Live when Laya is only Degraded", () => {
    expect(classifyOperatorSignals(signals({ decisionStatus: "degraded" }))).toBeNull();
  });

  it("keeps Chat failures off Live writes and off broker Connected", () => {
    const incident = classifyOperatorSignals(signals({ llmChrome: "error" }));
    expect(incident?.failureClass).toBe("llm_provider");
    expect(incident?.moneyPath).toBe(false);
    expect(liveWritesMuted(incident)).toBe(false);
    expect(incident?.rectify.toLowerCase()).toContain("chat");
    expect(
      honestBrokerStatus({
        connected: true,
        connectedRead: true,
        nativeMonday: true,
        incident,
      }),
    ).toBe("Connected (read)");
  });

  it("does not paint an LLM incident for an unconfigured provider", () => {
    expect(classifyOperatorSignals(signals({ llmChrome: "unconfigured" }))).toBeNull();
  });

  it("ranks the freeze banner above a broker rate limit and above Chat, and still closes Live", () => {
    const incident = classifyOperatorSignals(
      signals({
        nativeHttpFreeze: true,
        llmChrome: "disconnected",
        brokerRateLimited: true,
      }),
    );
    expect(incident?.failureClass).toBe("backend_unreachable");
    expect(incident?.nativeHttpFreeze).toBe(true);
    expect(incident?.muteBrokerSmoke).toBe(true);
    expect(incident?.moneyPath).toBe(true);
    expect(liveWritesMuted(incident)).toBe(true);
    expect(
      honestBrokerStatus({
        connected: true,
        connectedRead: true,
        nativeMonday: false,
        incident,
      }),
    ).not.toMatch(/Connected/);
  });

  it("ranks host unhealthy above a latched broker rate limit", () => {
    const incident = classifyOperatorSignals(
      signals({ health: "unhealthy", brokerRateLimited: true }),
    );
    expect(incident?.failureClass).toBe("host_unhealthy");
    expect(incident?.muteBrokerSmoke).toBe(true);
    expect(liveWritesMuted(incident)).toBe(true);
  });

  it("mutes further broker smoke only while a rate limit is latched", () => {
    const limited = classifyOperatorSignals(signals({ brokerRateLimited: true }));
    expect(limited?.muteBrokerSmoke).toBe(true);
    expect(classifyOperatorSignals(signals())?.muteBrokerSmoke).not.toBe(true);
  });

  it("classifies a cutover 503 as the native HTTP freeze and ignores market-closed copy", () => {
    expect(
      classifyObservedFailure({
        message: "broker_account_cutover_unavailable",
        httpStatus: 503,
      }),
    ).toEqual({ kind: "freeze" });
    expect(
      classifyObservedFailure({
        message: "Market closed for this session",
        httpStatus: 400,
      }),
    ).toBeNull();
    expect(
      classifyObservedFailure({
        message: "host unhealthy",
        httpStatus: 503,
      })?.kind,
    ).toBe("reject");
    expect(
      classifyObservedFailure({
        message: "Cannot reach the FlintTrade backend",
        httpStatus: null,
      }),
    ).toMatchObject({ kind: "reject", failureClass: "backend_unreachable" });
    expect(
      classifyObservedFailure({
        message: "Internal server error",
        httpStatus: 500,
      }),
    ).toBeNull();
    expect(
      classifyObservedFailure({
        message: "Too many requests",
        httpStatus: 429,
      }),
    ).toBeNull();
    expect(
      classifyObservedFailure({
        message: "Broker REST bad gateway",
        httpStatus: 502,
      }, "order"),
    ).toMatchObject({ kind: "reject", failureClass: "broker_rest" });
  });

  it("keeps a real exchange reject when the session clock is also closed", () => {
    const incident = classifyOperatorSignals(
      signals({
        sessionClockClosed: true,
        brokerReject: {
          message: "Trading halted by exchange circuit breaker",
          httpStatus: 400,
          broker: "dhan",
        },
      }),
    );
    expect(incident?.failureClass).toBe("exchange");
  });
});
