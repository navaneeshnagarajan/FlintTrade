import { useEffect } from "react";

import { useFunds } from "@/hooks/useFunds";
import { usePositions } from "@/hooks/usePositions";
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import { useAccountQueryAvailability } from "@/hooks/useAccountQueryAvailability";
import { useTradingStore } from "@/stores/tradingStore";

/**
 * Single-source TanStack → Zustand sync hook.
 *
 * `tradingStore` is an **ergonomic mirror** of aggregate derived state
 * (total P&L, margin, position count) so widgets can read simple scalars
 * without each re-deriving the same figures. The canonical source is
 * TanStack Query — this hook mirrors those values into Zustand once at
 * the app root.
 *
 * Call exactly once in the top-level layout (e.g. `AppLayout`). Do not
 * write into `tradingStore` from anywhere else, and do not copy this
 * sync into other hooks — duplication is what the state-boundary rule
 * forbids.
 */
export function useTradingStoreSync(sessionEnabled = true): void {
  const context = useAccountReadContext();
  const canRetain = sessionEnabled && context.identity.mode !== "explore";
  const accountReadsEnabled = sessionEnabled && context.enabled;
  const funds = useFunds({ enabled: accountReadsEnabled, context });
  const positions = usePositions({ enabled: accountReadsEnabled, context });
  const fundsData = canRetain ? funds.data : undefined;
  const positionsData = canRetain ? positions.data : undefined;
  const fundsStatus = useAccountQueryAvailability({
    accountReadsEnabled, hasData: fundsData !== undefined,
    fetchStatus: funds.fetchStatus, isError: funds.isError,
    isLoading: funds.isLoading, isStale: funds.isStale,
  });
  const positionsStatus = useAccountQueryAvailability({
    accountReadsEnabled, hasData: positionsData !== undefined,
    fetchStatus: positions.fetchStatus, isError: positions.isError,
    isLoading: positions.isLoading, isStale: positions.isStale,
  });

  useEffect(() => {
    useTradingStore.getState().syncAccountSnapshot({
      scopeKey: sessionEnabled ? context.identity.scopeKey : null,
      fundsStatus,
      positionsStatus,
      funds: fundsData,
      positions: positionsData,
    });
  }, [sessionEnabled, context.identity.scopeKey, fundsData, positionsData, fundsStatus, positionsStatus]);
}
