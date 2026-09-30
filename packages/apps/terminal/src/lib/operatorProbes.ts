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
  /** Bytes received while `layaReason` is `downloading`. Null otherwise. */
  layaDownloadBytes: number | null;
  /** Bytes expected while `layaReason` is `downloading`. Null otherwise. */
  layaDownloadTotal: number | null;
}

const LAYA_REASON_CODES = new Set([
  "not_started",
  "stopped",
  "port_in_use",
  "still_loading",
  "downloading",
  "download_failed",
  "unreachable",
  "wrong_revision",
  "unverified",
  "key_rejected",
  "key_missing",
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

function byteCount(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) return null;
  return value;
}

/** Done and total bytes. Both must be present, or both are null. */
export function layaDownloadProgressFromBody(body: unknown): { done: number | null; total: number | null } {
  if (body === null || typeof body !== "object") return { done: null, total: null };
  const record = body as { laya_download_bytes?: unknown; laya_download_total?: unknown };
  const done = byteCount(record.laya_download_bytes);
  const total = byteCount(record.laya_download_total);
  if (done === null || total === null) return { done: null, total: null };
  return { done, total };
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
        layaDownloadBytes: null,
        layaDownloadTotal: null,
      };
    }
    const body: unknown = await resp.json().catch(() => null);
    const progress = layaDownloadProgressFromBody(body);
    return {
      localPing: "ok",
      transportReason: null,
      laya: layaHeartbeatFromBody(body),
      layaPractice: layaPracticeFromBody(body),
      layaLiveQualified: layaLiveQualifiedFromBody(body),
      layaReason: layaReasonFromBody(body),
      layaPort: layaPortFromBody(body),
      layaDownloadBytes: progress.done,
      layaDownloadTotal: progress.total,
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
      layaDownloadBytes: null,
      layaDownloadTotal: null,
    };
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
