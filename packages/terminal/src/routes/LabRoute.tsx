import { useState, useEffect } from "react";
import { Zap } from "lucide-react";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillStore } from "@/stores/skillStore";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { RouteBanner } from "@/components/help/RouteBanner";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
import { ScrollArea } from "@/components/ui/scroll-area";
import TabTransition from "@/components/motion/TabTransition";
import PineEditor from "@/routes/lab/PineEditor";
import { type BacktestResult } from "@/services/ftApi";
import { type TabId, TABS } from "./LabRoute/types";
import { LabTabBar } from "./LabRoute/LabTabBar";
import { BacktestSection } from "./LabRoute/BacktestSection";
import { ForwardTestSection } from "./LabRoute/ForwardTest";
import { OptimizeSection } from "./LabRoute/OptimizeSection";
import { ResultsSection } from "./LabRoute/ResultsSection";

export default function LabRoute() {
  useEffect(() => { useSkillStore.getState().trackAction("lab", "daysActive"); }, []);

  const [activeTab, setActiveTab] = useState<TabId>("backtest");
  const [lastResult, setLastResult] = useState<BacktestResult | null>(null);
  const level = useSkillLevel("lab");

  const visibleTabIds: TabId[] = (() => {
    if (level === "beginner") return ["backtest", "results", "pine-editor"];
    if (level === "intermediate") return ["backtest", "forward-test", "results", "pine-editor"];
    return ["backtest", "forward-test", "optimize", "results", "pine-editor"];
  })();

  const visibleTabs = TABS.filter((t) => visibleTabIds.includes(t.id));

  function renderTab(id: TabId) {
    switch (id) {
      case "backtest":
        return (
          <BacktestSection onResult={setLastResult} lastResult={lastResult} />
        );
      case "forward-test":
        return <ForwardTestSection />;
      case "optimize":
        return <OptimizeSection />;
      case "results":
        return <ResultsSection lastResult={lastResult} />;
      case "pine-editor":
        return <PineEditor />;
    }
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <RouteBanner
        hintId="lab-import-strategy"
        text="Import a ready-made strategy from the library — open the Backtest tab and click 'Choose Strategy' to get started."
      />
      <div className="border-b border-glass-l1 bg-[rgba(12,12,20,0.85)] backdrop-blur-md px-6 pt-4 pb-0">
        <div className="flex items-center gap-3 pb-3" data-tour-target="strategy-picker">
          <Zap className="w-6 h-6 text-accent" />
          <div>
            <h1 className="font-heading font-bold text-lg text-text-primary">
              {level === "beginner" ? "Try a Strategy" : "Strategy Lab"}
            </h1>
            <p className="text-xxs text-text-muted">
              {level === "beginner"
                ? "Pick a built-in strategy and run a backtest — no code needed"
                : "Backtest, forward test, and optimise strategies — no broker has this built-in"}
            </p>
          </div>
        </div>
        <LabTabBar active={activeTab} onChange={setActiveTab} tabs={visibleTabs} />
      </div>

      <div
        role="tabpanel"
        id={`lab-tabpanel-${activeTab}`}
        aria-labelledby={`lab-tab-${activeTab}`}
        className="flex-1"
      >
        <ScrollArea className="h-full">
          <div className="p-6 max-w-5xl mx-auto" data-tour-target="backtest-results">
            <TabTransition tabKey={activeTab}>
              {renderTab(activeTab)}
            </TabTransition>
          </div>
        </ScrollArea>
      </div>

      {level === "beginner" && (
        <SpotlightTour
          tourId="lab-beginner"
          steps={TOUR_DEFINITIONS["lab-beginner"] ?? []}
        />
      )}
    </div>
  );
}
