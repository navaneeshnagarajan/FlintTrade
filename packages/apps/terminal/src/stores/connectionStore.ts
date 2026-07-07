import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type { StateCreator } from "zustand";
import type { ConnectionStatus } from "@/types/stores";
import type { WsFailure } from "@/services/websocket";

interface ConnectionStore {
  host: string;
  apiKey: string;
  wsUrl: string;
  status: ConnectionStatus;
  wsConnected: boolean;
  /**
   * Most recent WebSocket failure surfaced by the WS service — null when
   * healthy. `kind: "auth"` lets the connection chrome show "Authentication
   * failed" (with the server's reason) instead of a bare "Disconnected".
   */
  wsFailure: WsFailure | null;
  lastPing: number | null;
  demo: boolean;
  setStatus: (status: ConnectionStatus) => void;
  setWsConnected: (connected: boolean) => void;
  setWsFailure: (failure: WsFailure | null) => void;
  setConfig: (config: { host?: string; apiKey?: string; wsUrl?: string }) => void;
  setLastPing: (timestamp: number) => void;
  setDemo: (v: boolean) => void;
}

// SECURITY: do not seed connection values from Vite env vars. Vite inlines
// `VITE_*` values into the production JS bundle at build time, which is the
// wrong source of truth for an installable desktop app. Users configure
// OpenAlgo/native broker access through Setup or Settings; the backend then
// persists those choices to the OS workspace. This store is only a volatile
// runtime cache hydrated from the backend; it must not keep a second writable
// copy of broker credentials in browser storage.
const storeImpl: StateCreator<ConnectionStore> = (set) => ({
  host: "",
  apiKey: "",
  wsUrl: "",
  status: "disconnected",
  wsConnected: false,
  wsFailure: null,
  lastPing: null,
  demo: false,
  setStatus: (status) => set({ status }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  setWsFailure: (wsFailure) => set({ wsFailure }),
  setConfig: (config) => set((state) => ({ ...state, ...config })),
  setLastPing: (lastPing) => set({ lastPing }),
  setDemo: (demo) => set({ demo }),
});

try {
  sessionStorage.removeItem("flinttrade:connection");
} catch {
  // Non-browser test/runtime environment.
}

export const useConnectionStore = import.meta.env.DEV
  ? create<ConnectionStore>()(devtools(storeImpl, { name: "connection" }))
  : create<ConnectionStore>()(storeImpl);
