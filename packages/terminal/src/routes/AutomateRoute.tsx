import React, { useState, useEffect } from "react";
import { Workflow } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { ScrollArea } from "@/components/ui/scroll-area";
import TabTransition from "@/components/motion/TabTransition";
import { getSafetyConfig, getRunningStrategies, getUploadedStrategies } from "@/services/ftApi";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillStore } from "@/stores/skillStore";

import AutomateSidebar, { SECTIONS, type SectionId } from "./automate/AutomateSidebar";
import FlowsSection       from "./automate/FlowsSection";
import CronSection        from "./automate/CronSection";
import MonitorsSection    from "./automate/MonitorsSection";
import LogsSection        from "./automate/LogsSection";
import StrategiesSection  from "./automate/StrategiesSection";
import SettingsSection    from "./automate/SettingsSection";

export default function AutomateRoute() {
  useEffect(() => { useSkillStore.getState().trackAction("automate", "daysActive"); }, []);

  const level = useSkillLevel("automate");

  // Density adaptation:
  // Beginner: Alerts/Monitors + Settings only (hide Flows, Cron, Strategies)
  // Intermediate: Flows + Schedules + Monitors + Logs
  // Advanced: All sections
  const visibleSectionIds: SectionId[] = (() => {
    if (level === "beginner") return ["monitors", "settings"];
    if (level === "intermediate") return ["flows", "schedules", "monitors", "logs"];
    return ["flows", "schedules", "monitors", "strategies", "logs", "settings"];
  })();

  const visibleSections = SECTIONS.filter((s) => visibleSectionIds.includes(s.id));

  // Default to the first visible section for the current skill level
  const defaultSection = visibleSectionIds[0] ?? "monitors";
  const [activeSection, setActiveSection] = useState<SectionId>(defaultSection);

  // Lightweight queries for rail status dots — same keys fetched by each section on mount,
  // so no extra network requests are made.
  const { data: safetyData } = useQuery({
    queryKey: ["safetyConfig"],
    queryFn: getSafetyConfig,
  });

  const { data: strategiesData } = useQuery({
    queryKey: ["runningStrategies"],
    queryFn: getRunningStrategies,
    refetchInterval: 10000,
  });

  const { data: uploadedStrategiesData } = useQuery({
    queryKey: ["uploadedStrategies"],
    queryFn: getUploadedStrategies,
    refetchInterval: 10000,
  });

  const killSwitchActive = safetyData?.kill_switch_active ?? false;
  const runningCount = (strategiesData ?? []).filter(
    (s) => s.status.toLowerCase() === "running",
  ).length;
  const uploadedRunningCount = (uploadedStrategiesData ?? []).filter(
    (s) => s.status === "running",
  ).length;

  const sectionContent: Record<SectionId, React.ReactNode> = {
    flows:      <FlowsSection />,
    schedules:  <CronSection />,
    monitors:   <MonitorsSection />,
    strategies: <StrategiesSection />,
    logs:       <LogsSection />,
    settings:   <SettingsSection />,
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 py-4 shrink-0">
        <div className="flex items-center gap-3">
          <Workflow className="w-6 h-6 text-accent" />
          <div>
            <h1 className="font-heading font-bold text-lg text-text-primary">Automation Hub</h1>
            <p className="text-xxs text-text-muted">
              Flow builder, cron scheduler, Telegram alerts, and safety controls
            </p>
          </div>
          {killSwitchActive && (
            <div className="ml-auto flex items-center gap-1.5 px-3 py-1 rounded-full bg-loss/10 border border-loss/30">
              <span className="ft-dot-kill" />
              <span className="text-xs text-loss font-medium">Kill Switch Active</span>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <AutomateSidebar
          activeSection={activeSection}
          onSelect={setActiveSection}
          killSwitchActive={killSwitchActive}
          sections={visibleSections}
          runningCount={runningCount}
          uploadedRunningCount={uploadedRunningCount}
        />

        <ScrollArea className="flex-1">
          <TabTransition tabKey={activeSection} className="p-6 max-w-4xl mx-auto">
            {sectionContent[activeSection]}
          </TabTransition>
        </ScrollArea>
      </div>
    </div>
  );
}
