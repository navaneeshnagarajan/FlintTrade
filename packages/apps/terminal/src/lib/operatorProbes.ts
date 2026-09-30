/**
 * Thin probes for the operator incident model.
 *
 * Signed-out liveness is `GET /api/v1/ping`. That answer is status, a
 * timestamp, and the Laya heartbeat — no component, version, or path
 * detail. `/health` is the HealthMonitor one-liner and is read only when a
 * session token is already in memory. A 401 or 403 on that read is not a
 * host fault; the probe falls back to ping. The edge/CDN probe fetches the
 * public site and the install script. A throw on either, while
 * `/api/v1/ping` is ok, is edge/CDN — not a vendor outage and not a broker
 * outage. A separate neutral fetch is the public-internet probe for
 * network_local. Chat uses the advisor chrome, not a background LLM test.
 */

import { getBase } from "@/services/ftApi.helpers";
import { useAuthStore } from "@/stores/authStore";
import { transportReasonFromError } from "@/lib/operatorTransport";
import type { TransportReason } from "@/lib/operatorIncident";
import {
  EDGE_PROBE_URLS,
  INSTALL_PROBE_URL,
  PUBLIC_INTERNET_PROBE_URL,
  PUBLIC_SITE_PROBE_URL,
} from "@/lib/operatorProbeUrls";

export {
  EDGE_PROBE_URLS,
  INSTALL_PROBE_URL,
  PUBLIC_INTERNET_PROBE_URL,
  PUBLIC_SITE_PROBE_URL,
};

export function operatorProbesEnabled(): boolean {
  return import.meta.env.MODE !== "test";
}

export type LayaHeartbeat = "ready" | "degraded" | "down";

export interface PingProbe {
  localPing: "ok" | "transport" | "http_error";
  transportReason: TransportReason | null;
  /** Null when the heartbeat did not name Laya. Never implied Ready. */
  laya: LayaHeartbeat | null;
}

export function layaHeartbeatFromBody(body: unknown): LayaHeartbeat | null {
  if (body === null || typeof body !== "object") return null;
  const value = (body as { laya?: unknown }).laya;
  if (value === "ready" || value === "degraded" || value === "down") return value;
  return null;
}

export async function probeLocalPing(fetchImpl: typeof fetch = fetch): Promise<PingProbe> {
  try {
    const resp = await fetchImpl(`${getBase()}/api/v1/ping`, { method: "GET", cache: "no-store" });
    if (!resp.ok) return { localPing: "http_error", transportReason: null, laya: null };
    const body: unknown = await resp.json().catch(() => null);
    return { localPing: "ok", transportReason: null, laya: layaHeartbeatFromBody(body) };
  } catch (err) {
    return { localPing: "transport", transportReason: transportReasonFromError(err), laya: null };
  }
}

export type DeskHealth = "healthy" | "degraded" | "unhealthy" | "unknown";

function sessionBearer(): string | null {
  const token = useAuthStore.getState().token;
  if (!token || token === "demo-user" || token === "dev-bypass") return null;
  return token;
}

export async function probeDeskHealth(
  fetchImpl: typeof fetch = fetch,
): Promise<DeskHealth> {
  const token = sessionBearer();
  if (token) {
    const primary = await readDeskHealth(`${getBase()}/health`, fetchImpl, token);
    if (primary !== "unauthorised") return primary;
  }
  const ping = await probeLocalPing(fetchImpl);
  if (ping.localPing === "ok") return "healthy";
  if (ping.localPing === "http_error") return "unhealthy";
  return "unknown";
}

async function readDeskHealth(
  url: string,
  fetchImpl: typeof fetch,
  token: string,
): Promise<DeskHealth | "unauthorised"> {
  try {
    const resp = await fetchImpl(url, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (resp.status === 401 || resp.status === 403) return "unauthorised";
    const body: unknown = await resp.json().catch(() => null);
    const status = healthStatusField(body);
    if (status === "ok" || status === "healthy") return "healthy";
    if (status === "degraded") return "degraded";
    if (status === "error" || status === "unhealthy") return "unhealthy";
    if (!resp.ok && resp.status >= 500) return "unhealthy";
    return resp.ok ? "healthy" : "unknown";
  } catch {
    return "unknown";
  }
}

function healthStatusField(body: unknown): string {
  if (body === null || typeof body !== "object") return "";
  const record = body as { status?: unknown; overall_status?: unknown };
  if (typeof record.overall_status === "string") return record.overall_status;
  if (typeof record.status === "string") return record.status;
  return "";
}

export async function probePublicSite(fetchImpl: typeof fetch = fetch): Promise<"ok" | "unreachable"> {
  for (const url of EDGE_PROBE_URLS) {
    try {
      await fetchImpl(url, { mode: "no-cors", cache: "no-store" });
    } catch {
      return "unreachable";
    }
  }
  return "ok";
}

export async function probePublicInternet(fetchImpl: typeof fetch = fetch): Promise<"ok" | "unreachable"> {
  try {
    await fetchImpl(PUBLIC_INTERNET_PROBE_URL, { mode: "no-cors", cache: "no-store" });
    return "ok";
  } catch {
    return "unreachable";
  }
}
