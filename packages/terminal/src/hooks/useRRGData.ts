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
import { useModeStore } from "@/stores/modeStore";

export function useRRGData(tailLength: number = 12): {
  data: RRGResponse | null;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
} {
  const mode = useModeStore((s) => s.mode);
  // RRG is useful even in explore mode (backend returns sample data).
  // Enable always so the widget has something to render out-of-the-box.
  const enabled = mode !== undefined;

  const query = useQuery<RRGResponse>({
    queryKey: ["rrg-sectors", tailLength],
    queryFn: () => getRRGData(tailLength),
    enabled,
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
