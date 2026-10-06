import { useMemo } from "react";

import {
  brokerAccountKey,
  useBrokerStore,
} from "@/stores/brokerStore";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";
import { resolveMarketDataScope, resolveNativeDataAccount } from "@/lib/marketDataScope";
export { resolveMarketDataScope, resolveNativeDataAccount } from "@/lib/marketDataScope";

export interface DataScopeInput {
  mode: AppMode;
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

/** Resolve the exact immutable identity represented by an account-query key. */
export function resolveAccountAuthorityIdentity({
  mode,
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

export class MarketDataAuthorityChangedError extends Error {
  constructor() {
    super("Market data authority changed before the request could complete.");
    this.name = "MarketDataAuthorityChangedError";
  }
}

/** Broker capabilities are broker-wide, so native account IDs never enter their cache key. */
export function resolveBrokerCapabilityScope(dataScope: string): string {
  const parts = dataScope.split(":");
  return parts[1] === "native" ? parts.slice(0, 3).join(":") : dataScope;
}

/** Imperatively validate a render-captured market authority at a fetch boundary. */
export function requireCurrentMarketDataScope(expectedDataScope?: string): void {
  if (!expectedDataScope) return;
  const { accounts, activeAccountId } = useBrokerStore.getState();
  const actual = resolveMarketDataScope({
    mode: useModeStore.getState().mode,
    accounts,
    activeAccountId,
  });
  if (actual !== expectedDataScope) throw new MarketDataAuthorityChangedError();
}

/** Validate the broker-wide capability authority represented by a query key. */
export function requireCurrentBrokerCapabilityScope(expectedScope?: string): void {
  if (!expectedScope) return;
  const { accounts, activeAccountId } = useBrokerStore.getState();
  const actual = resolveBrokerCapabilityScope(resolveMarketDataScope({
    mode: useModeStore.getState().mode,
    accounts,
    activeAccountId,
  }));
  if (actual !== expectedScope) throw new MarketDataAuthorityChangedError();
}

/** Reactive immutable authority identity for account queries and actions. */
export function useAccountAuthorityIdentity(): AccountAuthorityIdentity {
  const mode = useModeStore((state) => state.mode);
  const accounts = useBrokerStore((state) => state.accounts);
  const activeAccountId = useBrokerStore((state) => state.activeAccountId);

  return useMemo(
    () => resolveAccountAuthorityIdentity({ mode, accounts, activeAccountId }),
    [mode, accounts, activeAccountId],
  );
}

/** Reactive provenance key for TanStack queries and local chart caches. */
export function useDataScope(): string {
  return useAccountAuthorityIdentity().scopeKey;
}

/** Reactive provenance key for market data and its local caches. */
export function useMarketDataScope(): string {
  const mode = useModeStore((state) => state.mode);
  const accounts = useBrokerStore((state) => state.accounts);
  const activeAccountId = useBrokerStore((state) => state.activeAccountId);

  return useMemo(
    () => resolveMarketDataScope({ mode, accounts, activeAccountId }),
    [mode, accounts, activeAccountId],
  );
}
