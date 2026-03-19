import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type { StateCreator } from "zustand";
import type { ConnectionStatus } from "@/types/stores";

interface ConnectionStore {
  host: string;
  apiKey: string;
  wsUrl: string;
  status: ConnectionStatus;
  wsConnected: boolean;
  lastPing: number | null;
  setStatus: (status: ConnectionStatus) => void;
  setWsConnected: (connected: boolean) => void;
  setConfig: (config: { host?: string; apiKey?: string; wsUrl?: string }) => void;
  setLastPing: (timestamp: number) => void;
}

const storeImpl: StateCreator<ConnectionStore> = (set) => ({
  host: import.meta.env.VITE_OPENALGO_HOST || "",
  apiKey: import.meta.env.VITE_OPENALGO_API_KEY || "",
  wsUrl: import.meta.env.VITE_OPENALGO_WS
    || (import.meta.env.VITE_OPENALGO_HOST
      ? `ws://${new URL(import.meta.env.VITE_OPENALGO_HOST).hostname}:${import.meta.env.VITE_OPENALGO_WS_PORT || "8765"}`
      : ""),
  status: "disconnected",
  wsConnected: false,
  lastPing: null,
  setStatus: (status) => set({ status }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  setConfig: (config) => set((state) => ({ ...state, ...config })),
  setLastPing: (lastPing) => set({ lastPing }),
});

export const useConnectionStore = import.meta.env.DEV
  ? create<ConnectionStore>()(devtools(storeImpl, { name: "connection" }))
  : create<ConnectionStore>()(storeImpl);
