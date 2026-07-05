import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { gatewayApi } from "@/services/gatewayApi";
import { listNativeAccounts, type NativeAccount } from "@/services/ftApi.native";
import { useBrokerStore } from "@/stores/brokerStore";
import type { AccountStatus, BrokerAccount } from "@/types/broker";

export const BROKER_ACCOUNTS_QUERY_KEY = ["broker", "accounts"] as const;

function nativeStatus(account: NativeAccount): AccountStatus {
  if (account.has_session === true) return "connected";
  if (account.needs_relogin === true) return "token_expired";
  if (account.login_retryable === true) return "disconnected";
  return "disconnected";
}

function nativeToBrokerAccount(account: NativeAccount): BrokerAccount {
  return {
    account_id: account.account_id,
    broker: account.adapter_id,
    label: account.label || account.account_id,
    status: nativeStatus(account),
    connected_at: null,
    error_message: account.login_error ?? null,
    is_primary: !!account.is_primary,
    source: "native",
  };
}

async function listBrokerAccounts(): Promise<BrokerAccount[]> {
  const [gatewayResult, nativeResult] = await Promise.allSettled([
    gatewayApi.listAccounts(),
    listNativeAccounts(),
  ]);

  if (gatewayResult.status === "rejected" && nativeResult.status === "rejected") {
    throw gatewayResult.reason instanceof Error
      ? gatewayResult.reason
      : new Error("Could not list broker accounts");
  }

  // A *one-sided* failure must not drop the failing source's accounts. Both
  // routes share the port-5100 backend, so a one-sided rejection is a
  // transient/route-specific blip — returning a partial list would let
  // setAccounts null the persisted activeAccountId if the active account
  // belonged to that source, silently reverting write-targeting to OpenAlgo with
  // no re-selection on recovery. Keep that source's last-good rows (from the
  // store) until it recovers, so the surviving source stays live and the active
  // account survives the blip.
  const previous = useBrokerStore.getState().accounts;
  const gatewayAccounts = gatewayResult.status === "fulfilled"
    ? gatewayResult.value
    : previous.filter((a) => a.source !== "native");
  const nativeAccounts = nativeResult.status === "fulfilled"
    ? nativeResult.value.map(nativeToBrokerAccount)
    : previous.filter((a) => a.source === "native");
  return [...gatewayAccounts, ...nativeAccounts];
}

/**
 * Polls gateway + native broker-account routes every 10 seconds.
 * Syncs to brokerStore (Zustand) as a side effect.
 * UI components should read from useBrokerStore, not this hook's data.
 */
export function useBrokerAccounts() {
  const setAccounts = useBrokerStore((s) => s.setAccounts);

  const query = useQuery({
    queryKey: BROKER_ACCOUNTS_QUERY_KEY,
    queryFn: listBrokerAccounts,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (query.data) {
      setAccounts(query.data);
    }
  }, [query.data, setAccounts]);

  // Return query for loading/error state only — UI reads accounts from store
  return { isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}
