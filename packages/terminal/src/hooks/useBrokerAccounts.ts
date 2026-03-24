import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { gatewayApi } from "@/services/gatewayApi";
import { useBrokerStore } from "@/stores/brokerStore";

/**
 * Polls /ft-api/v1/accounts every 10 seconds.
 * Syncs to brokerStore (Zustand) as a side effect.
 * UI components should read from useBrokerStore, not this hook's data.
 */
export function useBrokerAccounts() {
  const setAccounts = useBrokerStore((s) => s.setAccounts);

  const query = useQuery({
    queryKey: ["gateway", "accounts"],
    queryFn: gatewayApi.listAccounts,
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
