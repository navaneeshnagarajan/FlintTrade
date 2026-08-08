import type { ComponentType } from "react";
import { Activity, Bot, Briefcase, ChartNoAxesCombined, Globe2, ListChecks, Newspaper, PieChart, PlusCircle, Radar, TrendingUp, Wallet } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { AIPulseCard } from "@/routes/home/AIPulseCard";
import { BreadthCard } from "@/routes/home/BreadthCard";
import { GlobalCard } from "@/routes/home/GlobalCard";
import { MiniChartCard } from "@/routes/home/MiniChartCard";
import { NewsCard } from "@/routes/home/NewsCard";
import { OrdersCard } from "@/routes/home/OrdersCard";
import { PortfolioCard } from "@/routes/home/PortfolioCard";
import { PositionsCard } from "@/routes/home/PositionsCard";
import { SIPCard } from "@/routes/home/SIPCard";
import { SectorCard } from "@/routes/home/SectorCard";
import { WatchlistCard } from "@/routes/home/WatchlistCard";
import { WelcomeCard } from "@/routes/home/WelcomeCard";

import type { WidgetSurface, WidgetAvailability } from "@/types/widgets";

export interface HomeWidgetDefinition {
  componentId: string;
  name: string;
  description: string;
  icon: LucideIcon;
  surface: WidgetSurface;
  availability: WidgetAvailability;
  tradePairId?: string;
  domain?: "market" | "account" | "orders" | "ai" | "invest" | "utility";
}

export const HOME_WIDGET_COMPONENTS: Record<string, ComponentType> = {
  WelcomeCard,
  AIPulseCard,
  PositionsCard,
  MiniChartCard,
  PortfolioCard,
  WatchlistCard,
  NewsCard,
  BreadthCard,
  SectorCard,
  SIPCard,
  GlobalCard,
  OrdersCard,
};

export const HOME_WIDGET_CATALOG: HomeWidgetDefinition[] = [
  {
    componentId: "WelcomeCard",
    name: "Welcome",
    description: "Daily account pulse, P&L, open position count, and regime.",
    icon: PlusCircle,
    surface: "home",
    availability: "live-or-sample",
    domain: "market",
  },
  {
    componentId: "AIPulseCard",
    name: "AI Pulse",
    description: "Market readout and shortcut into the AI chat surface.",
    icon: Bot,
    surface: "home",
    availability: "sample-only",
    domain: "ai",
  },
  {
    componentId: "PositionsCard",
    name: "Open Positions",
    description: "Live or sample positions with per-symbol P&L.",
    icon: Briefcase,
    surface: "shared",
    availability: "live-or-sample",
    tradePairId: "positions",
    domain: "account",
  },
  {
    componentId: "MiniChartCard",
    name: "NIFTY Chart",
    description: "Compact NIFTY sparkline with quick range controls.",
    icon: ChartNoAxesCombined,
    surface: "home",
    availability: "live-or-sample",
    domain: "market",
  },
  {
    componentId: "PortfolioCard",
    name: "Portfolio",
    description: "Net worth and allocation mix across major buckets.",
    icon: PieChart,
    surface: "shared",
    availability: "live-or-sample",
    tradePairId: "holdings",
    domain: "account",
  },
  {
    componentId: "WatchlistCard",
    name: "Watchlist",
    description: "Tracked indices and instruments for quick scanning.",
    icon: Activity,
    surface: "shared",
    availability: "live-or-sample",
    tradePairId: "watchlist",
    domain: "market",
  },
  {
    componentId: "NewsCard",
    name: "Top Stories",
    description: "Market headlines and source timestamps.",
    icon: Newspaper,
    surface: "shared",
    availability: "sample-only",
    tradePairId: "news",
    domain: "market",
  },
  {
    componentId: "BreadthCard",
    name: "Market Breadth",
    description: "Advance, decline, and unchanged market participation.",
    icon: Radar,
    surface: "shared",
    availability: "live-or-sample",
    tradePairId: "marketoverview",
    domain: "market",
  },
  {
    componentId: "SectorCard",
    name: "Sector Performance",
    description: "Sector returns for fast strength and weakness checks.",
    icon: TrendingUp,
    surface: "home",
    availability: "sample-only",
    domain: "market",
  },
  {
    componentId: "SIPCard",
    name: "Active SIPs",
    description: "Upcoming SIP dates and monthly investment amounts.",
    icon: Wallet,
    surface: "home",
    availability: "sample-only",
    domain: "invest",
  },
  {
    componentId: "GlobalCard",
    name: "Global Indices",
    description: "Global market context across major indices.",
    icon: Globe2,
    surface: "home",
    availability: "sample-only",
    domain: "market",
  },
  {
    componentId: "OrdersCard",
    name: "Recent Orders",
    description: "Latest order activity and execution status.",
    icon: ListChecks,
    surface: "shared",
    availability: "live-or-sample",
    tradePairId: "orders",
    domain: "orders",
  },
];
