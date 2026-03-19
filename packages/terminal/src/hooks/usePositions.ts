import { useQuery } from "@tanstack/react-query";
import { getPositionbook } from "@/services/api";
import { useTradingStore } from "@/stores/tradingStore";
import type { Position } from "@/types/api";

function isMarketHours(): boolean {
  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const mins = ist.getHours() * 60 + ist.getMinutes();
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  return mins >= 555 && mins <= 930;
}

export function usePositions() {
  return useQuery<Position[]>({
    queryKey: ["positions"],
    queryFn: getPositionbook,
    refetchInterval: isMarketHours() ? 5_000 : 60_000,
    select: (data) => {
      useTradingStore.getState().updateFromPositions(data);
      return data;
    },
  });
}
