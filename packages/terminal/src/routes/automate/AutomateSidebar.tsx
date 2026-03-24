/**
 * AutomateSidebar — icon rail navigation for the Automation Hub.
 *
 * 48px collapsed, ~168px expanded on hover via Framer Motion.
 * Status dots reflect live state (kill switch, running strategy count).
 */

import { useState } from "react";
import { Workflow, Clock, Activity, FileText, Settings2, FileCode2 } from "lucide-react";
import { motion } from "framer-motion";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SectionId = "flows" | "schedules" | "monitors" | "logs" | "strategies" | "settings";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: typeof Workflow;
  desc: string;
}

export const SECTIONS: SectionDef[] = [
  { id: "flows",      label: "Flow Builder",       icon: Workflow,   desc: "Visual 54-node automation builder" },
  { id: "schedules",  label: "Schedules",           icon: Clock,      desc: "Cron jobs & timed executions" },
  { id: "monitors",   label: "Monitors",            icon: Activity,   desc: "Live strategy monitoring" },
  { id: "strategies", label: "Strategies",          icon: FileCode2,  desc: "Upload and run Python strategies" },
  { id: "logs",       label: "Execution Logs",      icon: FileText,   desc: "History of automated actions" },
  { id: "settings",   label: "Automation Settings", icon: Settings2,  desc: "Kill switches, limits, Telegram alerts" },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AutomateSidebarProps {
  activeSection: SectionId;
  onSelect: (id: SectionId) => void;
  killSwitchActive: boolean;
  runningCount: number;
  uploadedRunningCount: number;
  /** Optional filtered list. Defaults to all SECTIONS. */
  sections?: SectionDef[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AutomateSidebar({
  activeSection,
  onSelect,
  killSwitchActive,
  runningCount,
  uploadedRunningCount,
  sections = SECTIONS,
}: AutomateSidebarProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <motion.nav
      aria-label="Section navigation"
      onHoverStart={() => setExpanded(true)}
      onHoverEnd={() => setExpanded(false)}
      animate={{ width: expanded ? 168 : 48 }}
      transition={{ duration: 0.2, ease: [0.25, 1, 0.5, 1] }}
      className="relative shrink-0 border-r border-border-default bg-surface-card overflow-hidden py-2 flex flex-col gap-0.5"
      style={{ minWidth: 48 }}
    >
      {sections.map((section) => {
        const Icon     = section.icon;
        const isActive = activeSection === section.id;

        const dotClass =
          section.id === "settings" && killSwitchActive
            ? "ft-dot-kill"
            : section.id === "monitors" && runningCount > 0
            ? "ft-dot-running"
            : section.id === "strategies" && uploadedRunningCount > 0
            ? "ft-dot-running"
            : section.id === "schedules" && !killSwitchActive
            ? "ft-dot-paused"
            : null;

        return (
          <button
            key={section.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onSelect(section.id)}
            aria-current={isActive ? "true" : undefined}
            title={expanded ? undefined : section.label}
            className={`
              relative flex items-center gap-2.5 h-10 px-3 text-sm font-sans
              transition-colors duration-150 border-l-2 overflow-hidden
              ${
                isActive
                  ? "text-accent bg-accent/10 border-accent"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface-base border-transparent"
              }
            `}
          >
            <span className="shrink-0 flex items-center justify-center w-4 h-4 relative">
              <Icon size={16} />
              {dotClass && (
                <span
                  className={dotClass}
                  style={{ position: "absolute", top: -3, right: -3 }}
                />
              )}
            </span>

            <motion.span
              animate={{ opacity: expanded ? 1 : 0 }}
              transition={{ duration: 0.12, ease: "easeOut" }}
              className="whitespace-nowrap text-xs font-medium leading-none"
            >
              {section.label}
            </motion.span>
          </button>
        );
      })}
    </motion.nav>
  );
}
