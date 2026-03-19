import { create } from "zustand";
import { devtools } from "zustand/middleware";
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

const BASE = "";
const API_KEY = "";
const WS_URL = "";

export const useConnectionStore = create<ConnectionStore>()(
  devtools(
    (set) => ({
      host: BASE,
      apiKey: API_KEY,
      wsUrl: WS_URL,
      status: "disconnected",
      wsConnected: false,
      lastPing: null,
      setStatus: (status) => set({ status }, false, "setStatus"),
      setWsConnected: (wsConnected) => set({ wsConnected }, false, "setWsConnected"),
      setConfig: (config) => set((state) => ({ ...state, ...config }), false, "setConfig"),
      setLastPing: (lastPing) => set({ lastPing }, false, "setLastPing"),
    }),
    { name: "connection" }
  )
);
