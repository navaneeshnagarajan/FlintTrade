/**
 * InvestRoute.tsx — thin shell (~100 lines)
 *
 * Responsibilities:
 *   1. Wrap the route in InvestProvider (single data-fetch boundary)
 *   2. Manage active tab state
 *   3. Apply skill-level gating (density adaptation — hide, never restructure)
 *   4. Render the tab bar + active tab content
 *   5. Mount the guided tour for beginners
 *
 * All tab content lives in routes/invest/tabs/*.tsx
 * All data fetching lives in routes/invest/InvestContext.tsx
 */

import { useState, useEffect, lazy, Suspense } from "react";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillStore } from "@/stores/skillStore";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { RouteBanner } from "@/components/help/RouteBanner";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
import {
  TrendingUp,
  BarChart3,
  Calculator,
  Wallet,
  RotateCcw,
  Filter,
  Search,
  Ticket,
  RefreshCw,
  LayoutDashboard,
  Users,
  Receipt,
  Layers,
  Sparkles,
  Activity,
  Target,
  IndianRupee,
  ScanLine,
  GitBranch,
  Crosshair,
  Grid2X2,
  PieChart,
  Eye,
  EyeOff,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ExampleLabel } from "@/components/data/ExampleLabel";
import {
  Page,
  PageBody,
  PageHeader,
  PageTabs,
  pageTabId,
  pageTabPanelId,
  type PageTab,
} from "@/components/layout/Page";
import { useValueVisibilityStore } from "@/stores/valueVisibilityStore";
import { useModeStore } from "@/stores/modeStore";
import TabTransition from "@/components/motion/TabTransition";
import { InvestProvider, useInvest } from "./invest/InvestContext";
import {
  INVEST_GROUPS,
  groupForTab,
  resolveInvestLocation,
  visibleInvestTabs,
  type InvestTabId,
} from "./invest/investTabs";

// Lazy-load each tab individually — only the active tab is loaded.
// Previously all 14 tabs were eagerly imported via barrel export (~142KB).
const DashboardTab = lazy(() => import("./invest/tabs/DashboardTab").then(m => ({ default: m.DashboardTab })));
const HoldingsTab = lazy(() => import("./invest/tabs/HoldingsTab").then(m => ({ default: m.HoldingsTab })));
const NetWorthTab = lazy(() => import("./invest/tabs/NetWorthTab").then(m => ({ default: m.NetWorthTab })));
const SipTab = lazy(() => import("./invest/tabs/SipTab").then(m => ({ default: m.SipTab })));
const SectorTab = lazy(() => import("./invest/tabs/SectorTab").then(m => ({ default: m.SectorTab })));
const EtfTab = lazy(() => import("./invest/tabs/EtfTab").then(m => ({ default: m.EtfTab })));
const StocksTab = lazy(() => import("./invest/tabs/StocksTab").then(m => ({ default: m.StocksTab })));
const IpoTab = lazy(() => import("./invest/tabs/IpoTab").then(m => ({ default: m.IpoTab })));
const SocialTab = lazy(() => import("./invest/tabs/SocialTab").then(m => ({ default: m.SocialTab })));
const TaxTab = lazy(() => import("./invest/tabs/TaxTab").then(m => ({ default: m.TaxTab })));
const OverlapTab = lazy(() => import("./invest/tabs/OverlapTab").then(m => ({ default: m.OverlapTab })));
const MfOptimizerTab = lazy(() => import("./invest/tabs/MfOptimizerTab").then(m => ({ default: m.MfOptimizerTab })));
const BenchmarkTab = lazy(() => import("./invest/tabs/BenchmarkTab").then(m => ({ default: m.BenchmarkTab })));
const BasketTab = lazy(() => import("./invest/tabs/BasketTab").then(m => ({ default: m.BasketTab })));
const GoalTab = lazy(() => import("./invest/tabs/GoalTab").then(m => ({ default: m.GoalTab })));
const MutualFundTab = lazy(() => import("./invest/tabs/MutualFundTab").then(m => ({ default: m.MutualFundTab })));
const EtfScreenerTab = lazy(() => import("./invest/tabs/EtfScreenerTab").then(m => ({ default: m.EtfScreenerTab })));
const ShareholdingTab = lazy(() => import("./invest/tabs/ShareholdingTab").then(m => ({ default: m.ShareholdingTab })));
const SectorRotationTab = lazy(() => import("./invest/tabs/SectorRotationTab").then(m => ({ default: m.SectorRotationTab })));
const RiskReturnTab = lazy(() => import("./invest/tabs/RiskReturnTab").then(m => ({ default: m.RiskReturnTab })));
const CorrelationTab = lazy(() => import("./invest/tabs/CorrelationTab").then(m => ({ default: m.CorrelationTab })));

// ─── Tab registry ─────────────────────────────────────────────────────────────

type TabId = InvestTabId;

interface TabDef {
  id: TabId;
  label: string;
  icon: typeof TrendingUp;
}

const TABS: TabDef[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "holdings", label: "Holdings", icon: BarChart3 },
  { id: "sip", label: "SIPs", icon: Calculator },
  { id: "networth", label: "Net Worth", icon: Wallet },
  { id: "social", label: "Social", icon: Users },
  { id: "sector", label: "Sector", icon: RotateCcw },
  { id: "overlap", label: "Overlap", icon: Layers },
  { id: "etf", label: "ETFs", icon: Filter },
  { id: "stocks", label: "Stocks", icon: Search },
  { id: "ipo", label: "IPO", icon: Ticket },
  { id: "tax", label: "Tax", icon: Receipt },
  { id: "mf-optimizer", label: "MF Optimizer", icon: Sparkles },
  { id: "mutual-funds", label: "Mutual Funds", icon: IndianRupee },
  { id: "benchmark", label: "Benchmark", icon: Activity },
  { id: "basket", label: "Baskets", icon: Layers },
  { id: "goals", label: "Goals", icon: Target },
  { id: "etf-screener", label: "ETF Screener", icon: ScanLine },
  { id: "shareholding", label: "Shareholding", icon: PieChart },
  { id: "sector-rotation", label: "Sector Rotation", icon: GitBranch },
  { id: "risk-return", label: "Risk-Return", icon: Crosshair },
  { id: "correlation", label: "Correlation", icon: Grid2X2 },
];

/** Holdings tab owns its scroll — all others use the shared PageBody. */
const FULL_HEIGHT_TABS: TabId[] = ["holdings"];

type GroupId = (typeof INVEST_GROUPS)[number]["id"];

const GROUP_ICONS: Record<GroupId, typeof TrendingUp> = {
  overview: LayoutDashboard,
  holdings: BarChart3,
  analyse: PieChart,
  discover: Search,
  tax: Receipt,
};

/**
 * Resolve an Invest URL hash to a leaf tab.
 *
 * Deep links such as `/invest#holdings` and group links such as `/invest#overview`
 * select the matching group and sub-view on the first paint.
 */
function tabFromHash(): TabId {
  return resolveInvestLocation(window.location.hash).tabId;
}

// ─── Active tab renderer ──────────────────────────────────────────────────────

/**
 * Renders only the currently active tab's component, avoiding the cost of
 * instantiating all 14 tab components at module-load time.
 */
function TabFallback() {
  return (
    <div role="status" className="flex items-center justify-center py-12">
      <div className="w-5 h-5 border-2 border-accent/30 border-t-accent rounded-full animate-spin" aria-hidden="true" />
      <span className="sr-only">Loading...</span>
    </div>
  );
}

function ActiveTabContent({ tabId }: { tabId: TabId }) {
  const content = (() => {
    switch (tabId) {
      case "dashboard":    return <DashboardTab />;
      case "holdings":     return <HoldingsTab />;
      case "sip":          return <SipTab />;
      case "networth":     return <NetWorthTab />;
      case "social":       return <SocialTab />;
      case "sector":       return <SectorTab />;
      case "overlap":      return <OverlapTab />;
      case "etf":          return <EtfTab />;
      case "stocks":       return <StocksTab />;
      case "ipo":          return <IpoTab />;
      case "tax":          return <TaxTab />;
      case "mf-optimizer":  return <MfOptimizerTab />;
      case "mutual-funds":  return <MutualFundTab />;
      case "benchmark":     return <BenchmarkTab />;
      case "basket":       return <BasketTab />;
      case "goals":          return <GoalTab />;
      case "etf-screener":   return <EtfScreenerTab />;
      case "shareholding":   return <ShareholdingTab />;
      case "sector-rotation": return <SectorRotationTab />;
      case "risk-return":    return <RiskReturnTab />;
      case "correlation":    return <CorrelationTab />;
      default:               return null;
    }
  })();

  return <Suspense fallback={<TabFallback />}>{content}</Suspense>;
}

/** Not shown in Practice, where Invest reads the Practice account. */
function InvestBrokerHint({ className }: { className?: string }) {
  return (
    <RouteBanner
      hintId="invest-broker-connect"
      text="Connect a broker in Settings → Brokers to see your real holdings, SIPs, and portfolio value here."
      className={className}
    />
  );
}

// ─── Inner shell (needs InvestProvider in scope) ──────────────────────────────

function InvestShell() {
  useEffect(() => {
    useSkillStore.getState().trackAction("invest", "daysActive");
  }, []);

  const [activeTab, setActiveTab] = useState<TabId>(tabFromHash);
  const level = useSkillLevel("invest");
  const { holdings, isLoading, isSampleData } = useInvest();
  const isPractice = useModeStore((s) => s.mode === "practice");
  const valuesHidden = useValueVisibilityStore((s) => s.hidden);
  const toggleValues = useValueVisibilityStore((s) => s.toggle);

  useEffect(() => {
    const syncTabFromHash = () => setActiveTab(tabFromHash());
    window.addEventListener("hashchange", syncTabFromHash);
    return () => window.removeEventListener("hashchange", syncTabFromHash);
  }, []);

  useEffect(() => {
    const nextHash = `#${activeTab}`;
    if (window.location.hash !== nextHash) {
      window.history.replaceState(null, "", nextHash);
    }
  }, [activeTab]);

  const allowedTabIds = visibleInvestTabs(level, activeTab);
  const groups = INVEST_GROUPS
    .map((group) => ({
      ...group,
      tabs: group.tabs.filter((id) => allowedTabIds.includes(id)),
    }))
    .filter((group) => group.tabs.length > 0);
  const activeGroup = groups.find((group) => group.tabs.includes(activeTab)) ?? groups[0];
  const subTabs = (activeGroup?.tabs ?? [])
    .map((id) => TABS.find((tab) => tab.id === id))
    .filter((tab): tab is TabDef => tab != null);

  const selectGroup = (groupId: GroupId) => {
    const group = groups.find((candidate) => candidate.id === groupId);
    if (!group || group.tabs.includes(activeTab)) return;
    setActiveTab(group.tabs[0]);
  };

  const groupTabs: PageTab<GroupId>[] = groups.map((group) => ({
    id: group.id,
    label: group.label,
    icon: GROUP_ICONS[group.id],
  }));
  const activeGroupId = activeGroup?.id ?? groupForTab(activeTab).id;
  const panelId = pageTabPanelId("invest", activeTab);
  const panelLabelledBy = subTabs.length > 1
    ? pageTabId("invest", activeTab)
    : pageTabId("invest-group", activeGroupId);

  return (
    <Page>
      <PageHeader
        title="Invest"
        tourTarget="holdings"
        description={
          level === "beginner"
            ? "Track your holdings and build your wealth over time."
            : "Portfolio, holdings, net worth and long-term investing tools."
        }
        meta={
          isLoading ? (
            <RefreshCw className="size-3.5 animate-spin text-text-muted" aria-label="Loading holdings" />
          ) : (
            <>
              <Badge variant="outline" className="h-5 border-border-default text-xs text-text-secondary">
                {holdings.length} holdings
              </Badge>
              {isSampleData && <ExampleLabel testId="invest-header-example" />}
            </>
          )
        }
        actions={
          <div data-tour-target="networth">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={toggleValues}
              aria-pressed={valuesHidden}
              aria-label={valuesHidden ? "Show values" : "Hide values"}
              title={valuesHidden ? "Show values" : "Hide values"}
            >
              {valuesHidden ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
              <span className="hidden sm:inline">{valuesHidden ? "Show values" : "Hide values"}</span>
            </Button>
          </div>
        }
      >
        <PageTabs<GroupId>
          tabs={groupTabs}
          value={activeGroupId}
          onChange={selectGroup}
          label="Invest sections"
          idPrefix="invest-group"
          panelId={panelId}
        />
        {subTabs.length > 1 && (
          <div className="-mx-[var(--ft-page-gutter)] border-t border-border-default px-[var(--ft-page-gutter)] py-2">
            <PageTabs<TabId>
              tabs={subTabs}
              value={activeTab}
              onChange={setActiveTab}
              label={`${activeGroup?.label ?? "Invest"} views`}
              idPrefix="invest"
              variant="secondary"
            />
          </div>
        )}
      </PageHeader>

      {/* Content */}
      {FULL_HEIGHT_TABS.includes(activeTab) ? (
        <div
          role="tabpanel"
          id={panelId}
          aria-labelledby={panelLabelledBy}
          className="flex-1 flex flex-col overflow-hidden"
        >
          {!isPractice && <InvestBrokerHint className="mx-[var(--ft-page-gutter)] mt-5 shrink-0" />}
          <TabTransition tabKey={activeTab} className="flex-1 flex flex-col overflow-hidden">
            <ActiveTabContent tabId={activeTab} />
          </TabTransition>
        </div>
      ) : (
        <PageBody
          role="tabpanel"
          id={panelId}
          aria-labelledby={panelLabelledBy}
        >
          {!isPractice && <InvestBrokerHint className="mb-5" />}
          <TabTransition tabKey={activeTab}>
            <ActiveTabContent tabId={activeTab} />
          </TabTransition>
        </PageBody>
      )}

      {/* Guided tour — beginner only, first visit */}
      {level === "beginner" && (
        <SpotlightTour
          tourId="invest-beginner"
          steps={TOUR_DEFINITIONS["invest-beginner"] ?? []}
        />
      )}
    </Page>
  );
}

// ─── Route export ─────────────────────────────────────────────────────────────

export default function InvestRoute() {
  return (
    <InvestProvider>
      <InvestShell />
    </InvestProvider>
  );
}
