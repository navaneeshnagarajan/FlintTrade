import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { listBrokerAccounts } from "@/services/brokerAccountsApi";
import { useBrokerStore } from "@/stores/brokerStore";
import { noteObservedFailure, useOperatorSignalStore } from "@/stores/operatorSignalStore";

export const BROKER_ACCOUNTS_QUERY_KEY = ["broker", "accounts"] as const;

/**
 * Polls gateway + native broker-account routes every 10 seconds.
 * Syncs to brokerStore (Zustand) as a side effect.
 * UI components should read from useBrokerStore, not this hook's data.
 */
export function useBrokerAccounts(enabled = true) {
  const setAccounts = useBrokerStore((s) => s.setAccounts);

  const brokerRateLimited = useOperatorSignalStore((s) => s.brokerRateLimited);
  const query = useQuery({
    queryKey: BROKER_ACCOUNTS_QUERY_KEY,
    queryFn: ({ signal }) => listBrokerAccounts(useBrokerStore.getState().accounts, signal),
    enabled,
    // A latched broker rate limit must not keep polling. The operator retries once.
    refetchInterval: brokerRateLimited ? false : 10_000,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (!query.error) return;
    const message = query.error instanceof Error ? query.error.message : String(query.error);
    const httpStatus = "status" in query.error && typeof query.error.status === "number"
      ? query.error.status
      : null;
    noteObservedFailure({ message, httpStatus });
  }, [query.error]);

  useEffect(() => {
    if (enabled && query.data) {
      setAccounts(query.data);
    }
  }, [enabled, query.data, setAccounts]);

  // Return query for loading/error state only — UI reads accounts from store
  return { isLoading: query.isLoading, error: query.error, refetch: query.refetch };
}
