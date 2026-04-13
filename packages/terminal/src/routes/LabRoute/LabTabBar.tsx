import { motion } from "framer-motion";
import { motionConfig } from "@/lib/motion";
import { type TabId, type TabDef, TABS } from "./types";

export interface LabTabBarProps {
  active: TabId;
  onChange: (id: TabId) => void;
  tabs?: TabDef[];
}

export function LabTabBar({ active, onChange, tabs = TABS }: LabTabBarProps) {
  return (
    <div
      role="tablist"
      aria-label="Strategy Lab sections"
      className="flex items-center gap-1 border-b border-border-default bg-surface-card px-6"
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = active === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            aria-controls={`lab-tabpanel-${tab.id}`}
            id={`lab-tab-${tab.id}`}
            onClick={() => onChange(tab.id)}
            className={[
              "relative flex items-center gap-2 px-4 py-3 text-sm font-sans transition-colors select-none",
              isActive
                ? "text-accent"
                : "text-text-secondary hover:text-text-primary",
            ].join(" ")}
          >
            <Icon className="w-3.5 h-3.5" />
            {tab.label}
            {isActive && (
              <motion.div
                layoutId="lab-tab-indicator"
                className="absolute bottom-0 left-0 right-0 h-0.5 bg-accent rounded-t"
                transition={motionConfig.transitions.tab}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
