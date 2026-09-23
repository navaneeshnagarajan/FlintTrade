import { describe, expect, it, vi } from "vitest";
import {
  INSTALL_PROBE_URL,
  layaHeartbeatFromBody,
  probeDeskHealth,
  probeLocalPing,
  probePublicInternet,
  probePublicSite,
  PUBLIC_INTERNET_PROBE_URL,
} from "../operatorProbes";

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function asFetch(
  impl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
): typeof fetch {
  return impl as typeof fetch;
}

describe("Laya heartbeat on desk ping", () => {
  it("reads Ready, Degraded, or Down and treats a missing field as unknown", () => {
    expect(layaHeartbeatFromBody({ status: "ok", laya: "ready" })).toBe("ready");
    expect(layaHeartbeatFromBody({ status: "ok", laya: "degraded" })).toBe("degraded");
    expect(layaHeartbeatFromBody({ status: "ok", laya: "down" })).toBe("down");
    expect(layaHeartbeatFromBody({ status: "ok" })).toBeNull();
    expect(layaHeartbeatFromBody({ laya: "connected" })).toBeNull();
    expect(layaHeartbeatFromBody(null)).toBeNull();
  });

  it("does not present Ready when ping fails or omits Laya", async () => {
    const missing = vi.fn(async () => jsonResponse({ status: "ok" }, 200));
    await expect(probeLocalPing(asFetch(missing))).resolves.toMatchObject({
      localPing: "ok",
      laya: null,
    });
    const failed = vi.fn(async () => {
      throw new Error("failed to fetch");
    });
    await expect(probeLocalPing(asFetch(failed))).resolves.toMatchObject({
      localPing: "transport",
      laya: null,
    });
  });
});

describe("desk health probe", () => {
  it("keeps a degraded /health 503 as degraded", async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL) => jsonResponse({ status: "degraded" }, 503));
    await expect(probeDeskHealth(asFetch(fetchImpl))).resolves.toBe("degraded");
    expect(String(fetchImpl.mock.calls[0]?.[0])).toMatch(/\/health$/);
  });

  it("does not treat an unauthenticated /health as unhealthy", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/v1/health")) return jsonResponse({ status: "error" }, 200);
      return new Response("no", { status: 401 });
    });
    await expect(probeDeskHealth(asFetch(fetchImpl))).resolves.toBe("unhealthy");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(String(fetchImpl.mock.calls[1]?.[0])).toContain("/api/v1/health");
  });

  it("reads overall_status when that is the field the desk returned", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ overall_status: "unhealthy" }, 503));
    await expect(probeDeskHealth(asFetch(fetchImpl))).resolves.toBe("unhealthy");
  });
});

describe("edge/CDN and public-internet probes", () => {
  it("treats an install fetch failure as a public-site miss", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === INSTALL_PROBE_URL) throw new Error("failed to fetch");
      return new Response(null, { status: 200 });
    });
    await expect(probePublicSite(asFetch(fetchImpl))).resolves.toBe("unreachable");
  });

  it("probes a neutral host for the public internet, not the product site", async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL) => new Response(null, { status: 200 }));
    await expect(probePublicInternet(asFetch(fetchImpl))).resolves.toBe("ok");
    expect(String(fetchImpl.mock.calls[0]?.[0])).toBe(PUBLIC_INTERNET_PROBE_URL);
    expect(PUBLIC_INTERNET_PROBE_URL).not.toContain("flinttrade.vercel.app");
    expect(PUBLIC_INTERNET_PROBE_URL).not.toContain("dhan");
  });

  it("reports the public internet unreachable when that fetch throws", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("getaddrinfo ENOTFOUND");
    });
    await expect(probePublicInternet(asFetch(fetchImpl))).resolves.toBe("unreachable");
  });
});
