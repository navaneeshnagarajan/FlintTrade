/**
 * MarketIntelligenceTool — 14-tab market intelligence dashboard
 * Adapted patterns from etftracker and oipulse repos.
 */

import { useState } from "react";
import { BarChart3, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useModeStore } from "@/stores/modeStore";
import { SAMPLE_DATA_TABS, TABS } from "./data";
import type { TabId } from "./types";
import { MarketBreadthTab } from "./tabs/MarketBreadthTab";
import { FiiDiiFlowsTab } from "./tabs/FiiDiiFlowsTab";
import { SectorRotationTab } from "./tabs/SectorRotationTab";
import { SectorHeatmapTab } from "./tabs/SectorHeatmapTab";
import { IndiaVixTab } from "./tabs/IndiaVixTab";
import { GlobalIndicesTab } from "./tabs/GlobalIndicesTab";
import { ParticipantOITab } from "./tabs/ParticipantOITab";
import { DeliveryDataTab } from "./tabs/DeliveryDataTab";
import { CorrelationMatrixTab } from "./tabs/CorrelationMatrixTab";
import { AnnouncementsTab } from "./tabs/AnnouncementsTab";
import { GexTab } from "./tabs/GexTab";
import { IVSmileTab } from "./tabs/IVSmileTab";
import { MaxPainTab } from "./tabs/MaxPainTab";
import { OIProfileTab } from "./tabs/OIProfileTab";

interface Props {
  onClose?: () => void;
}

const SELF_SCROLLING_TABS: TabId[] = [
  "breadth",
  "fiidii",
  "vix",
  "participantoi",
  "correlation",
  "gex",
  "ivsmile",
  "maxpain",
  "oiprofile",
];

const TAB_CONTENT: Record<TabId, () => React.ReactNode> = {
  breadth: () => <MarketBreadthTab />,
  fiidii: () => <FiiDiiFlowsTab />,
  sectors: () => <SectorRotationTab />,
  heatmap: () => <SectorHeatmapTab />,
  vix: () => <IndiaVixTab />,
  global: () => <GlobalIndicesTab />,
  participantoi: () => <ParticipantOITab />,
  delivery: () => <DeliveryDataTab />,
  correlation: () => <CorrelationMatrixTab />,
  announcements: () => <AnnouncementsTab />,
  gex: () => <GexTab />,
  ivsmile: () => <IVSmileTab />,
  maxpain: () => <MaxPainTab />,
  oiprofile: () => <OIProfileTab />,
};

export default function MarketIntelligenceTool({ onClose }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>("breadth");
  const isExploreMode = useModeStore((s) => s.mode === "explore");

  const currentTab = TABS.find((t) => t.id === activeTab);
  const isSampleData = isExploreMode || SAMPLE_DATA_TABS.includes(activeTab);

  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card shrink-0">
        <div className="flex items-center gap-2">
          <BarChart3 size={16} className="text-primary" />
          <span className="font-heading font-bold text-lg text-text-primary">Market Intelligence</span>
          {currentTab && (
            <>
              <span className="text-text-disabled">/</span>
              <span className="text-xs text-text-secondary">{currentTab.label}</span>
            </>
          )}
          {isSampleData ? (
            <Badge className="text-xs h-4 px-1.5 bg-amber-500/10 text-amber-400 border border-amber-500/30">
              Sample Data
            </Badge>
          ) : (
            <Badge className="text-xs h-4 px-1.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
              Live
            </Badge>
          )}
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} className="h-6 w-6 text-text-muted hover:text-text-primary">
          <X size={15} />
        </Button>
      </div>

      {/* Body: sidebar + content */}
      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <div className="w-44 border-r border-border-default bg-surface-card shrink-0 overflow-y-auto py-1.5">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={[
                  "w-full flex items-center gap-2 px-3 py-2 font-heading font-medium text-xs transition-colors text-left",
                  isActive
                    ? "bg-neutral-bg/60 text-primary border-r-2 border-primary"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-elevated",
                ].join(" ")}
              >
                <Icon size={13} className="shrink-0" />
                <span className="truncate">{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Content area */}
        {SELF_SCROLLING_TABS.includes(activeTab) ? (
          <div className="flex-1 min-h-0 overflow-hidden">
            {TAB_CONTENT[activeTab]()}
          </div>
        ) : (
          <ScrollArea className="flex-1">
            <div>{TAB_CONTENT[activeTab]()}</div>
          </ScrollArea>
        )}
      </div>
    </div>
  );
}
