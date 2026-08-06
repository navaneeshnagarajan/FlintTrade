import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { searchSymbol } from "@/services/api";

interface SymbolResult {
  symbol: string;
  exchange: string;
}

export function useSymbolSearch(query: string) {
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const nextRetryId = useRef(0);
  const [retryingAttempt, setRetryingAttempt] = useState<{
    id: number;
    query: string;
  } | null>(null);

  useEffect(() => {
    if (query.length < 2) {
      setDebouncedQuery("");
      return;
    }
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const { data, isLoading, isError, refetch } = useQuery<SymbolResult[]>({
    queryKey: ["symbolSearch", debouncedQuery],
    queryFn: () => searchSymbol(debouncedQuery),
    enabled: debouncedQuery.length >= 2,
    staleTime: 30_000,
  });

  const isPending = query.length >= 2 && debouncedQuery !== query;
  const isRetrying =
    retryingAttempt !== null &&
    retryingAttempt.query === debouncedQuery &&
    debouncedQuery === query;
  const retry = useCallback(async () => {
    const attempt = {
      id: ++nextRetryId.current,
      query: debouncedQuery,
    };
    setRetryingAttempt(attempt);
    try {
      return await refetch();
    } finally {
      setRetryingAttempt((current) =>
        current?.id === attempt.id ? null : current,
      );
    }
  }, [debouncedQuery, refetch]);

  return {
    results: isError || isPending || isRetrying ? [] : (data ?? []),
    isLoading:
      !isRetrying && ((isLoading && debouncedQuery.length >= 2) || isPending),
    isError: isRetrying || (!!isError && debouncedQuery.length >= 2),
    isRetrying,
    retry,
  };
}
