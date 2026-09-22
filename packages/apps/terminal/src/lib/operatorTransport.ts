import type { TransportReason } from "@/lib/operatorIncident";

export function transportReasonFromError(err: unknown): TransportReason {
  const message = (err instanceof Error ? err.message : String(err)).toLowerCase();
  if (message.includes("enotfound") || message.includes("getaddrinfo") || message.includes("dns")) {
    return "dns";
  }
  if (message.includes("etimedout") || message.includes("timed out") || message.includes("timeout")) {
    return "timeout";
  }
  if (message.includes("econnrefused") || message.includes("connection refused")) {
    return "connection_refused";
  }
  return "failed_fetch";
}
