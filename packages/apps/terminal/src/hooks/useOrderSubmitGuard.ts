import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import { useOrders } from "@/hooks/useOrders";
import {
  orderSubmitGuardVersion,
  orderSubmitInFlight,
  readUnknownOrderSubmits,
  reconcileUnknownOrderSubmits,
  submitOrderOnce,
  subscribeOrderSubmitGuard,
  UNKNOWN_SUBMIT_SETTLE_MS,
  type OrderBookRead,
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
 * Remember the start of a fetch that later completes, and settle lost
 * submits only with that read. A cached list that never fetched does not
 * unlock.
 */
export function useSettleUnknownSubmits(
  scope: string,
  isFetching: boolean,
  dataUpdatedAt: number,
  listComplete: boolean,
): void {
  const unknown = useUnknownOrderSubmits(scope);
  const startedAtRef = useRef<number | null>(null);
  const seenFetchingRef = useRef(false);
  const [completedRead, setCompletedRead] = useState<OrderBookRead | null>(null);

  useEffect(() => {
    if (isFetching) {
      if (!seenFetchingRef.current) startedAtRef.current = Date.now();
      seenFetchingRef.current = true;
      return;
    }
    const startedAt = startedAtRef.current;
    startedAtRef.current = null;
    if (seenFetchingRef.current && startedAt != null && listComplete) {
      setCompletedRead({ startedAt, completedAt: dataUpdatedAt });
    }
    seenFetchingRef.current = false;
  }, [isFetching, listComplete, dataUpdatedAt]);

  useEffect(() => {
    if (!completedRead || unknown.length === 0) return;
    reconcileUnknownOrderSubmits(scope, completedRead);
  }, [completedRead, unknown, scope]);
}

/** One order-book read just after the settle delay, so a lock clears promptly. */
export const UNKNOWN_SUBMIT_SETTLE_READ_MS = UNKNOWN_SUBMIT_SETTLE_MS + 100;

/**
 * Schedule one order-book read for each lost submit, just after the settle
 * delay. The read only counts if it starts after that delay, so when another
 * read is still in flight at that moment, wait for it and read once more.
 */
export function useScheduledSettleRead(
  unknown: UnknownOrderSubmit[],
  isFetching: boolean,
  refetch: (options?: { cancelRefetch?: boolean }) => Promise<unknown>,
): void {
  const fetchingRef = useRef(isFetching);
  fetchingRef.current = isFetching;
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;
  const dueAt = unknown.length === 0
    ? null
    : Math.min(...unknown.map((record) => record.receivedAt)) + UNKNOWN_SUBMIT_SETTLE_READ_MS;

  useEffect(() => {
    if (dueAt == null) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      void (async () => {
        if (fetchingRef.current) await refetchRef.current({ cancelRefetch: false }).catch(() => undefined);
        if (!cancelled) await refetchRef.current({ cancelRefetch: false }).catch(() => undefined);
      })();
    }, Math.max(0, dueAt - Date.now()));
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [dueAt]);
}

/**
 * Shared single-flight and lost-submit lock for fast order paths. While an
 * instrument is locked this polls the order book, and a complete read that
 * started a few seconds after the loss unlocks it.
 */
export function useOrderSubmitGuard() {
  const context = useAccountReadContext();
  const scope = pendingOrderScope(context.identity);
  const unknown = useUnknownOrderSubmits(scope);
  const orders = useOrders({ enabled: unknown.length > 0, context });
  const listComplete = orders.data !== undefined && !orders.isError && !orders.isFetching;
  useSettleUnknownSubmits(scope, orders.isFetching, orders.dataUpdatedAt, listComplete);
  useScheduledSettleRead(unknown, orders.isFetching, orders.refetch);

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
