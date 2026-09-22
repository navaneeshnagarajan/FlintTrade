/**
 * Thin probes for the operator incident model.
 *
 * Local ping and `/api/v1/health` are the desk. The public-site fetch is the
 * only edge signal we have: an opaque success means the browser reached
 * flinttrade.vercel.app; a throw means it did not. We do not treat that as a
 * broker outage, and we do not poll it on a tight loop.
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

export async function probeDeskHealth(
  fetchImpl: typeof fetch = fetch,
): Promise<"healthy" | "degraded" | "unhealthy" | "unknown"> {
  try {
    const resp = await fetchImpl(`${getBase()}/api/v1/health`, { cache: "no-store" });
    if (!resp.ok && resp.status >= 500) return "unhealthy";
    const body: unknown = await resp.json().catch(() => null);
    const status = body !== null && typeof body === "object" && "status" in body
      ? String((body as { status: unknown }).status)
      : "";
    if (status === "ok" || status === "healthy") return "healthy";
    if (status === "degraded") return "degraded";
    if (status === "error" || status === "unhealthy") return "unhealthy";
    return resp.ok ? "healthy" : "unknown";
  } catch {
    return "unknown";
  }
}

export async function probePublicSite(fetchImpl: typeof fetch = fetch): Promise<"ok" | "unreachable"> {
  try {
    await fetchImpl(PUBLIC_SITE_PROBE_URL, { mode: "no-cors", cache: "no-store" });
    return "ok";
  } catch {
    return "unreachable";
  }
}
