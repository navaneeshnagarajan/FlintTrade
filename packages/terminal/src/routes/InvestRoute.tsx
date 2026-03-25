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

import { useState, useEffect, type ReactNode } from "react";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillStore } from "@/stores/skillStore";
import { SpotlightTour } from "@/components/help/SpotlightTour";
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
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import TabTransition from "@/components/motion/TabTransition";
import { cn } from "@/lib/utils";
import { InvestProvider, useInvest } from "./invest/InvestContext";
import {
  DashboardTab,
  HoldingsTab,
  NetWorthTab,
  SipTab,
  SectorTab,
  EtfTab,
  StocksTab,
  IpoTab,
} from "./invest/tabs";

// ─── Tab registry ─────────────────────────────────────────────────────────────

type TabId =
  | "dashboard"
  | "holdings"
  | "sip"
  | "networth"
  | "sector"
  | "etf"
  | "stocks"
  | "ipo";

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
  { id: "sector", label: "Sector", icon: RotateCcw },
  { id: "etf", label: "ETFs", icon: Filter },
  { id: "stocks", label: "Stocks", icon: Search },
  { id: "ipo", label: "IPO", icon: Ticket },
];

/** Holdings tab owns its scroll — all others use the shared ScrollArea. */
const FULL_HEIGHT_TABS: TabId[] = ["holdings"];

// ─── Tab content map ──────────────────────────────────────────────────────────

const TAB_CONTENT: Record<TabId, ReactNode> = {
  dashboard: <DashboardTab />,
  holdings: <HoldingsTab />,
  sip: <SipTab />,
  networth: <NetWorthTab />,
  sector: <SectorTab />,
  etf: <EtfTab />,
  stocks: <StocksTab />,
  ipo: <IpoTab />,
};

// ─── Inner shell (needs InvestProvider in scope) ──────────────────────────────

function InvestShell() {
  useEffect(() => {
    useSkillStore.getState().trackAction("invest", "daysActive");
  }, []);

  const [activeTab, setActiveTab] = useState<TabId>("dashboard");
  const level = useSkillLevel("invest");
  const { holdings, isLoading } = useInvest();

  // Density adaptation: fewer tabs for lower skill levels
  const visibleTabIds: TabId[] = (() => {
    if (level === "beginner") return ["dashboard", "holdings", "sip", "networth"];
    if (level === "intermediate") return ["dashboard", "holdings", "sip", "networth", "sector"];
    return ["dashboard", "holdings", "sip", "networth", "sector", "etf", "stocks", "ipo"];
  })();

  const visibleTabs = TABS.filter((t) => visibleTabIds.includes(t.id));

  return (
    <div className="h-full flex flex-col overflow-hidden">
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
          <nav
            aria-label="Section navigation"
            className="flex items-end gap-1 px-6 overflow-x-auto scrollbar-none"
          >
            {visibleTabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  aria-current={isActive ? "true" : undefined}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-2 text-xs font-sans font-medium transition-colors border-b-2 whitespace-nowrap shrink-0",
                    isActive
                      ? "text-accent border-accent"
                      : "text-text-secondary hover:text-text-primary border-transparent hover:border-border-default",
                  )}
                >
                  <Icon className="w-3.5 h-3.5 shrink-0" />
                  {tab.label}
                </button>
              );
            })}
          </nav>
      </div>

      {/* Content */}
      {FULL_HEIGHT_TABS.includes(activeTab) ? (
        <TabTransition tabKey={activeTab} className="flex-1 flex flex-col overflow-hidden">
          {TAB_CONTENT[activeTab]}
        </TabTransition>
      ) : (
        <ScrollArea className="flex-1">
          <TabTransition tabKey={activeTab}>
            <div className="p-6 max-w-5xl mx-auto">{TAB_CONTENT[activeTab]}</div>
          </TabTransition>
        </ScrollArea>
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
