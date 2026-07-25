/**
 * ConnectionStatusPanel — the connection-layer status roll-up.
 *
 * Extracted from the retired System Health widget (ruling D6, 2026-07-26).
 * Everything else that widget showed was already rendered by Monitoring and
 * Security, but this four-row card — broker session, OpenAlgo bridge,
 * WebSocket, FlintTrade backend — existed nowhere else: ConnectionSection is
 * a credentials FORM, and the status bar shows a single dot. The capability
 * moves here rather than dying with the widget.
 *
 * Data sources:
 *  - ping       → @/services/api (optional OpenAlgo bridge health check)
 *  - getHealth  → @/services/ftApi (FlintTrade backend health)
 *  - useConnectionStore → Zustand (WS connected / status)
 *
 * Auto-refreshes every 30 seconds while mounted.
 */

import { useCallback, useEffect, useState } from "react";
import { Wifi } from "lucide-react";
import { ping } from "@/services/api";
import { getHealth } from "@/services/ftApi";
import { useConnectionStore } from "@/stores/connectionStore";
import { useDirectBrokerConnected } from "@/hooks/useBrokerConnected";

const REFRESH_INTERVAL_MS = 30_000;

type ServiceStatus = "ok" | "degraded" | "error" | "unknown";

interface ConnectionRow {
  name: string;
  status: ServiceStatus;
  latencyMs?: number | null;
}

function statusColour(s: ServiceStatus): string {
  switch (s) {
    case "ok":       return "bg-profit";
    case "degraded": return "bg-amber-400";
    case "error":    return "bg-loss";
    default:         return "bg-text-muted";
  }
}

function statusLabel(s: ServiceStatus): string {
  switch (s) {
    case "ok":       return "Online";
    case "degraded": return "Degraded";
    case "error":    return "Down";
    default:         return "Unknown";
  }
}

export function ConnectionStatusPanel() {
  const wsConnected = useConnectionStore((s) => s.wsConnected);
  const connStatus = useConnectionStore((s) => s.status);
  const openAlgoConfigured = useConnectionStore((s) => Boolean(s.apiKey));
  const directBrokerConnected = useDirectBrokerConnected();

  const [openAlgoStatus, setOpenAlgoStatus] = useState<ServiceStatus>("unknown");
  const [openAlgoLatency, setOpenAlgoLatency] = useState<number | null>(null);
  const [ftStatus, setFtStatus] = useState<ServiceStatus>("unknown");

  const refresh = useCallback(async () => {
    // Optional OpenAlgo bridge ping. A live native/gateway broker session
    // keeps the broker layer healthy even with no OpenAlgo key configured.
    const t0 = Date.now();
    try {
      if (!openAlgoConfigured) throw new Error("OpenAlgo API key not configured");
      await ping();
      setOpenAlgoStatus(connStatus === "connected" ? "ok" : "degraded");
      setOpenAlgoLatency(Date.now() - t0);
    } catch {
      setOpenAlgoStatus(directBrokerConnected ? "degraded" : "error");
      setOpenAlgoLatency(null);
    }

    try {
      const h = await getHealth();
      setFtStatus(h.status === "ok" ? "ok" : h.status === "degraded" ? "degraded" : "error");
    } catch {
      setFtStatus("error");
    }
  }, [connStatus, directBrokerConnected, openAlgoConfigured]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => { void refresh(); }, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const rows: ConnectionRow[] = [
    {
      name: "Broker session",
      status: connStatus === "connected" || directBrokerConnected ? "ok" : "degraded",
    },
    { name: "OpenAlgo bridge", status: openAlgoStatus, latencyMs: openAlgoLatency },
    { name: "WebSocket", status: wsConnected ? "ok" : "error" },
    { name: "FlintTrade Backend", status: ftStatus },
  ];

  return (
    <div data-testid="connection-status-panel">
      <div className="flex items-center gap-1.5 mb-2">
        <Wifi size={12} className="text-text-muted" aria-hidden="true" />
        <span className="text-xxs font-sans uppercase tracking-wider text-text-muted">
          Connections
        </span>
      </div>
      <div className="space-y-1.5">
        {rows.map((row) => (
          <div key={row.name} className="flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <span
                className={`inline-block w-2 h-2 rounded-full shrink-0 ${statusColour(row.status)} ${row.status === "ok" ? "animate-pulse" : ""}`}
                aria-hidden="true"
              />
              <span className="text-xs text-text-primary truncate">{row.name}</span>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {row.latencyMs != null && (
                <span className="text-xxs font-mono text-text-muted">
                  {row.latencyMs.toFixed(0)} ms
                </span>
              )}
              <span className="text-xxs text-text-secondary">{statusLabel(row.status)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
