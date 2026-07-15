import { useConnectionStore } from "@/stores/connectionStore";
import {
  brokerAccountKey,
  findBrokerAccountMatch,
  useBrokerStore,
} from "@/stores/brokerStore";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";

export interface DataScopeInput {
  mode: AppMode;
  host: string;
  apiKey: string;
  accounts: BrokerAccount[];
  activeAccountId: string | null;
}

/** Build an opaque deterministic identifier without retaining raw connection values. */
export function connectionScopeFingerprint(host: string, apiKey: string): string {
  const value = `${host.trim().toLowerCase().replace(/\/+$/, "")}\u0000${apiKey.trim()}`;
  let first = 0xdeadbeef ^ value.length;
  let second = 0x41c6ce57 ^ value.length;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    first = Math.imul(first ^ code, 2_654_435_761);
    second = Math.imul(second ^ code, 1_597_334_677);
  }
  first = Math.imul(first ^ (first >>> 16), 2_246_822_507)
    ^ Math.imul(second ^ (second >>> 13), 3_266_489_909);
  second = Math.imul(second ^ (second >>> 16), 2_246_822_507)
    ^ Math.imul(first ^ (first >>> 13), 3_266_489_909);
  return `${(first >>> 0).toString(16).padStart(8, "0")}${(second >>> 0).toString(16).padStart(8, "0")}`;
}

/**
 * Return the provenance key used by account queries and persisted market data.
 *
 * Explore and Practice are deliberately account-independent. Live OpenAlgo
 * reads are selected whenever an OpenAlgo key exists; otherwise native reads
 * follow the selected composite account, then the primary connected account.
 */
export function resolveDataScope({
  mode,
  host,
  apiKey,
  accounts,
  activeAccountId,
}: DataScopeInput): string {
  if (mode === "explore") return "explore:mock";
  if (mode === "practice") return "practice:sandbox:default";
  if (apiKey.trim()) return `live:openalgo:${connectionScopeFingerprint(host, apiKey)}`;

  const active = findBrokerAccountMatch(accounts, activeAccountId);
  if (active?.source === "native") {
    return `live:${brokerAccountKey(active)}`;
  }

  const fallback = accounts.find((account) => (
    account.source === "native" && account.status === "connected" && account.is_primary
  )) ?? accounts.find((account) => (
    account.source === "native" && account.status === "connected"
  ));
  return fallback ? `live:${brokerAccountKey(fallback)}` : "live:unconfigured";
}

/** Reactive provenance key for TanStack queries and local chart caches. */
export function useDataScope(): string {
  const mode = useModeStore((state) => state.mode);
  const host = useConnectionStore((state) => state.host);
  const apiKey = useConnectionStore((state) => state.apiKey);
  const accounts = useBrokerStore((state) => state.accounts);
  const activeAccountId = useBrokerStore((state) => state.activeAccountId);

  return resolveDataScope({ mode, host, apiKey, accounts, activeAccountId });
}
