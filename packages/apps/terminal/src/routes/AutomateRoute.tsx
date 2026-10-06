import React, { useState, useEffect } from "react";
import { useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Page, PageBody, PageHeader } from "@/components/layout/Page";
import TabTransition from "@/components/motion/TabTransition";
import { getSafetyConfig, getRunningStrategies, getUploadedStrategies } from "@/services/ftApi";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillStore } from "@/stores/skillStore";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";

import AutomateSidebar, { SECTIONS, type SectionId } from "./automate/AutomateSidebar";
import CronSection        from "./automate/CronSection";
import MonitorsSection    from "./automate/MonitorsSection";
import LogsSection        from "./automate/LogsSection";
import StrategiesSection  from "./automate/StrategiesSection";
import SettingsSection    from "./automate/SettingsSection";
import WebhooksSection    from "./automate/WebhooksSection";

const SAFETY_CONFIG_QUERY_KEY = ["safetyConfig"] as const;

function sectionIdFromHash(hash: string): SectionId | null {
  const id = hash.replace(/^#/, "");
  return SECTIONS.some((section) => section.id === id) ? (id as SectionId) : null;
}

export default function AutomateRoute() {
  useEffect(() => { useSkillStore.getState().trackAction("automate", "daysActive"); }, []);

  const location = useLocation();
  const hashedSection = sectionIdFromHash(location.hash);
  const level = useSkillLevel("automate");

  // Density adaptation:
  // Beginner: Alerts/Monitors + Settings only (hide Schedules and Strategies)
  // Intermediate: Schedules + Monitors + Logs + emergency settings
  // Advanced: All sections
  // A deep link such as /automate#schedules still opens that section.
  const visibleSectionIds: SectionId[] = (() => {
    const base: SectionId[] = level === "beginner"
      ? ["monitors", "settings"]
      : level === "intermediate"
        ? ["schedules", "monitors", "webhooks", "logs", "settings"]
        : ["schedules", "monitors", "strategies", "webhooks", "logs", "settings"];
    if (hashedSection && !base.includes(hashedSection)) return [hashedSection, ...base];
    return base;
  })();

  const visibleSections = SECTIONS.filter((s) => visibleSectionIds.includes(s.id));

  // Default to the hash target, otherwise the first visible section.
  const defaultSection = hashedSection ?? visibleSectionIds[0] ?? "monitors";
  const [activeSection, setActiveSection] = useState<SectionId>(defaultSection);

  useEffect(() => {
    if (hashedSection) setActiveSection(hashedSection);
  }, [hashedSection]);

  // Lightweight queries for rail status dots — same keys fetched by each section on mount,
  // so no extra network requests are made.
  const { data: safetyData } = useQuery({
    queryKey: SAFETY_CONFIG_QUERY_KEY,
    queryFn: getSafetyConfig,
    refetchInterval: 5_000,
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
    (s) => s.status === "running",
  ).length;
  const uploadedRunningCount = (uploadedStrategiesData ?? []).filter(
    (s) => s.status === "running",
  ).length;

  const sectionContent: Record<SectionId, React.ReactNode> = {
    schedules:  <CronSection />,
    monitors:   <MonitorsSection />,
    strategies: <StrategiesSection />,
    webhooks:   <WebhooksSection />,
    logs:       <LogsSection />,
    settings:   <SettingsSection />,
  };

  return (
    <Page>
      <PageHeader
        title="Automate"
        description="Schedules, strategy monitors, webhooks and the safety controls that stop them."
        meta={
          killSwitchActive ? (
            <span className="flex items-center gap-1.5 rounded-full border border-loss/30 bg-loss/10 px-2.5 py-0.5">
              <span className="ft-dot-kill" aria-hidden="true" />
              <span className="text-xs font-medium text-[var(--color-bearish-text,var(--color-loss))]">
                Kill Switch Active
              </span>
            </span>
          ) : null
        }
      />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
        <AutomateSidebar
          activeSection={activeSection}
          onSelect={setActiveSection}
          killSwitchActive={killSwitchActive}
          sections={visibleSections}
          runningCount={runningCount}
          uploadedRunningCount={uploadedRunningCount}
        />

        <PageBody
            role="tabpanel"
            id={`automate-tabpanel-${activeSection}`}
            aria-labelledby={`automate-tab-${activeSection}`}
          >
            <TabTransition tabKey={activeSection}>
              {sectionContent[activeSection]}
            </TabTransition>
          </PageBody>
      </div>

      {/* Guided tour — beginner only, first visit */}
      {level === "beginner" && (
        <SpotlightTour
          tourId="automate-beginner"
          steps={TOUR_DEFINITIONS["automate-beginner"] ?? []}
        />
      )}
    </Page>
  );
}
