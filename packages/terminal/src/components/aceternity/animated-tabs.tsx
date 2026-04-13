/**
 * animated-tabs.tsx
 * Aceternity UI — Tabs with a sliding animated background pill on the active tab.
 * Adapted: React 19, framer-motion v12, TypeScript strict, no `any`.
 */
import { useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Types                                                                */
/* ------------------------------------------------------------------ */

export interface TabItem {
  /** Unique identifier. */
  id: string;
  /** Label shown in the tab button. */
  label: ReactNode;
  /** Content panel rendered when this tab is active. */
  content: ReactNode;
}

interface AnimatedTabsProps {
  tabs: TabItem[];
  /** ID of the initially active tab. Defaults to first tab. */
  defaultTabId?: string;
  /** Controlled active tab. */
  activeTabId?: string;
  /** Called when the user changes tab. */
  onTabChange?: (id: string) => void;
  className?: string;
  tabListClassName?: string;
  tabPanelClassName?: string;
  /** Whether to keep inactive panels in the DOM (for performance). Default false. */
  keepMounted?: boolean;
}

/* ------------------------------------------------------------------ */
/* Component                                                            */
/* ------------------------------------------------------------------ */

export function AnimatedTabs({
  tabs,
  defaultTabId,
  activeTabId: controlledActiveId,
  onTabChange,
  className,
  tabListClassName,
  tabPanelClassName,
  keepMounted = false,
}: AnimatedTabsProps) {
  const [internalActiveId, setInternalActiveId] = useState<string>(
    defaultTabId ?? tabs[0]?.id ?? "",
  );

  const activeId = controlledActiveId ?? internalActiveId;

  function handleTabClick(id: string) {
    if (!controlledActiveId) setInternalActiveId(id);
    onTabChange?.(id);
  }

  const activeTab = tabs.find((t) => t.id === activeId);

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      {/* Tab list */}
      <div
        role="tablist"
        className={cn(
          "relative flex w-fit items-center gap-1 rounded-glass-control p-1",
          "bg-glass-l1 border border-glass-l1 backdrop-glass",
          tabListClassName,
        )}
      >
        {tabs.map((tab) => {
          const isActive = tab.id === activeId;
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${tab.id}`}
              id={`tab-${tab.id}`}
              onClick={() => handleTabClick(tab.id)}
              className={cn(
                "relative z-10 rounded-[6px] px-3 py-1.5 text-sm font-medium",
                "transition-colors duration-150 outline-none",
                "focus-visible:ring-2 focus-visible:ring-ring",
                isActive
                  ? "text-text-primary"
                  : "text-text-muted hover:text-text-secondary",
              )}
            >
              {/* Sliding background pill */}
              {isActive && (
                <motion.div
                  layoutId="active-tab-bg"
                  className={cn(
                    "absolute inset-0 rounded-[6px]",
                    "bg-glass-l3 border border-glass-l2",
                  )}
                  transition={{ type: "spring", stiffness: 380, damping: 30 }}
                  aria-hidden="true"
                />
              )}
              <span className="relative z-10">{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab panels */}
      <div className={cn("relative", tabPanelClassName)}>
        {keepMounted ? (
          // All panels mounted; only active one is visible
          tabs.map((tab) => (
            <div
              key={tab.id}
              role="tabpanel"
              id={`panel-${tab.id}`}
              aria-labelledby={`tab-${tab.id}`}
              hidden={tab.id !== activeId}
            >
              {tab.content}
            </div>
          ))
        ) : (
          // Only active panel — with fade animation
          <AnimatePresence mode="wait">
            {activeTab && (
              <motion.div
                key={activeTab.id}
                role="tabpanel"
                id={`panel-${activeTab.id}`}
                aria-labelledby={`tab-${activeTab.id}`}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.15 }}
              >
                {activeTab.content}
              </motion.div>
            )}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}
