import { useMemo } from "react";

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

/** Immutable authority identity shared by query keys, transports, and actions. */
export interface AccountAuthorityIdentity {
  readonly mode: AppMode;
  readonly scopeKey: string;
  readonly brokerType: string;
  readonly accountId: string;
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
 * Resolve the native account whose identity owns account-query provenance.
 * Connection status is deliberately not part of identity: disconnecting must
 * disable reads without moving the observer onto another account's cache key.
 */
export function resolveNativeDataAccount(
  accounts: BrokerAccount[],
  activeAccountId: string | null,
): BrokerAccount | undefined {
  if (activeAccountId) {
    const active = findBrokerAccountMatch(accounts, activeAccountId);
    return active?.source === "native" ? active : undefined;
  }

  const nativeAccounts = accounts.filter((account) => account.source === "native");
  const primary = nativeAccounts.find((account) => account.is_primary);
  if (primary) return primary;
  return nativeAccounts.length === 1 ? nativeAccounts[0] : undefined;
}

/** Resolve the exact immutable identity represented by an account-query key. */
export function resolveAccountAuthorityIdentity({
  mode,
  host,
  apiKey,
  accounts,
  activeAccountId,
}: DataScopeInput): AccountAuthorityIdentity {
  if (mode === "explore") {
    return Object.freeze({
      mode,
      scopeKey: "explore:mock",
      brokerType: "mock",
      accountId: "default",
    });
  }
  if (mode === "practice") {
    return Object.freeze({
      mode,
      scopeKey: "practice:sandbox:default",
      brokerType: "sandbox",
      accountId: "default",
    });
  }
  if (apiKey.trim()) {
    return Object.freeze({
      mode,
      scopeKey: `live:openalgo:${connectionScopeFingerprint(host, apiKey)}`,
      brokerType: "openalgo",
      accountId: "default",
    });
  }

  const nativeAccount = resolveNativeDataAccount(accounts, activeAccountId);
  if (nativeAccount) {
    return Object.freeze({
      mode,
      scopeKey: `live:${brokerAccountKey(nativeAccount)}`,
      brokerType: nativeAccount.broker,
      accountId: nativeAccount.account_id,
    });
  }
  return Object.freeze({
    mode,
    scopeKey: "live:unconfigured",
    brokerType: "unconfigured",
    accountId: "none",
  });
}

/**
 * Return the provenance key used by account queries and persisted market data.
 * Connection status never changes this identity.
 */
export function resolveDataScope(input: DataScopeInput): string {
  return resolveAccountAuthorityIdentity(input).scopeKey;
}

/** Reactive immutable authority identity for account queries and actions. */
export function useAccountAuthorityIdentity(): AccountAuthorityIdentity {
  const mode = useModeStore((state) => state.mode);
  const host = useConnectionStore((state) => state.host);
  const apiKey = useConnectionStore((state) => state.apiKey);
  const accounts = useBrokerStore((state) => state.accounts);
  const activeAccountId = useBrokerStore((state) => state.activeAccountId);

  return useMemo(
    () => resolveAccountAuthorityIdentity({ mode, host, apiKey, accounts, activeAccountId }),
    [mode, host, apiKey, accounts, activeAccountId],
  );
}

/** Reactive provenance key for TanStack queries and local chart caches. */
export function useDataScope(): string {
  return useAccountAuthorityIdentity().scopeKey;
}
