import { useCallback, useEffect, useState } from "react";
import { Wifi } from "lucide-react";
import { getHealth } from "@/services/ftApi";
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
  const directBrokerConnected = useDirectBrokerConnected();

  const [ftStatus, setFtStatus] = useState<ServiceStatus>("unknown");

  const refresh = useCallback(async () => {
    try {
      const h = await getHealth();
      setFtStatus(h.status === "ok" ? "ok" : h.status === "degraded" ? "degraded" : "error");
    } catch {
      setFtStatus("error");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => { void refresh(); }, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const rows: ConnectionRow[] = [
    {
      name: "Broker session",
      status: directBrokerConnected ? "ok" : "degraded",
    },
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
