/**
 * MarketOverviewWidget — the terminal's one market-overview surface.
 *
 * Six tabs over the market's vital signs:
 *
 *   Breadth       advances/declines, A/D line, 52-week highs/lows, McClellan,
 *                 breadth thrust, per-index split, top movers
 *   Sectors       position map (treemap/grid/table) plus two projections of
 *                 the live sectors/rotation plane — timeframe-ranked bars and
 *                 the market-cap-weighted heatmap
 *   Rotation      sector and portfolio Relative Rotation Graphs
 *   Flows         FII long/short positioning + FII/DII cash flows
 *   Indices       live NSE index tick cards + global indices table
 *   Contribution  index move decomposed by constituent weight
 *
 * Merged on 2026-07-26 from seven widgets that each watched a slice of the
 * same market: MarketBreadth, SectorMap, SectorPerformance, GlobalIndices,
 * FiiLongShort, MarketSummary and IndexContribution (plus the per-index
 * breadth split and live FII/DII wiring from the MarketIntelligence tool).
 *
 * What each contributed:
 *   MarketBreadth     the zod-validated breadth fetches and the strictest
 *                     provenance model (live history only when the backend
 *                     claims it; absent flags are sample)
 *   SectorMap         squarified treemap/grid/table with drill-down, the RRG
 *                     canvases, and the metric-labelling fix (live colours
 *                     are position P&L%, not day change — and say so)
 *   SectorPerformance the timeframe-ranked bar view. It reads
 *                     sectors/rotation, which is still a BACKEND STUB
 *                     (unconditional is_sample_data), so the bars stay
 *                     honestly badged sample until that route is built
 *   GlobalIndices     the world-indices table with the codebase's best
 *                     fail-closed provenance handling
 *   FiiLongShort      the futures-bias gauge and FII segment table
 *   MarketSummary     the live index tick cards and top movers, with
 *                     per-section Live/Sample chips
 *   IndexContribution the constituent contribution decomposition (D9)
 *
 * `params.tab` selects the opening tab and is persisted through
 * `api.updateParameters`, which is also how the seven retired ids keep
 * resolving into the view their operators saved; `params.view` opens a
 * specific view within the Sectors ("bars"/"treemap"/"grid"/"table") and
 * Rotation ("sectors"/"portfolio") tabs.
 *
 * Provenance rule for every tab: `is_sample_data !== false` is sample, and
 * sample surfaces carry a visible badge. No surface fabricates data without
 * an explore/sample guard.
 */

import { memo, useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowUpDown,
  BarChart4,
  Globe,
  LayoutGrid,
  PieChart,
  Repeat,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { WidgetProps } from "@/types/widgets";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

import BreadthTab from "./tabs/BreadthTab";
import SectorsTab from "./tabs/SectorsTab";
import RotationTab from "./tabs/RotationTab";
import FlowsTab from "./tabs/FlowsTab";
import IndicesTab from "./tabs/IndicesTab";
import ContributionTab from "./tabs/ContributionTab";
import type { MarketOverviewTab, RotationView, SectorView } from "./types";

// ---------------------------------------------------------------------------
// Tab identity
// ---------------------------------------------------------------------------

const OVERVIEW_TABS: readonly MarketOverviewTab[] = [
  "breadth",
  "sectors",
  "rotation",
  "flows",
  "indices",
  "contribution",
];

const SECTOR_VIEWS: readonly SectorView[] = ["treemap", "grid", "table", "bars", "heatmap"];
const ROTATION_VIEWS: readonly RotationView[] = ["sectors", "portfolio"];

/** Panel params this widget understands. */
export interface MarketOverviewPanelParams {
  /** Which tab to open on. Retired ids arrive here — see RETIRED_WIDGET_IDS. */
  tab?: string;
  /** Opening view within the Sectors or Rotation tab. */
  view?: string;
}

/**
 * Resolve a panel-supplied tab id to a tab this widget actually has.
 *
 * @param raw - The `tab` param from a saved layout, which may be anything.
 * @returns The matching tab, or `"breadth"` for unknown or absent values.
 */
export function resolveMarketOverviewTab(raw: unknown): MarketOverviewTab {
  return typeof raw === "string" && (OVERVIEW_TABS as readonly string[]).includes(raw)
    ? (raw as MarketOverviewTab)
    : "breadth";
}

/** Resolve a panel-supplied Sectors view; defaults to the treemap. */
export function resolveSectorView(raw: unknown): SectorView {
  return typeof raw === "string" && (SECTOR_VIEWS as readonly string[]).includes(raw)
    ? (raw as SectorView)
    : "treemap";
}

/** Resolve a panel-supplied Rotation view; defaults to the sector RRG. */
export function resolveRotationView(raw: unknown): RotationView {
  return typeof raw === "string" && (ROTATION_VIEWS as readonly string[]).includes(raw)
    ? (raw as RotationView)
    : "sectors";
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

const TRIGGER_CLS =
  "text-xs h-5 px-2 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted rounded";

function MarketOverviewWidget(props: WidgetProps) {
  const panelParams = props.params as MarketOverviewPanelParams | undefined;
  const track = useTrackBehavior();
  const [tab, setTab] = useState<MarketOverviewTab>(() => resolveMarketOverviewTab(panelParams?.tab));

  // Persist the chosen tab into the panel params so a saved layout reopens on
  // it — this is also how the seven retired ids land on the surface their
  // operators used.
  const handleTabChange = useCallback(
    (next: string) => {
      const resolved = resolveMarketOverviewTab(next);
      if (resolved === tab) return;
      setTab(resolved);
      props.api?.updateParameters({ tab: resolved });
    },
    [panelParams, props.api, tab],
  );

  useEffect(() => {
    track("trade", `market_overview_tab_${tab}`);
  }, [tab, track]);

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default shrink-0">
        <LayoutGrid size={11} className="text-text-muted" aria-hidden="true" />
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
          Market Overview
        </span>
      </div>

      {/* Tabs */}
      <Tabs
        value={tab}
        onValueChange={handleTabChange}
        className="flex-1 flex flex-col overflow-hidden"
      >
        <TabsList
          aria-label="Market overview sections"
          className="shrink-0 h-7 bg-surface-card rounded-none border-b border-border-default px-2 gap-1 justify-start"
        >
          <TabsTrigger value="breadth" className={TRIGGER_CLS}>
            <BarChart4 size={9} className="mr-1" aria-hidden="true" />
            Breadth
          </TabsTrigger>
          <TabsTrigger value="sectors" className={TRIGGER_CLS}>
            <Activity size={9} className="mr-1" aria-hidden="true" />
            Sectors
          </TabsTrigger>
          <TabsTrigger value="rotation" className={TRIGGER_CLS}>
            <Repeat size={9} className="mr-1" aria-hidden="true" />
            Rotation
          </TabsTrigger>
          <TabsTrigger value="flows" className={TRIGGER_CLS}>
            <ArrowUpDown size={9} className="mr-1" aria-hidden="true" />
            Flows
          </TabsTrigger>
          <TabsTrigger value="indices" className={TRIGGER_CLS}>
            <Globe size={9} className="mr-1" aria-hidden="true" />
            Indices
          </TabsTrigger>
          <TabsTrigger value="contribution" className={TRIGGER_CLS}>
            <PieChart size={9} className="mr-1" aria-hidden="true" />
            Contribution
          </TabsTrigger>
        </TabsList>

        <TabsContent value="breadth" className="flex-1 overflow-hidden m-0 p-0">
          <BreadthTab />
        </TabsContent>
        <TabsContent value="sectors" className="flex-1 overflow-hidden m-0 p-0">
          <SectorsTab initialView={resolveSectorView(panelParams?.view)} />
        </TabsContent>
        <TabsContent value="rotation" className="flex-1 overflow-hidden m-0 p-0">
          <RotationTab initialView={resolveRotationView(panelParams?.view)} />
        </TabsContent>
        <TabsContent value="flows" className="flex-1 overflow-hidden m-0 p-0">
          <FlowsTab />
        </TabsContent>
        <TabsContent value="indices" className="flex-1 overflow-hidden m-0 p-0">
          <IndicesTab />
        </TabsContent>
        <TabsContent value="contribution" className="flex-1 overflow-hidden m-0 p-0">
          <ContributionTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default memo(MarketOverviewWidget);
