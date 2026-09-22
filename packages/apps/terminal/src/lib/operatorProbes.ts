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

export const PUBLIC_SITE_PROBE_URL = "https://flinttrade.vercel.app/";
export const INSTALL_PROBE_URL = "https://flinttrade.vercel.app/install.sh";
/** Install/update and the public site. Either network failure is edge/CDN. */
export const EDGE_PROBE_URLS = [PUBLIC_SITE_PROBE_URL, INSTALL_PROBE_URL] as const;
/**
 * Neutral public-internet check. Not the product site and not a broker host.
 * A failure while the desk ping is ok is network_local.
 */
export const PUBLIC_INTERNET_PROBE_URL = "https://example.com/";

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
