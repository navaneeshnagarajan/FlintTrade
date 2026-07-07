import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getOrderbook } from "@/services/api";
import type { Order } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { queryKeys } from "@/services/queryKeys";

interface BrokerDataQueryOptions {
  enabled?: boolean;
}

/**
 * Exchanges whose sessions define the order-book auto-refresh window.
 * The union covers the NSE/BSE equity + F&O day session (9:15–15:30 IST),
 * the currency session (CDS 9:00–17:00 IST) and the commodity evening
 * session (MCX 9:00–23:30 IST) — NOT just NSE, so an MCX/CDS order book
 * keeps refreshing after the equity close.
 */
const ORDER_SESSION_EXCHANGES = ["NSE", "BSE", "MCX", "CDS"] as const;

/** True when ANY Indian market session relevant to the order book is open. */
export function isAnyOrderSessionOpen(): boolean {
  return ORDER_SESSION_EXCHANGES.some((exchange) => isMarketHours(exchange));
}

/** Foreground refetch interval while any Indian session is open. */
export const ORDERS_REFETCH_ACTIVE_MS = 10_000;
/**
 * Slow background interval outside all sessions — the order book still moves
 * off-hours (AMO placement, broker EOD cleanup), so never freeze it entirely.
 */
export const ORDERS_REFETCH_IDLE_MS = 120_000;

/** CustomEvent name signalling that the order book changed (place/modify/cancel). */
export const ORDERS_CHANGED_EVENT = "flinttrade:ordersChanged";

/**
 * Notify every mounted order-book query that an order was placed, modified
 * or cancelled, so the book refetches immediately instead of waiting out the
 * polling interval. Call this after any successful order mutation.
 */
export function emitOrdersChanged(): void {
  window.dispatchEvent(new CustomEvent(ORDERS_CHANGED_EVENT));
}

export function useOrders(options: BrokerDataQueryOptions = {}) {
  const enabled = options.enabled ?? true;
  const queryClient = useQueryClient();

  // Refetch on order placement events. Two triggers:
  //   1. The dedicated ORDERS_CHANGED_EVENT (dispatch via emitOrdersChanged).
  //   2. The app-wide Notification Centre bus ("flinttrade:notify"): OrderPad
  //      and the order-management widgets already emit a category:"order"
  //      notification on every placement/cancel outcome, so listening here
  //      refreshes the book without per-widget wiring. Failures invalidate
  //      too — a "failed" order may still have partially reached the broker.
  useEffect(() => {
    if (!enabled) return;
    const invalidate = () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.orders.all });
    };
    const onNotify = (e: Event) => {
      const detail = (e as CustomEvent<{ category?: string }>).detail;
      if (detail?.category === "order") invalidate();
    };
    window.addEventListener(ORDERS_CHANGED_EVENT, invalidate);
    window.addEventListener("flinttrade:notify", onNotify);
    return () => {
      window.removeEventListener(ORDERS_CHANGED_EVENT, invalidate);
      window.removeEventListener("flinttrade:notify", onNotify);
    };
  }, [enabled, queryClient]);

  return useQuery<Order[]>({
    queryKey: queryKeys.orders.all,
    queryFn: getOrderbook,
    enabled,
    staleTime: 5_000,
    refetchInterval: () => {
      if (!enabled) return false;
      return isAnyOrderSessionOpen() ? ORDERS_REFETCH_ACTIVE_MS : ORDERS_REFETCH_IDLE_MS;
    },
  });
}
