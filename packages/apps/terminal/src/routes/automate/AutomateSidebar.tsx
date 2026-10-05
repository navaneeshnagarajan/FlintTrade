/**
 * AutomateSidebar — labelled section navigation for Automate.
 *
 * Labels are always visible (the old 48px icon rail hid them until hover).
 * Status dots reflect live state (kill switch, running strategy count).
 */

import { Clock, Activity, FileText, Settings2, FileCode2, Webhook } from "lucide-react";
import { SectionNav } from "@/components/layout/SectionNav";
import "./shared";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SectionId = "schedules" | "monitors" | "logs" | "strategies" | "settings" | "webhooks";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: typeof Clock;
  desc: string;
}

export const SECTIONS: SectionDef[] = [
  { id: "schedules",  label: "Schedules",           icon: Clock,      desc: "Cron jobs & timed executions" },
  { id: "monitors",   label: "Monitors",            icon: Activity,   desc: "Live strategy monitoring" },
  { id: "strategies", label: "Strategies",          icon: FileCode2,  desc: "Upload and run Python strategies" },
  { id: "webhooks",   label: "Webhooks",             icon: Webhook,    desc: "Signed relay endpoint registry" },
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

function sectionDot(
  id: SectionId,
  killSwitchActive: boolean,
  runningCount: number,
  uploadedRunningCount: number,
): string | null {
  if (id === "settings" && killSwitchActive) return "ft-dot-kill";
  if (id === "monitors" && runningCount > 0) return "ft-dot-running";
  if (id === "strategies" && uploadedRunningCount > 0) return "ft-dot-running";
  if (id === "schedules" && !killSwitchActive) return "ft-dot-paused";
  return null;
}

export default function AutomateSidebar({
  activeSection,
  onSelect,
  killSwitchActive,
  runningCount,
  uploadedRunningCount,
  sections = SECTIONS,
}: AutomateSidebarProps) {
  const items = sections.map((section) => {
    const dot = sectionDot(section.id, killSwitchActive, runningCount, uploadedRunningCount);
    return {
      id: section.id,
      label: section.label,
      icon: section.icon,
      title: section.desc,
      indicator: dot ? <span className={dot} aria-hidden="true" /> : undefined,
    };
  });

  return (
    <SectionNav<SectionId>
      groups={[{ id: "automate", items }]}
      value={activeSection}
      onChange={onSelect}
      label="Automation sections"
      idPrefix="automate"
      data-testid="automate-section-nav"
    />
  );
}
