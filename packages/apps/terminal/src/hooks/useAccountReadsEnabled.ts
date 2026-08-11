import { useMemo } from "react";

import {
  resolveAccountAuthorityIdentity,
  resolveNativeDataAccount,
  type AccountAuthorityIdentity,
} from "@/hooks/useDataScope";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";
import type { ConnectionStatus } from "@/types/stores";

/** Resolve whether account-backed reads have a valid source in the current mode. */
export function resolveAccountReadsEnabled(mode: AppMode, brokerConnected: boolean): boolean {
  return mode === "practice" || (mode === "live" && brokerConnected);
}

interface ScopedAccountReadsInput {
  mode: AppMode;
  apiKey: string;
  openAlgoStatus: ConnectionStatus;
  accounts: BrokerAccount[];
  activeAccountId: string | null;
}

/**
 * Resolve the read gate for the same source identity used by `useDataScope`.
 * A different connected account must never keep the selected/primary account's
 * observer enabled after that account disconnects.
 */
export function resolveScopedAccountReadsEnabled({
  mode,
  apiKey,
  openAlgoStatus,
  accounts,
  activeAccountId,
}: ScopedAccountReadsInput): boolean {
  if (mode === "explore") return false;
  if (mode === "practice") return true;
  if (apiKey.trim()) return openAlgoStatus === "connected";
  return resolveNativeDataAccount(accounts, activeAccountId)?.status === "connected";
}

/** Immutable query transport snapshot; raw connection values never enter the query key. */
export interface AccountReadContext {
  readonly identity: AccountAuthorityIdentity;
  readonly enabled: boolean;
  readonly host: string;
  readonly apiKey: string;
}

/** Check read availability against the exact account encoded by an identity. */
export function accountIdentityReadsEnabled(
  identity: AccountAuthorityIdentity,
  openAlgoStatus: ConnectionStatus,
  accounts: BrokerAccount[],
): boolean {
  if (identity.mode === "explore") return false;
  if (identity.mode === "practice") {
    return identity.brokerType === "sandbox" && identity.accountId === "default";
  }
  if (identity.brokerType === "openalgo") return openAlgoStatus === "connected";
  if (identity.brokerType === "unconfigured") return false;
  return accounts.some((account) => (
    account.source === "native"
    && account.broker === identity.brokerType
    && account.account_id === identity.accountId
    && account.status === "connected"
  ));
}

/**
 * One reactive snapshot binds query scope, scheduling gate, and transport target.
 * The object and nested identity are immutable for the lifetime of a render.
 */
export function useAccountReadContext(): AccountReadContext {
  // AppLayout owns the single auth- and mode-gated broker-account poll. Query
  // hooks consume that store snapshot without mounting enabled observers that
  // could leak protected account discovery into Explore.
  const mode = useModeStore((state) => state.mode);
  const host = useConnectionStore((state) => state.host);
  const apiKey = useConnectionStore((state) => state.apiKey);
  const openAlgoStatus = useConnectionStore((state) => state.status);
  const accounts = useBrokerStore((state) => state.accounts);
  const activeAccountId = useBrokerStore((state) => state.activeAccountId);

  return useMemo(() => {
    const identity = resolveAccountAuthorityIdentity({
      mode,
      host,
      apiKey,
      accounts,
      activeAccountId,
    });
    return Object.freeze({
      identity,
      enabled: accountIdentityReadsEnabled(identity, openAlgoStatus, accounts),
      host,
      apiKey,
    });
  }, [mode, host, apiKey, openAlgoStatus, accounts, activeAccountId]);
}

/**
 * Account data comes from the local sandbox in Practice and the exact selected
 * Live source in Live. Explore owns its separate, labelled sample feed.
 */
export function useAccountReadsEnabled(): boolean {
  return useAccountReadContext().enabled;
}
