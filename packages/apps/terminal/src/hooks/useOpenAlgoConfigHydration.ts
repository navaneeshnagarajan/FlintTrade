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

export function applyOpenAlgoConfigToConnectionCache(
  data: OpenAlgoConfigData,
  options: { preserveApiKey?: boolean } = {},
): void {
  const current = useConnectionStore.getState();
  const host = String(data.host ?? "");
  const wsPort = String(data.ws_port ?? "8765");
  useConnectionStore.getState().setConfig({
    host,
    apiKey: options.preserveApiKey === false ? "" : current.apiKey,
    wsUrl: deriveOpenAlgoWsUrl(host, wsPort),
  });
}

export function useOpenAlgoConfigHydration(): void {
  useEffect(() => {
    let cancelled = false;
    void readOpenAlgoConfig()
      .then((payload) => {
        if (cancelled || payload.status !== "success") return;
        applyOpenAlgoConfigToConnectionCache(payload.data ?? {});
      })
      .catch((err) => {
        console.warn("[openalgo] failed to hydrate connection cache:", err);
      });

    return () => { cancelled = true; };
  }, []);
}
