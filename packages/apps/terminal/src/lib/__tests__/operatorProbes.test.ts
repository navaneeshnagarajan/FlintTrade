import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
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
  beforeEach(() => {
    useAuthStore.getState().setLoggedOut();
  });

  it("uses the public ping when no session is present", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toMatch(/\/api\/v1\/ping$/);
      return jsonResponse({ status: "ok", laya: "down" }, 200);
    });
    await expect(probeDeskHealth(asFetch(fetchImpl))).resolves.toBe("healthy");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("keeps a degraded /health 503 as degraded when a session exists", async () => {
    useAuthStore.getState().setLoggedIn("session-jwt", "nav", "");
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toMatch(/\/health$/);
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer session-jwt");
      return jsonResponse({ status: "degraded" }, 503);
    });
    await expect(probeDeskHealth(asFetch(fetchImpl))).resolves.toBe("degraded");
  });

  it("falls back to ping when /health rejects the session", async () => {
    useAuthStore.getState().setLoggedIn("session-jwt", "nav", "");
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/v1/ping")) return jsonResponse({ status: "ok" }, 200);
      return new Response("no", { status: 401 });
    });
    await expect(probeDeskHealth(asFetch(fetchImpl))).resolves.toBe("healthy");
    expect(fetchImpl.mock.calls.some(([url]) => String(url).includes("/api/v1/health"))).toBe(false);
  });

  it("reads overall_status when a signed-in desk returned that field", async () => {
    useAuthStore.getState().setLoggedIn("session-jwt", "nav", "");
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
