import { useState, useEffect } from "react";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillStore } from "@/stores/skillStore";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { RouteBanner } from "@/components/help/RouteBanner";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
import { Page, PageBody, PageHeader } from "@/components/layout/Page";
import TabTransition from "@/components/motion/TabTransition";
import PineEditor from "@/routes/lab/PineEditor";
import { type BacktestResult } from "@/services/ftApi";
import { type TabId, TABS } from "./LabRoute/types";
import { LabTabBar } from "./LabRoute/LabTabBar";
import { BacktestSection } from "./LabRoute/BacktestSection";
import { PortfolioBacktestSection } from "./LabRoute/PortfolioBacktestSection";
import { ForwardTestSection } from "./LabRoute/ForwardTest";
import { OptimizeSection } from "./LabRoute/OptimizeSection";
import { ResultsSection } from "./LabRoute/ResultsSection";
import StrategyBuilderTool from "@/tools/StrategyBuilder/StrategyBuilderTool";
import { hasPendingTemplate } from "@/tools/StrategyBuilder/templateBridge";
import { hasPendingPineDraft, OPEN_STRATEGY_BUILDER_EVENT } from "@/tools/StrategyBuilder/pineBridge";

export default function LabRoute() {
  useEffect(() => { useSkillStore.getState().trackAction("lab", "daysActive"); }, []);

  // A template stashed by the StrategyTemplates widget means the operator
  // just clicked "Load" there — land them straight in the Options Builder.
  const [activeTab, setActiveTab] = useState<TabId>(() =>
    hasPendingTemplate() || hasPendingPineDraft() ? "options-builder" : "backtest",
  );

  // The Pine Editor's "Open in Strategy Builder" hand-off — switch to the
  // builder tab when the editor dispatches the open event while we are
  // already mounted (the stash covers the not-yet-mounted case above).
  useEffect(() => {
    function onOpenBuilder() { setActiveTab("options-builder"); }
    window.addEventListener(OPEN_STRATEGY_BUILDER_EVENT, onOpenBuilder);
    return () => window.removeEventListener(OPEN_STRATEGY_BUILDER_EVENT, onOpenBuilder);
  }, []);
  const [lastResult, setLastResult] = useState<BacktestResult | null>(null);
  // Every completed run this session, keyed by strategy name — feeds the
  // Results tab's multi-run comparison (/backtest/compare).
  const [sessionRuns, setSessionRuns] = useState<Record<string, BacktestResult>>({});
  const level = useSkillLevel("lab");

  function handleBacktestResult(result: BacktestResult, strategy: string) {
    setLastResult(result);
    setSessionRuns((prev) => ({ ...prev, [strategy]: result }));
  }

  const visibleTabIds: TabId[] = (() => {
    if (level === "beginner") return ["backtest", "results", "options-builder", "pine-editor"];
    if (level === "intermediate") return ["backtest", "portfolio", "forward-test", "results", "options-builder", "pine-editor"];
    return ["backtest", "portfolio", "forward-test", "optimize", "results", "options-builder", "pine-editor"];
  })();

  const visibleTabs = TABS.filter((t) => visibleTabIds.includes(t.id));

  function renderTab(id: TabId) {
    switch (id) {
      case "backtest":
        return (
          <BacktestSection onResult={handleBacktestResult} lastResult={lastResult} />
        );
      case "portfolio":
        return <PortfolioBacktestSection />;
      case "forward-test":
        return <ForwardTestSection />;
      case "optimize":
        return <OptimizeSection />;
      case "results":
        return <ResultsSection lastResult={lastResult} sessionRuns={sessionRuns} />;
      case "options-builder":
        return <StrategyBuilderTool onClose={() => setActiveTab("backtest")} />;
      case "pine-editor":
        return <PineEditor />;
    }
  }

  return (
    <Page>
      <PageHeader
        title="Strategy Lab"
        tourTarget="strategy-picker"
        description={
          level === "beginner"
            ? "Pick a built-in strategy and run a backtest. No code needed."
            : "Backtest, forward test and optimise strategies before they trade."
        }
      >
        <LabTabBar active={activeTab} onChange={setActiveTab} tabs={visibleTabs} />
      </PageHeader>

      <PageBody
        role="tabpanel"
        id={`lab-tabpanel-${activeTab}`}
        aria-labelledby={`lab-tab-${activeTab}`}
        width={activeTab === "options-builder" || activeTab === "pine-editor" ? "wide" : "default"}
      >
        <div data-tour-target="backtest-results">
          <RouteBanner
            hintId="lab-import-strategy"
            text="Import a ready-made strategy from the library — open the Backtest tab and click 'Choose Strategy' to get started."
            className="mb-5"
          />
          <TabTransition tabKey={activeTab}>
            {renderTab(activeTab)}
          </TabTransition>
        </div>
      </PageBody>

      {level === "beginner" && (
        <SpotlightTour
          tourId="lab-beginner"
          steps={TOUR_DEFINITIONS["lab-beginner"] ?? []}
        />
      )}
    </Page>
  );
}
