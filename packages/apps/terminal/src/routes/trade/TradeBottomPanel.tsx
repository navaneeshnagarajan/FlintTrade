/**
 * TradeBottomPanel.tsx
 *
 * Collapsible bottom panel for the /trade route.
 * Shows tabs: Alerts | Trade Log
 *
 * The panel is collapsed by default (height = 0) and can be expanded via the
 * react-resizable-panels drag handle above it.
 *
 * Accessibility:
 * - Tab bar uses role="tablist" / role="tab" / role="tabpanel" with
 *   aria-selected and aria-controls linking.
 * - Tab panel has focus management via tabIndex.
 */

import { useState } from "react";
import { cn } from "@/lib/utils";

type TabId = "alerts" | "log";

interface TabDef {
  id: TabId;
  label: string;
}

const TABS: TabDef[] = [
  { id: "alerts", label: "Alerts" },
  { id: "log", label: "Trade Log" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TradeBottomPanel() {
  const [activeTab, setActiveTab] = useState<TabId>("alerts");

  return (
    <div className="h-full bg-surface-card border-t border-border-default flex flex-col overflow-hidden">
      {/* Tab bar */}
      <div
        role="tablist"
        aria-label="Trade panel tabs"
        className="flex items-center gap-0.5 px-2 h-7 border-b border-border-default shrink-0 bg-surface-elevated"
      >
        {TABS.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              id={`trade-bottom-tab-${tab.id}`}
              role="tab"
              aria-selected={isActive}
              aria-controls={`trade-bottom-panel-${tab.id}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "px-2.5 h-5 text-xxs font-medium rounded transition-colors",
                isActive
                  ? "bg-surface-active text-text-primary"
                  : "text-text-muted hover:text-text-secondary hover:bg-surface-hover"
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Panel content */}
      {TABS.map((tab) => (
        <div
          key={tab.id}
          id={`trade-bottom-panel-${tab.id}`}
          role="tabpanel"
          aria-labelledby={`trade-bottom-tab-${tab.id}`}
          tabIndex={0}
          hidden={activeTab !== tab.id}
          className="flex-1 overflow-y-auto p-2 text-xs text-text-muted outline-none"
        >
          {tab.id === "alerts" ? (
            <p className="text-text-disabled">No active alerts</p>
          ) : (
            <p className="text-text-disabled">No recent trades</p>
          )}
        </div>
      ))}
    </div>
  );
}
