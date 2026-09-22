/**
 * Thin probes for the operator incident model.
 *
 * Local ping and `/health` are the desk. `/health` is the HealthMonitor
 * one-liner (`status`: healthy, degraded, unhealthy). A 401 or 403 is not
 * a host fault — the probe falls back to the auth-exempt `/api/v1/health`
 * aggregator. The public-site fetch is the only edge signal: an opaque
 * success means the browser reached the public site; a throw means it did
 * not. That is a CDN/edge miss, not a broker outage, and it is not polled
 * on a tight loop. Chat uses the advisor chrome, not a background LLM test.
 */

import { getBase } from "@/services/ftApi.helpers";
import { transportReasonFromError } from "@/lib/operatorTransport";
import type { TransportReason } from "@/lib/operatorIncident";

export const PUBLIC_SITE_PROBE_URL = "https://flinttrade.vercel.app/";

export function operatorProbesEnabled(): boolean {
  return import.meta.env.MODE !== "test";
}

export interface PingProbe {
  localPing: "ok" | "transport" | "http_error";
  transportReason: TransportReason | null;
}

export async function probeLocalPing(fetchImpl: typeof fetch = fetch): Promise<PingProbe> {
  try {
    const resp = await fetchImpl(`${getBase()}/api/v1/ping`, { method: "GET", cache: "no-store" });
    if (!resp.ok) return { localPing: "http_error", transportReason: null };
    return { localPing: "ok", transportReason: null };
  } catch (err) {
    return { localPing: "transport", transportReason: transportReasonFromError(err) };
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
  try {
    await fetchImpl(PUBLIC_SITE_PROBE_URL, { mode: "no-cors", cache: "no-store" });
    return "ok";
  } catch {
    return "unreachable";
  }
}
