/**
 * OrdersCard — Last 3 orders with BUY/SELL badges.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { useOrders } from "@/hooks/useOrders";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { getDemoOrders } from "@/hooks/useModeData";
import {
  resolveAccountQueryUi,
  runGuardedAccountRefetch,
} from "@/lib/accountQueryState";
import { useModeStore } from "@/stores/modeStore";
import { DemoBadge } from "./DemoBadge";
import { ClipboardList, Loader2 } from "lucide-react";

export function OrdersCard() {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const accountReadsEnabled = useAccountReadsEnabled();
  const query = useOrders({ enabled: accountReadsEnabled });
  const orders = isExplore ? getDemoOrders() : query.data;
  const recentOrders = orders?.slice(0, 3) ?? [];
  const isError = !isExplore && query.isError;
  const queryUi = resolveAccountQueryUi({
    accountReadsEnabled,
    fetchStatus: query.fetchStatus,
    hasData: recentOrders.length > 0,
    isError,
    isExplore,
    isLoading: query.isLoading,
  });

  return (
    <BentoCard size="default" label="Recent Orders" data-testid="orders-card">
      {isExplore && <DemoBadge />}
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <ClipboardList size={13} className="text-text-muted" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
            Recent Orders
          </p>
        </div>

        {isError && (
          <div
            role="alert"
            className="flex items-center justify-between gap-2 text-[10px] text-loss"
          >
            <span>
              Orders unavailable
              {queryUi.isFrozen ? " — displayed orders are frozen" : ""}
            </span>
            <button
              type="button"
              onClick={() => runGuardedAccountRefetch(queryUi.canRefetch, query.refetch)}
              disabled={!queryUi.canRefetch || query.isFetching}
              className="shrink-0 font-medium underline disabled:opacity-50"
            >
              {query.isFetching ? "Retrying…" : "Retry orders"}
            </button>
          </div>
        )}

        {queryUi.isFrozen && !isError && (
          <p role="status" className="text-[10px] text-warning">
            {queryUi.isPaused
              ? "Offline — displayed orders are frozen"
              : "Broker disconnected — displayed orders are frozen"}
          </p>
        )}

        {queryUi.showInitialLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 size={16} className="animate-spin text-text-muted" aria-label="Loading orders" />
          </div>
        ) : recentOrders.length > 0 ? (
          <div className="flex-1 space-y-2">
            {recentOrders.map((order) => {
              const isBuy = order.action === "BUY";
              return (
                <div
                  key={order.orderId}
                  className="flex items-center justify-between py-1"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className="inline-block px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase shrink-0"
                      style={{
                        background: isBuy
                          ? "rgba(34,197,94,0.12)"
                          : "rgba(239,68,68,0.12)",
                        color: isBuy ? "var(--color-bullish-text)" : "var(--color-bearish-text)",
                        border: "1px solid",
                        borderColor: isBuy
                          ? "rgba(34,197,94,0.25)"
                          : "rgba(239,68,68,0.25)",
                      }}
                    >
                      {order.action}
                    </span>
                    <span className="text-xs text-text-primary truncate">
                      {order.symbol}
                    </span>
                  </div>
                  <div className="text-right shrink-0 ml-2">
                    <p className="font-mono text-xs text-text-secondary">
                      {order.quantity} × ₹{order.price.toLocaleString("en-IN")}
                    </p>
                    <p
                      className="text-[10px]"
                      style={{
                        color:
                          order.status === "COMPLETE"
                            ? "var(--color-bullish-text)"
                            : order.status === "REJECTED"
                            ? "var(--color-bearish-text)"
                            : "var(--color-warning-text)",
                      }}
                    >
                      {order.status}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : !isError ? (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-xs text-text-muted">
              {isExplore
                ? "No recent orders"
                : queryUi.isPaused
                  ? "Orders unavailable while offline"
                  : accountReadsEnabled
                    ? "No recent orders"
                    : "Connect a broker to load orders"}
            </p>
          </div>
        ) : null}
      </div>
    </BentoCard>
  );
}
