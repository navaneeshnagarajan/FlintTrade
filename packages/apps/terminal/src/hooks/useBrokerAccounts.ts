import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { listBrokerAccounts } from "@/services/brokerAccountsApi";
import { useBrokerStore } from "@/stores/brokerStore";

export const BROKER_ACCOUNTS_QUERY_KEY = ["broker", "accounts"] as const;

/**
 * Polls gateway + native broker-account routes every 10 seconds.
 * Syncs to brokerStore (Zustand) as a side effect.
 * UI components should read from useBrokerStore, not this hook's data.
 */
export function useBrokerAccounts(enabled = true) {
  const setAccounts = useBrokerStore((s) => s.setAccounts);

  const query = useQuery({
    queryKey: BROKER_ACCOUNTS_QUERY_KEY,
    queryFn: () => listBrokerAccounts(useBrokerStore.getState().accounts),
    enabled,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (enabled && query.data) {
      setAccounts(query.data);
    }
  }, [enabled, query.data, setAccounts]);

  // Return query for loading/error state only — UI reads accounts from store
  return { isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}
