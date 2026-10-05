import { brokerAccountKey, findBrokerAccountMatch } from "@/stores/brokerStore";
import type { BrokerAccount } from "@/types/broker";
import type { AppMode } from "@/stores/modeStore";

export interface MarketDataScopeInput {
  mode: AppMode;
  accounts: BrokerAccount[];
  activeAccountId: string | null;
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

/** Resolve the exact market-data authority, including its current app mode. */
export function resolveMarketDataScope({
  mode,
  accounts,
  activeAccountId,
}: MarketDataScopeInput): string {
  if (mode === "explore") return "explore:mock";
  const nativeAccount = resolveNativeDataAccount(accounts, activeAccountId);
  return nativeAccount
    ? `${mode}:${brokerAccountKey(nativeAccount)}`
    : `${mode}:unconfigured`;
}
