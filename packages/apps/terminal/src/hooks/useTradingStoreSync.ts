import { useEffect } from "react";

import { useFunds } from "@/hooks/useFunds";
import { usePositions } from "@/hooks/usePositions";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
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
  const scopedAccountReadsEnabled = useAccountReadsEnabled();
  const accountReadsEnabled = sessionEnabled && scopedAccountReadsEnabled;
  const funds = useFunds({ enabled: accountReadsEnabled });
  const positions = usePositions({ enabled: accountReadsEnabled });

  useEffect(() => {
    if (accountReadsEnabled && funds.data) {
      useTradingStore.getState().updateFromFunds(funds.data);
    }
  }, [accountReadsEnabled, funds.data]);

  useEffect(() => {
    if (accountReadsEnabled && positions.data) {
      useTradingStore.getState().updateFromPositions(positions.data);
    }
  }, [accountReadsEnabled, positions.data]);
}
