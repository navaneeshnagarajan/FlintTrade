/**
 * TradeBottomPanel.tsx
 *
 * Bottom book on the /trade route.
 * Tabs: Positions | Orders | Alerts | Trade Log
 *
 * The panel opens at about 28% of the workspace so Practice positions and
 * orders are on the desk without dragging a zero-height splitter. The header
 * control can open it again after it has been collapsed.
 */

import { lazy, Suspense, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { detachedPanelProps } from "@/layout/flexLayoutAdapter";
import { cn } from "@/lib/utils";
import type { TradeBookTab } from "./tradeBookPanel";

const PositionsWidget = lazy(() => import("@/widgets/trading/Positions/PositionsWidget"));
const OrdersWidget = lazy(() => import("@/widgets/trading/Orders/OrdersWidget"));

type TabId = TradeBookTab | "alerts" | "log";

interface TabDef {
  id: TabId;
  label: string;
}

const TABS: TabDef[] = [
  { id: "positions", label: "Positions" },
  { id: "orders", label: "Orders" },
  { id: "alerts", label: "Alerts" },
  { id: "log", label: "Trade Log" },
];

function BookFallback({ label }: { label: string }) {
  return (
    <p role="status" className="text-text-disabled">
      Loading {label}…
    </p>
  );
}

export function TradeBottomPanel({ requestedTab }: { requestedTab?: TradeBookTab | null }) {
  const [activeTab, setActiveTab] = useState<TabId>(requestedTab ?? "positions");

  useEffect(() => {
    if (requestedTab) setActiveTab(requestedTab);
  }, [requestedTab]);

  return (
    <div className="h-full bg-surface-card border-t border-border-default flex flex-col overflow-hidden">
      <div
        role="tablist"
        aria-label="Trade panel tabs"
        className="flex items-center gap-0.5 px-2 h-7 border-b border-border-default shrink-0 bg-surface-elevated"
      >
        {TABS.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <Button
              key={tab.id}
              id={`trade-bottom-tab-${tab.id}`}
              type="button"
              role="tab"
              variant="ghost"
              size="sm"
              aria-selected={isActive}
              aria-controls={`trade-bottom-panel-${tab.id}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "px-2.5 h-5 text-xxs font-medium rounded",
                isActive
                  ? "bg-surface-active text-text-primary"
                  : "text-text-muted hover:text-text-secondary hover:bg-surface-hover",
              )}
            >
              {tab.label}
            </Button>
          );
        })}
      </div>

      <div
        id={`trade-bottom-panel-${activeTab}`}
        role="tabpanel"
        aria-labelledby={`trade-bottom-tab-${activeTab}`}
        tabIndex={0}
        className="flex-1 overflow-y-auto p-2 text-xs text-text-muted outline-none"
      >
        {activeTab === "positions" && (
          <Suspense fallback={<BookFallback label="positions" />}>
            <PositionsWidget {...detachedPanelProps("desk-positions")} />
          </Suspense>
        )}
        {activeTab === "orders" && (
          <Suspense fallback={<BookFallback label="orders" />}>
            <OrdersWidget {...detachedPanelProps("desk-orders")} />
          </Suspense>
        )}
        {activeTab === "alerts" && <p className="text-text-disabled">No active alerts</p>}
        {activeTab === "log" && <p className="text-text-disabled">No recent trades</p>}
      </div>
    </div>
  );
}
