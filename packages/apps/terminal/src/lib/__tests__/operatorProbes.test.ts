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
    expect(layaHeartbeatFromBody({ status: "ok", decision_model: "ready" })).toBe("ready");
    expect(layaHeartbeatFromBody({ status: "ok", decision_model: "degraded" })).toBe("degraded");
    expect(layaHeartbeatFromBody({ status: "ok", decision_model: "down" })).toBe("down");
    expect(layaHeartbeatFromBody({ status: "ok" })).toBeNull();
    expect(layaHeartbeatFromBody({ decision_model: "connected" })).toBeNull();
    expect(layaHeartbeatFromBody(null)).toBeNull();
    expect(layaPracticeFromBody({ decision_model_practice: "ready" })).toBe("ready");
    expect(layaPracticeFromBody({ decision_model: "down" })).toBeNull();
    expect(layaLiveQualifiedFromBody({ decision_model_live_qualified: true })).toBe(true);
    expect(layaLiveQualifiedFromBody({ decision_model_live_qualified: false })).toBe(false);
    expect(layaLiveQualifiedFromBody({ status: "ok" })).toBe(false);
    expect(layaReasonFromBody({ decision_model_reason: "still_loading" })).toBe("still_loading");
    expect(layaReasonFromBody({ decision_model_reason: "downloading" })).toBe("downloading");
    expect(layaReasonFromBody({ decision_model_reason: "download_failed" })).toBe("download_failed");
    expect(layaDownloadProgressFromBody({
      decision_model_download_bytes: 1_200_000_000,
      decision_model_download_total: 3_400_000_000,
    })).toEqual({ done: 1_200_000_000, total: 3_400_000_000 });
    expect(layaDownloadProgressFromBody({ status: "ok" })).toEqual({ done: null, total: null });
    expect(layaReasonFromBody({ decision_model_reason: "stopped" })).toBe("stopped");
    expect(layaReasonFromBody({ decision_model_reason: "port_in_use" })).toBe("port_in_use");
    expect(layaReasonFromBody({ decision_model_reason: "unverified" })).toBe("unverified");
    expect(layaReasonFromBody({ decision_model_reason: "identity_absent" })).toBeNull();
    expect(layaReasonFromBody({ decision_model_reason: "key_rejected" })).toBe("key_rejected");
    expect(layaReasonFromBody({ decision_model_reason: "key_missing" })).toBe("key_missing");
    expect(layaReasonFromBody({ decision_model_reason: "booting" })).toBeNull();
    expect(layaReasonFromBody({ status: "ok" })).toBeNull();
    expect(layaPortFromBody({ decision_model_port: 8123 })).toBe(8123);
    expect(layaPortFromBody({ status: "ok" })).toBe(8000);
    expect(layaCheckingFromBody({ decision_model_checking: true })).toBe(true);
    expect(layaCheckingFromBody({ decision_model_checking: false })).toBe(false);
    expect(layaCheckingFromBody({ decision_model_checking: "true" })).toBe(false);
    expect(layaCheckingFromBody({ status: "ok" })).toBe(false);
    expect(layaCheckingFromBody(null)).toBe(false);
    expect(layaRouteFromBody({ decision_model_route: "ollama" })).toBe("ollama");
    expect(layaRouteFromBody({ decision_model_route: "sidecar" })).toBeNull();
    expect(layaRouteFromBody({ status: "ok" })).toBeNull();
    expect(layaManagedFromBody({ decision_model_managed: true })).toBe(true);
    expect(layaManagedFromBody({ decision_model_managed: false })).toBe(false);
    expect(layaManagedFromBody({ decision_model_managed: "true" })).toBe(false);
  });

  it("treats a missing laya_checking field as not checking", async () => {
    const checking = vi.fn(async () => jsonResponse({ status: "ok", decision_model_checking: true }, 200));
    await expect(probeLocalPing(asFetch(checking))).resolves.toMatchObject({ layaChecking: true });
    const sidecar = vi.fn(async () => jsonResponse({ status: "ok", decision_model: "down" }, 200));
    await expect(probeLocalPing(asFetch(sidecar))).resolves.toMatchObject({
      layaChecking: false,
      layaRoute: null,
      layaManaged: false,
    });
    const ollama = vi.fn(async () => jsonResponse({
      status: "ok",
      decision_model_route: "ollama",
      decision_model_managed: true,
      decision_model_checking: false,
    }, 200));
    await expect(probeLocalPing(asFetch(ollama))).resolves.toMatchObject({
      layaRoute: "ollama",
      layaManaged: true,
      layaChecking: false,
    });
  });

  it("confirms backend identity only from a valid successful Laya heartbeat", async () => {
    for (const body of [
      { status: "ok", decision_model: "down" },
      { status: "ok", decision_model: "ready", decision_model_route: "ollama", decision_model_managed: false },
      { status: "ok", decision_model: "down", decision_model_route: "ollama", decision_model_managed: true },
    ]) {
      await expect(probeLocalPing(asFetch(async () => jsonResponse(body, 200))))
        .resolves.toMatchObject({ localPing: "ok", layaHeartbeatValid: true });
    }
  });

  it.each([
    null,
    [],
    {},
    { status: "ok" },
    { status: "ok", decision_model: "connected" },
    { status: "error", decision_model: "ready" },
    { status: "ok", decision_model: "ready", decision_model_route: "unknown" },
    { status: "ok", decision_model: "ready", decision_model_route: null },
    { status: "ok", decision_model: "ready", decision_model_route: "ollama" },
    { status: "ok", decision_model: "ready", decision_model_route: "ollama", decision_model_managed: "true" },
  ].map((body) => [body]))("does not invent heartbeat authority from invalid HTTP 200 body %j", async (body) => {
    await expect(probeLocalPing(asFetch(async () => jsonResponse(body, 200))))
      .resolves.toMatchObject({ localPing: "ok", layaHeartbeatValid: false });
  });

  it("does not confirm backend identity after HTTP, JSON, or transport failures", async () => {
    for (const fetchImpl of [
      asFetch(async () => jsonResponse({ status: "ok", decision_model: "ready" }, 503)),
      asFetch(async () => new Response("not json", { status: 200 })),
      asFetch(async () => { throw new Error("failed to fetch"); }),
    ]) {
      await expect(probeLocalPing(fetchImpl)).resolves.toMatchObject({
        layaHeartbeatValid: false,
        laya: null,
      });
    }
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
      return jsonResponse({ status: "ok", decision_model: "down" }, 200);
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
