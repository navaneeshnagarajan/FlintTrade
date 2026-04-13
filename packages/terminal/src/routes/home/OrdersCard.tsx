/**
 * OrdersCard — Last 3 orders with BUY/SELL badges.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { useOrders } from "@/hooks/useOrders";
import { ClipboardList, Loader2 } from "lucide-react";

export function OrdersCard() {
  const { data: orders, isLoading } = useOrders();
  const recentOrders = orders?.slice(0, 3) ?? [];

  return (
    <BentoCard size="default" label="Recent Orders" data-testid="orders-card">
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <ClipboardList size={13} className="text-[#505068]" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-[#505068]">
            Recent Orders
          </p>
        </div>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 size={16} className="animate-spin text-[#505068]" aria-label="Loading orders" />
          </div>
        ) : recentOrders.length === 0 ? (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-xs text-[#505068]">No recent orders</p>
          </div>
        ) : (
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
                        color: isBuy ? "#22c55e" : "#ef4444",
                        border: "1px solid",
                        borderColor: isBuy
                          ? "rgba(34,197,94,0.25)"
                          : "rgba(239,68,68,0.25)",
                      }}
                    >
                      {order.action}
                    </span>
                    <span className="text-xs text-[#e8e8f0] truncate">
                      {order.symbol}
                    </span>
                  </div>
                  <div className="text-right shrink-0 ml-2">
                    <p className="font-mono text-xs text-[#9090b0]">
                      {order.quantity} × ₹{order.price.toLocaleString("en-IN")}
                    </p>
                    <p
                      className="text-[10px]"
                      style={{
                        color:
                          order.status === "COMPLETE"
                            ? "#22c55e"
                            : order.status === "REJECTED"
                            ? "#ef4444"
                            : "#f59e0b",
                      }}
                    >
                      {order.status}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </BentoCard>
  );
}
