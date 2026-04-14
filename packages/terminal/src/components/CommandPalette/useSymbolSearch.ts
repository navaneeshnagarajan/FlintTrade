import { useQuery } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { searchSymbol } from "@/services/api";

interface SymbolResult {
  symbol: string;
  exchange: string;
}

export function useSymbolSearch(query: string) {
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    if (query.length < 2) {
      setDebouncedQuery("");
      return;
    }
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const { data, isLoading } = useQuery<SymbolResult[]>({
    queryKey: ["symbolSearch", debouncedQuery],
    queryFn: () => searchSymbol(debouncedQuery),
    enabled: debouncedQuery.length >= 2,
    staleTime: 30_000,
  });

  return {
    results: data ?? [],
    isLoading: isLoading && debouncedQuery.length >= 2,
  };
}
