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

import { useState, useEffect, useCallback, useRef, lazy, Suspense } from "react";
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
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import TabTransition from "@/components/motion/TabTransition";
import { cn } from "@/lib/utils";
import { InvestProvider, useInvest } from "./invest/InvestContext";

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
const SectorRotationTab = lazy(() => import("./invest/tabs/SectorRotationTab").then(m => ({ default: m.SectorRotationTab })));
const RiskReturnTab = lazy(() => import("./invest/tabs/RiskReturnTab").then(m => ({ default: m.RiskReturnTab })));
const CorrelationTab = lazy(() => import("./invest/tabs/CorrelationTab").then(m => ({ default: m.CorrelationTab })));

// ─── Tab registry ─────────────────────────────────────────────────────────────

type TabId =
  | "dashboard"
  | "holdings"
  | "sip"
  | "networth"
  | "social"
  | "sector"
  | "overlap"
  | "etf"
  | "stocks"
  | "ipo"
  | "tax"
  | "mf-optimizer"
  | "mutual-funds"
  | "benchmark"
  | "basket"
  | "goals"
  | "etf-screener"
  | "sector-rotation"
  | "risk-return"
  | "correlation";

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
  { id: "sector-rotation", label: "Sector Rotation", icon: GitBranch },
  { id: "risk-return", label: "Risk-Return", icon: Crosshair },
  { id: "correlation", label: "Correlation", icon: Grid2X2 },
];

/** Holdings tab owns its scroll — all others use the shared ScrollArea. */
const FULL_HEIGHT_TABS: TabId[] = ["holdings"];

// ─── Active tab renderer ──────────────────────────────────────────────────────

/**
 * Renders only the currently active tab's component, avoiding the cost of
 * instantiating all 14 tab components at module-load time.
 */
function TabFallback() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="w-5 h-5 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
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
      case "sector-rotation": return <SectorRotationTab />;
      case "risk-return":    return <RiskReturnTab />;
      case "correlation":    return <CorrelationTab />;
      default:               return null;
    }
  })();

  return <Suspense fallback={<TabFallback />}>{content}</Suspense>;
}

// ─── Inner shell (needs InvestProvider in scope) ──────────────────────────────

function InvestShell() {
  useEffect(() => {
    useSkillStore.getState().trackAction("invest", "daysActive");
  }, []);

  const [activeTab, setActiveTab] = useState<TabId>("dashboard");
  const level = useSkillLevel("invest");
  const { holdings, isLoading } = useInvest();
  const tablistRef = useRef<HTMLDivElement>(null);

  // Density adaptation: fewer tabs for lower skill levels
  const visibleTabIds: TabId[] = (() => {
    if (level === "beginner") return ["dashboard", "holdings", "sip", "networth", "goals", "mf-optimizer", "mutual-funds"];
    if (level === "intermediate") return ["dashboard", "holdings", "sip", "networth", "social", "sector", "overlap", "goals", "tax", "mf-optimizer", "mutual-funds", "benchmark", "basket", "etf-screener", "sector-rotation"];
    return ["dashboard", "holdings", "sip", "networth", "social", "sector", "overlap", "etf", "stocks", "ipo", "tax", "mf-optimizer", "mutual-funds", "benchmark", "basket", "goals", "etf-screener", "sector-rotation", "risk-return", "correlation"];
  })();

  const visibleTabs = TABS.filter((t) => visibleTabIds.includes(t.id));

  // Roving tabindex: arrow key navigation on the horizontal tablist
  const handleTablistKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const tabs = tablistRef.current?.querySelectorAll<HTMLButtonElement>("[role='tab']");
      if (!tabs || tabs.length === 0) return;
      const idx = Array.from(tabs).indexOf(document.activeElement as HTMLButtonElement);
      const next =
        e.key === "ArrowRight"
          ? (idx + 1) % tabs.length
          : (idx - 1 + tabs.length) % tabs.length;
      const nextTab = tabs[next];
      nextTab?.focus();
      // Activate the focused tab (follows ARIA Tabs pattern)
      const tabId = visibleTabs[next]?.id;
      if (tabId) setActiveTab(tabId);
    },
    [visibleTabs],
  );

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Route-level hint banner — dismissible, respects helpPrefs.inlineHints */}
      <RouteBanner
        hintId="invest-broker-connect"
        text="Connect a broker in Settings → API to see your real holdings, SIPs, and portfolio value here."
      />
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card/80 backdrop-blur-sm shrink-0">
          {/* Title row */}
          <div className="flex items-center justify-between px-6 pt-4 pb-3">
            <div className="flex items-center gap-3" data-tour-target="holdings">
              <TrendingUp className="w-5 h-5 text-profit" />
              <div>
                <h1 className="font-heading font-bold text-base text-text-primary">
                  {level === "beginner" ? "Your Journey" : "Investor Dashboard"}
                </h1>
                <p className="text-xxs text-text-muted">
                  {level === "beginner"
                    ? "Track your holdings and build your wealth over time"
                    : "Portfolio, holdings, net worth, and investment tools"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2" data-tour-target="networth">
              {isLoading && <RefreshCw className="size-3 text-text-muted animate-spin" />}
              {!isLoading && (
                <Badge
                  variant="outline"
                  className="text-xxs h-5 border-border-default text-text-muted"
                >
                  {holdings.length} holdings
                </Badge>
              )}
            </div>
          </div>

          {/* Horizontal tab bar — filtered by skill level */}
          <div
            ref={tablistRef}
            role="tablist"
            aria-label="Invest sections"
            className="flex items-end gap-1 px-6 overflow-x-auto scrollbar-none"
            onKeyDown={handleTablistKeyDown}
          >
            {visibleTabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  role="tab"
                  aria-selected={isActive}
                  aria-controls={`invest-tabpanel-${tab.id}`}
                  id={`invest-tab-${tab.id}`}
                  tabIndex={isActive ? 0 : -1}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-2 text-xs font-sans font-medium transition-colors border-b-2 whitespace-nowrap shrink-0",
                    isActive
                      ? "text-accent border-accent"
                      : "text-text-secondary hover:text-text-primary border-transparent hover:border-border-default",
                  )}
                >
                  <Icon className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                  {tab.label}
                </button>
              );
            })}
          </div>
      </div>

      {/* Content */}
      {FULL_HEIGHT_TABS.includes(activeTab) ? (
        <div
          role="tabpanel"
          id={`invest-tabpanel-${activeTab}`}
          aria-labelledby={`invest-tab-${activeTab}`}
          className="flex-1 flex flex-col overflow-hidden"
        >
          <TabTransition tabKey={activeTab} className="flex-1 flex flex-col overflow-hidden">
            <ActiveTabContent tabId={activeTab} />
          </TabTransition>
        </div>
      ) : (
        <div
          role="tabpanel"
          id={`invest-tabpanel-${activeTab}`}
          aria-labelledby={`invest-tab-${activeTab}`}
          className="flex-1"
        >
          <ScrollArea className="h-full">
            <TabTransition tabKey={activeTab}>
              <div className="p-6 max-w-5xl mx-auto">
                <ActiveTabContent tabId={activeTab} />
              </div>
            </TabTransition>
          </ScrollArea>
        </div>
      )}

      {/* Guided tour — beginner only, first visit */}
      {level === "beginner" && (
        <SpotlightTour
          tourId="invest-beginner"
          steps={TOUR_DEFINITIONS["invest-beginner"] ?? []}
        />
      )}
    </div>
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
