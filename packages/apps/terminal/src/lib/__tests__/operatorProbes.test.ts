import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import {
  INSTALL_PROBE_URL,
  layaCheckingFromBody,
  layaManagedFromBody,
  layaRouteFromBody,
  layaHeartbeatFromBody,
  layaLiveQualifiedFromBody,
  layaPortFromBody,
  layaPracticeFromBody,
  layaDownloadProgressFromBody,
  layaReasonFromBody,
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
    expect(layaPracticeFromBody({ laya_practice: "ready" })).toBe("ready");
    expect(layaPracticeFromBody({ laya: "down" })).toBeNull();
    expect(layaLiveQualifiedFromBody({ laya_live_qualified: true })).toBe(true);
    expect(layaLiveQualifiedFromBody({ laya_live_qualified: false })).toBe(false);
    expect(layaLiveQualifiedFromBody({ status: "ok" })).toBe(false);
    expect(layaReasonFromBody({ laya_reason: "still_loading" })).toBe("still_loading");
    expect(layaReasonFromBody({ laya_reason: "downloading" })).toBe("downloading");
    expect(layaReasonFromBody({ laya_reason: "download_failed" })).toBe("download_failed");
    expect(layaDownloadProgressFromBody({
      laya_download_bytes: 1_200_000_000,
      laya_download_total: 3_400_000_000,
    })).toEqual({ done: 1_200_000_000, total: 3_400_000_000 });
    expect(layaDownloadProgressFromBody({ status: "ok" })).toEqual({ done: null, total: null });
    expect(layaReasonFromBody({ laya_reason: "stopped" })).toBe("stopped");
    expect(layaReasonFromBody({ laya_reason: "port_in_use" })).toBe("port_in_use");
    expect(layaReasonFromBody({ laya_reason: "unverified" })).toBe("unverified");
    expect(layaReasonFromBody({ laya_reason: "identity_absent" })).toBeNull();
    expect(layaReasonFromBody({ laya_reason: "key_rejected" })).toBe("key_rejected");
    expect(layaReasonFromBody({ laya_reason: "key_missing" })).toBe("key_missing");
    expect(layaReasonFromBody({ laya_reason: "booting" })).toBeNull();
    expect(layaReasonFromBody({ status: "ok" })).toBeNull();
    expect(layaPortFromBody({ laya_port: 8123 })).toBe(8123);
    expect(layaPortFromBody({ status: "ok" })).toBe(8000);
    expect(layaCheckingFromBody({ laya_checking: true })).toBe(true);
    expect(layaCheckingFromBody({ laya_checking: false })).toBe(false);
    expect(layaCheckingFromBody({ laya_checking: "true" })).toBe(false);
    expect(layaCheckingFromBody({ status: "ok" })).toBe(false);
    expect(layaCheckingFromBody(null)).toBe(false);
    expect(layaRouteFromBody({ laya_route: "ollama" })).toBe("ollama");
    expect(layaRouteFromBody({ laya_route: "sidecar" })).toBeNull();
    expect(layaRouteFromBody({ status: "ok" })).toBeNull();
    expect(layaManagedFromBody({ laya_managed: true })).toBe(true);
    expect(layaManagedFromBody({ laya_managed: false })).toBe(false);
    expect(layaManagedFromBody({ laya_managed: "true" })).toBe(false);
  });

  it("treats a missing laya_checking field as not checking", async () => {
    const checking = vi.fn(async () => jsonResponse({ status: "ok", laya_checking: true }, 200));
    await expect(probeLocalPing(asFetch(checking))).resolves.toMatchObject({ layaChecking: true });
    const sidecar = vi.fn(async () => jsonResponse({ status: "ok", laya: "down" }, 200));
    await expect(probeLocalPing(asFetch(sidecar))).resolves.toMatchObject({
      layaChecking: false,
      layaRoute: null,
      layaManaged: false,
    });
    const ollama = vi.fn(async () => jsonResponse({
      status: "ok",
      laya_route: "ollama",
      laya_managed: true,
      laya_checking: false,
    }, 200));
    await expect(probeLocalPing(asFetch(ollama))).resolves.toMatchObject({
      layaRoute: "ollama",
      layaManaged: true,
      layaChecking: false,
    });
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
