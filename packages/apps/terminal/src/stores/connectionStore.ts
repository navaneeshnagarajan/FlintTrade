import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import type { PersistStorage, StorageValue } from "zustand/middleware";
import type { ConnectionStatus } from "@/types/stores";
import { obfuscate, deobfuscate } from "@/lib/keyVault";

interface ConnectionStore {
  host: string;
  apiKey: string;
  wsUrl: string;
  status: ConnectionStatus;
  wsConnected: boolean;
  lastPing: number | null;
  demo: boolean;
  setStatus: (status: ConnectionStatus) => void;
  setWsConnected: (connected: boolean) => void;
  setConfig: (config: { host?: string; apiKey?: string; wsUrl?: string }) => void;
  setLastPing: (timestamp: number) => void;
  setDemo: (v: boolean) => void;
}

// Inner StateCreator (no middleware mutators — persist is applied outside)
//
// SECURITY: do not seed connection values from Vite env vars. Vite inlines
// `VITE_*` values into the production JS bundle at build time, which is the
// wrong source of truth for an installable desktop app. Users configure
// OpenAlgo/native broker access through Setup or Settings; the backend then
// persists those choices to the OS workspace under ~/.flinttrade/ (or the
// platform equivalent).
const storeImpl: StateCreator<ConnectionStore, [["zustand/persist", unknown]]> = (set) => ({
  host: "",
  apiKey: "",
  wsUrl: "",
  status: "disconnected",
  wsConnected: false,
  lastPing: null,
  demo: false,
  setStatus: (status) => set({ status }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  setConfig: (config) => set((state) => ({ ...state, ...config })),
  setLastPing: (lastPing) => set({ lastPing }),
  setDemo: (demo) => set({ demo }),
});

/**
 * Partial shape that Zustand persist serialises to/from storage.
 * Defined explicitly so the custom storage adapter is fully type-safe.
 */
type PersistedState = {
  host: string;
  apiKey: string;
  wsUrl: string;
};

/**
 * Custom sessionStorage adapter that XOR-obfuscates the API key at rest.
 *
 * The key is never written to sessionStorage in plaintext — it is passed
 * through {@link obfuscate} on every write and {@link deobfuscate} on every
 * read. All other fields (host, wsUrl) are stored as-is since they are not
 * sensitive credentials.
 *
 * sessionStorage scope: the value is cleared automatically when the tab
 * closes, which limits the window of exposure compared with localStorage.
 */
const obfuscatedStorage: PersistStorage<PersistedState> = {
  getItem(name): StorageValue<PersistedState> | null {
    const raw = sessionStorage.getItem(name);
    if (raw === null) return null;
    const parsed = JSON.parse(raw) as StorageValue<PersistedState>;
    if (parsed?.state?.apiKey) {
      parsed.state.apiKey = deobfuscate(parsed.state.apiKey);
    }
    return parsed;
  },
  setItem(name, value): void {
    // Deep-clone so we never mutate the live Zustand state object.
    const clone = JSON.parse(
      JSON.stringify(value),
    ) as StorageValue<PersistedState>;
    if (clone?.state?.apiKey) {
      clone.state.apiKey = obfuscate(clone.state.apiKey);
    }
    sessionStorage.setItem(name, JSON.stringify(clone));
  },
  removeItem(name): void {
    sessionStorage.removeItem(name);
  },
};

const persistedStore = persist(storeImpl, {
  name: "flinttrade:connection",
  version: 1,
  // sessionStorage — clears on tab close, limiting XSS exfiltration window.
  // The API key is additionally XOR-obfuscated (see obfuscatedStorage above)
  // so it does not appear in plain text in DevTools / storage inspectors.
  storage: obfuscatedStorage,
  // Only persist credentials — runtime connection state is always re-derived.
  partialize: (state): PersistedState => ({
    host: state.host,
    apiKey: state.apiKey,
    wsUrl: state.wsUrl,
  }),
});

export const useConnectionStore = import.meta.env.DEV
  ? create<ConnectionStore>()(devtools(persistedStore, { name: "connection" }))
  : create<ConnectionStore>()(persistedStore);
