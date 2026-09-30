/**
 * One NSE cash session for the TopBar chip and the ticker venue badges.
 */

import { useCallback, useEffect, useState } from "react";
import {
  MARKET_TIMINGS_MAX_AGE_MS,
  useTimings,
} from "@/hooks/useMarketStatus";
import {
  getNseCashSessionStatus,
  type MarketSessionInfo,
} from "@/lib/market";

export function useOperatorMarketSession(): MarketSessionInfo {
  const { data: timings, dataUpdatedAt, isError, isLoading } = useTimings();
  const currentStatus = useCallback(() => {
    const timingIsTrustworthy =
      !isError &&
      !isLoading &&
      dataUpdatedAt > 0 &&
      Date.now() - dataUpdatedAt <= MARKET_TIMINGS_MAX_AGE_MS;
    return getNseCashSessionStatus(timingIsTrustworthy ? timings : undefined);
  }, [dataUpdatedAt, isError, isLoading, timings]);
  const [statusInfo, setStatusInfo] = useState<MarketSessionInfo>(() => currentStatus());

  useEffect(() => {
    const update = () => setStatusInfo(currentStatus());
    update();
    const id = setInterval(update, 30_000);
    return () => clearInterval(id);
  }, [currentStatus]);

  return statusInfo;
}
