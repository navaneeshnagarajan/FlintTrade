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
  host: "",
  apiKey: "",
  wsUrl: "",
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
