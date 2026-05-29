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

export interface HomeWidgetDefinition {
  componentId: string;
  name: string;
  description: string;
  icon: LucideIcon;
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
  },
  {
    componentId: "AIPulseCard",
    name: "AI Pulse",
    description: "Market readout and shortcut into the AI chat surface.",
    icon: Bot,
  },
  {
    componentId: "PositionsCard",
    name: "Open Positions",
    description: "Live or sample positions with per-symbol P&L.",
    icon: Briefcase,
  },
  {
    componentId: "MiniChartCard",
    name: "NIFTY Chart",
    description: "Compact NIFTY sparkline with quick range controls.",
    icon: ChartNoAxesCombined,
  },
  {
    componentId: "PortfolioCard",
    name: "Portfolio",
    description: "Net worth and allocation mix across major buckets.",
    icon: PieChart,
  },
  {
    componentId: "WatchlistCard",
    name: "Watchlist",
    description: "Tracked indices and instruments for quick scanning.",
    icon: Activity,
  },
  {
    componentId: "NewsCard",
    name: "Top Stories",
    description: "Market headlines and source timestamps.",
    icon: Newspaper,
  },
  {
    componentId: "BreadthCard",
    name: "Market Breadth",
    description: "Advance, decline, and unchanged market participation.",
    icon: Radar,
  },
  {
    componentId: "SectorCard",
    name: "Sector Performance",
    description: "Sector returns for fast strength and weakness checks.",
    icon: TrendingUp,
  },
  {
    componentId: "SIPCard",
    name: "Active SIPs",
    description: "Upcoming SIP dates and monthly investment amounts.",
    icon: Wallet,
  },
  {
    componentId: "GlobalCard",
    name: "Global Indices",
    description: "Global market context across major indices.",
    icon: Globe2,
  },
  {
    componentId: "OrdersCard",
    name: "Recent Orders",
    description: "Latest order activity and execution status.",
    icon: ListChecks,
  },
];
