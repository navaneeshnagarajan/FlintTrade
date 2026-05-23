/**
 * useRRGData
 *
 * Fetches Relative Rotation Graph (RRG) sector data from the FlintTrade
 * backend (/ft-api/api/v1/rrg/sectors).
 *
 * - Explore mode: returns null (widget falls back to the built-in sample data
 *   that the backend always serves when no broker is connected).
 * - Practice/Live mode: fetches RRG data; refetches every 5 minutes (weekly
 *   bars — no need for sub-minute refresh).
 */

import { useQuery } from "@tanstack/react-query";
import { getRRGData } from "@/services/ftApi";
import type { RRGResponse } from "@/services/ftApi";

export function useRRGData(tailLength: number = 12): {
  data: RRGResponse | null;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
} {
  // RRG is useful even in explore mode — the backend returns sample data
  // there — so the query is always enabled. (Previously gated on
  // `mode !== undefined`, which was always true since `mode` is a non-nullable
  // union literal type — that conditional was dead logic.)

  const query = useQuery<RRGResponse>({
    queryKey: ["rrg-sectors", tailLength],
    queryFn: () => getRRGData(tailLength),
    staleTime: 5 * 60_000,        // 5 minutes — weekly bars don't change fast
    refetchInterval: 5 * 60_000,
    retry: 2,
  });

  return {
    data: query.data ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}
