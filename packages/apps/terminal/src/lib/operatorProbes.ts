/**
 * Thin probes for the operator incident model.
 *
 * Local ping and `/health` are the desk. `/health` is the HealthMonitor
 * one-liner (`status`: healthy, degraded, unhealthy). A 401 or 403 is not
 * a host fault — the probe falls back to the auth-exempt `/api/v1/health`
 * aggregator. The edge/CDN probe fetches the public site and the install
 * script. A throw on either, while `/api/v1/ping` is ok, is edge/CDN — not
 * a vendor outage and not a broker outage. A separate neutral fetch is the
 * public-internet probe for network_local. Chat uses the advisor chrome,
 * not a background LLM test.
 */

import { getBase } from "@/services/ftApi.helpers";
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
  /** Live-facing status. Null when the heartbeat did not name Laya. Never implied Ready. */
  laya: LayaHeartbeat | null;
  /** Sidecar status for Practice. Null when the heartbeat omitted it. */
  layaPractice: LayaHeartbeat | null;
  /** True only when the heartbeat says Live is qualified. */
  layaLiveQualified: boolean;
  /** Machine-readable sidecar reason. Null when the heartbeat omitted a known code. */
  layaReason: string | null;
  /** Sidecar port from the heartbeat. 8000 when the field is absent. */
  layaPort: number;
}

const LAYA_REASON_CODES = new Set([
  "not_started",
  "stopped",
  "port_in_use",
  "still_loading",
  "unreachable",
  "wrong_revision",
  "unverified",
  "identity_absent",
  "key_rejected",
]);

function layaStatusValue(value: unknown): LayaHeartbeat | null {
  if (value === "ready" || value === "degraded" || value === "down") return value;
  return null;
}

export function layaHeartbeatFromBody(body: unknown): LayaHeartbeat | null {
  if (body === null || typeof body !== "object") return null;
  return layaStatusValue((body as { laya?: unknown }).laya);
}

export function layaPracticeFromBody(body: unknown): LayaHeartbeat | null {
  if (body === null || typeof body !== "object") return null;
  return layaStatusValue((body as { laya_practice?: unknown }).laya_practice);
}

export function layaLiveQualifiedFromBody(body: unknown): boolean {
  if (body === null || typeof body !== "object") return false;
  return (body as { laya_live_qualified?: unknown }).laya_live_qualified === true;
}

export function layaReasonFromBody(body: unknown): string | null {
  if (body === null || typeof body !== "object") return null;
  const value = (body as { laya_reason?: unknown }).laya_reason;
  if (typeof value !== "string" || !LAYA_REASON_CODES.has(value)) return null;
  return value;
}

export function layaPortFromBody(body: unknown): number {
  if (body === null || typeof body !== "object") return 8000;
  const value = (body as { laya_port?: unknown }).laya_port;
  if (typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 65535) return value;
  return 8000;
}

export async function probeLocalPing(fetchImpl: typeof fetch = fetch): Promise<PingProbe> {
  try {
    const resp = await fetchImpl(`${getBase()}/api/v1/ping`, { method: "GET", cache: "no-store" });
    if (!resp.ok) {
      return {
        localPing: "http_error",
        transportReason: null,
        laya: null,
        layaPractice: null,
        layaLiveQualified: false,
        layaReason: null,
        layaPort: 8000,
      };
    }
    const body: unknown = await resp.json().catch(() => null);
    return {
      localPing: "ok",
      transportReason: null,
      laya: layaHeartbeatFromBody(body),
      layaPractice: layaPracticeFromBody(body),
      layaLiveQualified: layaLiveQualifiedFromBody(body),
      layaReason: layaReasonFromBody(body),
      layaPort: layaPortFromBody(body),
    };
  } catch (err) {
    return {
      localPing: "transport",
      transportReason: transportReasonFromError(err),
      laya: null,
      layaPractice: null,
      layaLiveQualified: false,
      layaReason: null,
      layaPort: 8000,
    };
  }
}

export type DeskHealth = "healthy" | "degraded" | "unhealthy" | "unknown";

export async function probeDeskHealth(
  fetchImpl: typeof fetch = fetch,
): Promise<DeskHealth> {
  const primary = await readDeskHealth(`${getBase()}/health`, fetchImpl);
  if (primary !== "unauthorised") return primary;
  const fallback = await readDeskHealth(`${getBase()}/api/v1/health`, fetchImpl);
  return fallback === "unauthorised" ? "unknown" : fallback;
}

async function readDeskHealth(
  url: string,
  fetchImpl: typeof fetch,
): Promise<DeskHealth | "unauthorised"> {
  try {
    const resp = await fetchImpl(url, { cache: "no-store" });
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
