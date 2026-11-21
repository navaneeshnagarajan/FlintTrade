import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import { useOrders } from "@/hooks/useOrders";
import {
  orderSubmitGuardVersion,
  orderSubmitInFlight,
  readUnknownOrderSubmits,
  reconcileUnknownOrderSubmits,
  submitOrderOnce,
  subscribeOrderSubmitGuard,
  type OrderSubmitIntent,
  type UnknownOrderSubmit,
} from "@/lib/orderSubmitGuard";
import { pendingOrderScope } from "@/lib/pendingOrderStore";

/** Lost submits for one account scope, re-read whenever the guard changes. */
export function useUnknownOrderSubmits(scope: string): UnknownOrderSubmit[] {
  const version = useSyncExternalStore(subscribeOrderSubmitGuard, orderSubmitGuardVersion, orderSubmitGuardVersion);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- version is the store revision
  return useMemo(() => readUnknownOrderSubmits(scope), [scope, version]);
}

/**
 * Shared single-flight and lost-submit lock for fast order paths. While an
 * instrument is locked this polls the order book, and a newer complete read
 * unlocks it.
 */
export function useOrderSubmitGuard() {
  const context = useAccountReadContext();
  const scope = pendingOrderScope(context.identity);
  const unknown = useUnknownOrderSubmits(scope);
  const orders = useOrders({ enabled: unknown.length > 0, context });
  const listComplete = orders.data !== undefined && !orders.isError && !orders.isFetching;

  useEffect(() => {
    if (unknown.length === 0 || !listComplete) return;
    reconcileUnknownOrderSubmits(scope, orders.dataUpdatedAt);
  }, [unknown, listComplete, scope, orders.dataUpdatedAt]);

  const isLocked = useCallback(
    (key: string) => orderSubmitInFlight(scope, key) || unknown.some((record) => record.key === key),
    [scope, unknown],
  );
  const isUnknown = useCallback(
    (key: string) => unknown.some((record) => record.key === key),
    [unknown],
  );
  const submit = useCallback(
    <T,>(intent: OrderSubmitIntent, send: () => Promise<T>, isLost?: (error: unknown) => boolean) => submitOrderOnce(
      scope,
      intent,
      send,
      // The cached order list is readable even while polling is off.
      orders.dataUpdatedAt ?? 0,
      isLost,
    ),
    [scope, orders.dataUpdatedAt],
  );

  return { scope, unknown, isLocked, isUnknown, submit };
}

export type OrderSubmitGuard = ReturnType<typeof useOrderSubmitGuard>;
