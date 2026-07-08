import { useEffect } from "react";
import { readOpenAlgoConfig, type OpenAlgoConfigData } from "@/services/ftApi.openalgo";
import { useConnectionStore } from "@/stores/connectionStore";

export function deriveOpenAlgoWsUrl(host: string, wsPort: string): string {
  if (!host.trim()) return "";
  try {
    const parsed = new URL(host);
    const protocol = parsed.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${parsed.hostname}:${wsPort || "8765"}`;
  } catch {
    return `ws://127.0.0.1:${wsPort || "8765"}`;
  }
}

export function openAlgoRestPortFromHost(host: string): string {
  try {
    return new URL(host).port || "";
  } catch {
    return "";
  }
}

export function openAlgoWsPortFromUrl(wsUrl: string): string {
  try {
    const wsUrlObj = new URL(wsUrl.replace(/^ws/, "http"));
    return wsUrlObj.port || "8765";
  } catch {
    return "8765";
  }
}

export function applyOpenAlgoConfigToConnectionCache(data: OpenAlgoConfigData): void {
  const current = useConnectionStore.getState();
  const host = String(data.host ?? "");
  const wsPort = String(data.ws_port ?? "8765");
  // Rehydrate the raw bridge apiKey from the loopback GET. The connection store
  // is memory-only (never persisted to browser storage), so the key is
  // re-fetched fresh over loopback on every load rather than kept in the
  // browser — that memory-only property is deliberate and must stay. When the
  // backend omits api_key (a partial response), preserve whatever is already in
  // memory instead of clobbering it with "".
  const apiKey = "api_key" in data ? String(data.api_key ?? "") : current.apiKey;
  current.setConfig({
    host,
    apiKey,
    wsUrl: deriveOpenAlgoWsUrl(host, wsPort),
  });
}

/** Attempts before the hydration gate is left latched-closed (fail-closed). */
const MAX_HYDRATION_ATTEMPTS = 5;

export function useOpenAlgoConfigHydration(): void {
  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const scheduleRetry = (): void => {
      attempt += 1;
      // Give up after a bounded number of tries. `openAlgoHydrated` stays false,
      // so live-order routing keeps failing closed — a genuinely unreachable
      // backend would fail the order fetch anyway, and never opening the gate is
      // safer than opening it on an empty apiKey and misrouting a live order.
      if (attempt >= MAX_HYDRATION_ATTEMPTS) return;
      retryTimer = setTimeout(hydrate, Math.min(1000 * attempt, 5000));
    };

    const hydrate = (): void => {
      void readOpenAlgoConfig()
        .then((payload) => {
          if (cancelled) return;
          if (payload.status !== "success") {
            scheduleRetry();
            return;
          }
          applyOpenAlgoConfigToConnectionCache(payload.data ?? {});
          // Open the routing gate only after a successful read has rehydrated
          // the raw apiKey, so live-order routing fails closed during the async
          // hydration window instead of diverting an order on an empty apiKey.
          useConnectionStore.getState().setOpenAlgoHydrated(true);
        })
        .catch((err) => {
          if (cancelled) return;
          console.warn("[openalgo] failed to hydrate connection cache:", err);
          scheduleRetry();
        });
    };

    hydrate();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, []);
}
