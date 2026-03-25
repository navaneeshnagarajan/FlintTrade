import React, { useState } from "react";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
import { motion, AnimatePresence } from "framer-motion";
import { CinematicLayout } from "@/components/layout/CinematicLayout";
import { BlurFade } from "@/components/magicui/blur-fade";
import { TextGenerateEffect } from "@/components/aceternity/text-generate-effect";
import {
  BookOpen,
  GraduationCap,
  BarChart3,
  PlayCircle,
  Search,
  ChevronRight,
  ExternalLink,
  TrendingUp,
  PanelLeftClose,
  PanelLeftOpen,
  Clock,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { GlassCard } from "@/components/ui/GlassCard";
import TabTransition from "@/components/motion/TabTransition";
import { StaggeredList } from "@/components/motion/StaggeredList";
import { motionConfig } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TabId = "basics" | "glossary" | "strategies" | "paper" | "videos";

interface TabDef {
  id: TabId;
  label: string;
  icon: typeof BookOpen;
  /** Progress 0–100 shown as a bar under the label */
  progress: number;
}

interface GlossaryEntry {
  term: string;
  definition: string;
}

interface StrategyCard {
  name: string;
  category: string;
  difficulty: "Beginner" | "Intermediate" | "Advanced";
  description: string;
  /** Extra detail revealed on click */
  detail: string;
}

interface VideoCard {
  title: string;
  channel: string;
  topic: string;
  url: string;
}

interface BasicsSection {
  title: string;
  content: string;
  readingTime: number; // minutes
  difficulty: "Beginner" | "Intermediate" | "Advanced";
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TABS: TabDef[] = [
  { id: "basics",     label: "Market Basics",    icon: BookOpen,     progress: 33 },
  { id: "glossary",   label: "Glossary",          icon: GraduationCap, progress: 0  },
  { id: "strategies", label: "Strategy Library",  icon: BarChart3,    progress: 16 },
  { id: "paper",      label: "Paper Trading",     icon: TrendingUp,   progress: 0  },
  { id: "videos",     label: "Video Hub",         icon: PlayCircle,   progress: 0  },
];

const BASICS_SECTIONS: BasicsSection[] = [
  {
    title: "What are Stocks?",
    readingTime: 2,
    difficulty: "Beginner",
    content:
      "Stocks represent ownership in a company. When you buy a stock, you become a shareholder. Stock prices change based on supply and demand — if more people want to buy than sell, the price goes up. In India, stocks trade on NSE (National Stock Exchange) and BSE (Bombay Stock Exchange).",
  },
  {
    title: "Understanding F&O",
    readingTime: 3,
    difficulty: "Intermediate",
    content:
      "Futures & Options (F&O) are derivative instruments. A Future is an agreement to buy/sell an asset at a predetermined price on a specific date. An Option gives you the right (not obligation) to buy (Call) or sell (Put) at a specific price (Strike). F&O requires less capital than stocks but carries higher risk.",
  },
  {
    title: "Mutual Funds & SIPs",
    readingTime: 2,
    difficulty: "Beginner",
    content:
      "A Mutual Fund pools money from many investors to invest in stocks, bonds, or other assets. A SIP (Systematic Investment Plan) lets you invest a fixed amount regularly (monthly). SIPs average out the purchase price over time (rupee cost averaging), reducing risk for long-term investors.",
  },
  {
    title: "Index Trading",
    readingTime: 2,
    difficulty: "Beginner",
    content:
      "An index tracks the performance of a group of stocks. NIFTY 50 tracks the top 50 companies on NSE. SENSEX tracks the top 30 on BSE. BANKNIFTY tracks banking stocks. Index trading through F&O is popular because it provides market-level exposure without picking individual stocks.",
  },
  {
    title: "Understanding Risk",
    readingTime: 3,
    difficulty: "Intermediate",
    content:
      "Never invest money you cannot afford to lose. Use stop-losses to limit downside. Diversify across stocks and sectors. For F&O, understand margin requirements — you can lose more than your invested amount. Start with paper trading before using real money.",
  },
  {
    title: "SEBI Regulations",
    readingTime: 2,
    difficulty: "Beginner",
    content:
      "SEBI (Securities and Exchange Board of India) regulates Indian markets. Key rules: maximum 10 orders per second for algo trading, mandatory 5-year audit trail, static IP required for API trading. FlintTrade is designed to comply with all SEBI regulations automatically.",
  },
];

const GLOSSARY: GlossaryEntry[] = [
  { term: "ATM",        definition: "At The Money — option strike closest to current market price" },
  { term: "Bid/Ask",    definition: "Bid is the highest buy price, Ask is the lowest sell price" },
  { term: "Call Option",definition: "Right to BUY an asset at a specific price (bullish)" },
  { term: "Delta",      definition: "Rate of change of option price per ₹1 move in underlying" },
  { term: "EMA",        definition: "Exponential Moving Average — weighted average giving more importance to recent prices" },
  { term: "F&O",        definition: "Futures and Options — derivative instruments" },
  { term: "Gamma",      definition: "Rate of change of Delta — measures acceleration of price change" },
  { term: "Hedge",      definition: "A position taken to offset potential losses in another position" },
  { term: "IV",         definition: "Implied Volatility — market's expectation of future price movement" },
  { term: "Lot Size",   definition: "Minimum quantity for F&O trading. NIFTY=25, BANKNIFTY=15" },
  { term: "Margin",     definition: "Deposit required to open F&O positions. Can be SPAN + Exposure." },
  { term: "MTM",        definition: "Mark To Market — daily P&L calculation based on closing price" },
  { term: "NRML",       definition: "Normal position — can be carried overnight, higher margin" },
  { term: "OI",         definition: "Open Interest — total outstanding derivative contracts" },
  { term: "PCR",        definition: "Put-Call Ratio — Put OI / Call OI. >1 = bearish, <1 = bullish" },
  { term: "Put Option", definition: "Right to SELL an asset at a specific price (bearish)" },
  { term: "RSI",        definition: "Relative Strength Index — momentum oscillator (0-100, >70 overbought, <30 oversold)" },
  { term: "SL",         definition: "Stop Loss — automatic exit to limit losses" },
  { term: "Straddle",   definition: "Buying both Call and Put at same strike — profits from big moves in either direction" },
  { term: "Theta",      definition: "Time decay — how much option value decreases per day" },
  { term: "Underlying", definition: "The asset an F&O contract derives its value from (e.g., NIFTY index)" },
  { term: "Vega",       definition: "Sensitivity of option price to changes in implied volatility" },
  { term: "VIX",        definition: "India Volatility Index — measures expected market volatility over 30 days" },
  { term: "VWAP",       definition: "Volume Weighted Average Price — average price weighted by trading volume" },
];

const STRATEGIES: StrategyCard[] = [
  {
    name: "EMA Crossover",    category: "Trend",          difficulty: "Beginner",
    description: "Buy when fast EMA crosses above slow EMA, sell on reverse",
    detail: "Commonly used pairs: 9/21 EMA for intraday, 50/200 EMA for positional. Avoid during sideways market — generates false signals. Works best on 15m+ timeframes for F&O.",
  },
  {
    name: "RSI Reversal",     category: "Momentum",       difficulty: "Beginner",
    description: "Buy below RSI 30, sell above RSI 70",
    detail: "Use RSI(14) as default. Combine with price support/resistance for higher accuracy. In strong trends, RSI can stay overbought/oversold for extended periods — use with trend filter.",
  },
  {
    name: "Supertrend",       category: "Trend",          difficulty: "Beginner",
    description: "Follow ATR-based trend indicator — green = long, red = short",
    detail: "Default parameters: ATR(10), multiplier 3. Flip position on color change. Add volume filter to reduce whipsaws. Best on daily chart for swing trades.",
  },
  {
    name: "Bollinger Squeeze",category: "Volatility",     difficulty: "Intermediate",
    description: "Enter breakout when bands contract then expand",
    detail: "Look for BB width at multi-month lows (squeeze). Breakout direction confirms trade. Use ATR to set stop-loss. Combine with RSI or MACD for directional bias before entry.",
  },
  {
    name: "MACD Signal",      category: "Momentum",       difficulty: "Intermediate",
    description: "Trade MACD line crossing signal line",
    detail: "Settings: 12/26/9 EMA. Crossover above zero line = stronger buy signal. Histogram divergence from price warns of reversals before they happen. Avoid in ranging markets.",
  },
  {
    name: "Straddle Selling", category: "Options",        difficulty: "Advanced",
    description: "Sell ATM CE + PE, profit from time decay if market stays in range",
    detail: "Best on expiry week when theta decay accelerates. Adjust (hedge) if underlying moves >1.5% in one direction. Target: premium collected. Risk: unlimited if not hedged.",
  },
  {
    name: "Iron Condor",      category: "Options",        difficulty: "Advanced",
    description: "Sell OTM strangle + buy further OTM hedge — defined risk range strategy",
    detail: "Sell 1 OTM CE + 1 OTM PE, buy 1 further OTM CE + 1 further OTM PE. Max profit = net premium. Max loss = spread width − premium. Target: 50% of max profit exit.",
  },
  {
    name: "VWAP Revert",      category: "Mean Reversion", difficulty: "Intermediate",
    description: "Short above VWAP, long below VWAP — mean reversion intraday",
    detail: "Use intraday VWAP reset at 9:15. Enter within first 30 min when price deviates >0.5% from VWAP. Exit at VWAP. Stop: previous high/low. Only in liquid instruments.",
  },
  {
    name: "OBV Divergence",   category: "Volume",         difficulty: "Intermediate",
    description: "Trade when OBV diverges from price — hidden supply/demand",
    detail: "Bullish divergence: price makes lower low, OBV makes higher low → buy. Bearish divergence: price makes higher high, OBV makes lower high → sell. Confirm with volume spike.",
  },
  {
    name: "ATR Breakout",     category: "Volatility",     difficulty: "Beginner",
    description: "Enter when price moves > 1.5x ATR from previous close",
    detail: "Calculate ATR(14) on daily chart. Set long trigger at Close + 1.5×ATR and short trigger at Close − 1.5×ATR. Trail stop at 1×ATR. Works well for opening range breakouts.",
  },
  {
    name: "Donchian Channel", category: "Trend",          difficulty: "Beginner",
    description: "Buy at 20-day high breakout, sell at 10-day low breakdown",
    detail: "Classic turtle trading system. Use 20-day channel for entry, 10-day for exit. Add 55-day channel for major trend confirmation. Position size by ATR-based risk per trade.",
  },
  {
    name: "Wheel Strategy",   category: "Options",        difficulty: "Advanced",
    description: "Sell CSP → get assigned → sell CC → repeat. Income generation.",
    detail: "Step 1: Sell Cash-Secured Put at a strike you'd buy the stock. Step 2: If assigned, sell Covered Call at cost basis. Repeat. Best on high IV, liquid stocks you want to own.",
  },
];

const VIDEOS: VideoCard[] = [
  { title: "Options Trading for Beginners",    channel: "CA Rachana Ranade",  topic: "Options Basics",      url: "https://www.youtube.com/results?search_query=options+trading+beginners+india" },
  { title: "Technical Analysis Full Course",   channel: "Trading Chanakya",   topic: "Charts & Indicators", url: "https://www.youtube.com/results?search_query=technical+analysis+full+course+india" },
  { title: "NIFTY Intraday Strategy",          channel: "Power of Stocks",    topic: "Intraday",            url: "https://www.youtube.com/results?search_query=nifty+intraday+strategy" },
  { title: "Mutual Fund Investing",            channel: "Groww",              topic: "Investing Basics",    url: "https://www.youtube.com/results?search_query=mutual+fund+investing+india+beginners" },
  { title: "Option Greeks Explained",          channel: "Sensibull",          topic: "Options Advanced",    url: "https://www.youtube.com/results?search_query=option+greeks+explained+india" },
  { title: "Risk Management in Trading",       channel: "Vivek Bajaj",        topic: "Risk",                url: "https://www.youtube.com/results?search_query=risk+management+trading+india" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function difficultyColor(d: "Beginner" | "Intermediate" | "Advanced"): string {
  if (d === "Beginner")     return "bg-bullish-bg text-profit border-0";
  if (d === "Intermediate") return "bg-atm-bg text-warning border-0";
  return "bg-bearish-bg text-loss border-0";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function BasicsTab() {
  return (
    <StaggeredList className="space-y-5" staggerDelay={50}>
      {BASICS_SECTIONS.map((section) => (
        <GlassCard
          key={section.title}
          className="rounded-lg p-6 hover:-translate-y-0.5 transition-transform duration-200 cursor-default"
        >
          {/* Header row */}
          <div className="flex items-start justify-between gap-3 mb-3">
            <h3 className="font-heading font-semibold text-base text-text-primary leading-snug">
              {section.title}
            </h3>
            <div className="flex items-center gap-2 shrink-0">
              <Badge className={`text-xs ${difficultyColor(section.difficulty)}`}>
                {section.difficulty}
              </Badge>
              <span className="flex items-center gap-1 text-xs text-text-muted whitespace-nowrap">
                <Clock className="w-3 h-3" />
                {section.readingTime} min
              </span>
            </div>
          </div>
          <p className="text-sm text-text-secondary leading-relaxed">{section.content}</p>
        </GlassCard>
      ))}
    </StaggeredList>
  );
}

// ---------------------------------------------------------------------------
// Glossary accordion item
// ---------------------------------------------------------------------------

interface GlossaryItemProps {
  entry: GlossaryEntry;
}

function GlossaryItem({ entry }: GlossaryItemProps) {
  const [open, setOpen] = useState(false);

  return (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      aria-expanded={open}
      className="w-full text-left"
    >
      <GlassCard className="rounded-lg p-0 overflow-hidden hover:-translate-y-0.5 transition-transform duration-200">
        {/* Accordion header */}
        <div className="flex items-center gap-3 px-4 py-3">
          <span className="text-sm font-mono font-semibold text-accent shrink-0 w-28 truncate">
            {entry.term}
          </span>
          <span className="text-xs text-text-muted flex-1 line-clamp-1 text-left">
            {entry.definition}
          </span>
          <motion.div
            animate={{ rotate: open ? 180 : 0 }}
            transition={motionConfig.transitions.scale}
            className="shrink-0"
          >
            <ChevronDown className="w-3.5 h-3.5 text-text-muted" />
          </motion.div>
        </div>

        {/* Accordion body — smooth height reveal */}
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              key="body"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: motionConfig.duration.normal, ease: motionConfig.ease.enter }}
              style={{ overflow: "hidden" }}
            >
              <div className="px-4 pb-3 pt-0 border-t border-border-default/50">
                <p className="text-sm text-text-secondary leading-relaxed text-left">
                  {entry.definition}
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </GlassCard>
    </button>
  );
}

function GlossaryTab() {
  const [search, setSearch] = useState("");
  const filtered = GLOSSARY.filter(
    (e) =>
      e.term.toLowerCase().includes(search.toLowerCase()) ||
      e.definition.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
        <Input
          placeholder="Search terms..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9 bg-surface-card border-border-default"
          aria-label="Search glossary terms"
        />
      </div>

      <StaggeredList className="space-y-2" staggerDelay={30}>
        {filtered.map((entry) => (
          <GlossaryItem key={entry.term} entry={entry} />
        ))}
        {filtered.length === 0 && (
          <p className="text-sm text-text-muted text-center py-8">No matching terms</p>
        )}
      </StaggeredList>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Strategy card with animated detail reveal
// ---------------------------------------------------------------------------

interface StrategyCardItemProps {
  s: StrategyCard;
}

function StrategyCardItem({ s }: StrategyCardItemProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <button
      type="button"
      onClick={() => setExpanded((v) => !v)}
      aria-expanded={expanded}
      className="w-full text-left"
    >
      <GlassCard className="rounded-lg p-4 hover:-translate-y-0.5 transition-transform duration-200 cursor-pointer">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-semibold text-text-primary">{s.name}</h4>
          <div className="flex items-center gap-2">
            <Badge className={`text-xs ${difficultyColor(s.difficulty)}`}>{s.difficulty}</Badge>
            <motion.div
              animate={{ rotate: expanded ? 180 : 0 }}
              transition={motionConfig.transitions.scale}
            >
              <ChevronDown className="w-3.5 h-3.5 text-text-muted" />
            </motion.div>
          </div>
        </div>

        <Badge variant="outline" className="text-xs mb-2">{s.category}</Badge>
        <p className="text-xs text-text-secondary">{s.description}</p>

        {/* Animated detail reveal */}
        <AnimatePresence initial={false}>
          {expanded && (
            <motion.div
              key="detail"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: motionConfig.duration.normal, ease: motionConfig.ease.enter }}
              style={{ overflow: "hidden" }}
            >
              <div className="mt-3 pt-3 border-t border-border-default/50">
                <p className="text-xs text-text-secondary leading-relaxed">{s.detail}</p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </GlassCard>
    </button>
  );
}

function StrategiesTab() {
  const [filter, setFilter] = useState<string>("all");
  const categories = ["all", ...new Set(STRATEGIES.map((s) => s.category))];
  const filtered = filter === "all" ? STRATEGIES : STRATEGIES.filter((s) => s.category === filter);

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap">
        {categories.map((c) => (
          <Button
            key={c}
            variant={filter === c ? "default" : "outline"}
            size="sm"
            onClick={() => setFilter(c)}
            className="text-xs capitalize"
          >
            {c}
          </Button>
        ))}
      </div>

      <StaggeredList className="grid grid-cols-1 md:grid-cols-2 gap-3" staggerDelay={40}>
        {filtered.map((s) => (
          <StrategyCardItem key={s.name} s={s} />
        ))}
      </StaggeredList>
    </div>
  );
}

function PaperTradingTab() {
  return (
    <StaggeredList className="space-y-6" staggerDelay={60}>
      <GlassCard className="rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-3">
          What is Paper Trading?
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Paper trading lets you practice trading with virtual money. You execute the same strategies,
          see the same market data, but don&apos;t risk real capital. It&apos;s the best way to learn
          before going live.
        </p>
        <h4 className="font-heading font-semibold text-sm text-text-primary mb-2">
          How to Paper Trade with FlintTrade:
        </h4>
        <ol className="space-y-2 text-sm text-text-secondary list-decimal list-inside">
          <li>
            Set up OpenAlgo with your broker&apos;s <strong>Sandbox mode</strong>{" "}
            (Dhan Sandbox provides ₹10L virtual capital)
          </li>
          <li>Connect FlintTrade to the sandbox instance</li>
          <li>Trade normally — all orders execute against virtual funds</li>
          <li>Review your P&L Dashboard to analyze performance</li>
          <li>When confident, switch to your real broker credentials</li>
        </ol>
      </GlassCard>

      <GlassCard className="rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-3">
          Supported Sandboxes
        </h3>
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <Badge className="bg-bullish-bg text-profit border-0">Active</Badge>
            <span className="text-sm text-text-primary">Dhan Sandbox</span>
            <span className="text-xs text-text-muted">— ₹10L virtual funds, 24/7, all instruments</span>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="outline" className="text-xs">Planned</Badge>
            <span className="text-sm text-text-primary">Kotak Neo Sandbox</span>
            <span className="text-xs text-text-muted">— when available</span>
          </div>
        </div>
      </GlassCard>
    </StaggeredList>
  );
}

function VideoHubTab() {
  return (
    <StaggeredList className="grid grid-cols-1 md:grid-cols-2 gap-3" staggerDelay={50}>
      {VIDEOS.map((v) => (
        <a
          key={v.title}
          href={v.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block"
        >
          <GlassCard className="rounded-lg p-4 hover:-translate-y-0.5 transition-transform duration-200 cursor-pointer">
            <div className="flex items-start gap-3">
              <PlayCircle className="w-8 h-8 text-red-500 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <h4 className="text-sm font-semibold text-text-primary flex items-center gap-1">
                  {v.title}
                  <ExternalLink className="w-3 h-3 text-text-muted" />
                </h4>
                <p className="text-xs text-text-muted">{v.channel}</p>
                <Badge variant="outline" className="text-xs mt-1">{v.topic}</Badge>
              </div>
            </div>
          </GlassCard>
        </a>
      ))}
    </StaggeredList>
  );
}

// ---------------------------------------------------------------------------
// Sidebar nav item with progress bar
// ---------------------------------------------------------------------------

interface SidebarItemProps {
  tab: TabDef;
  isActive: boolean;
  collapsed: boolean;
  onClick: () => void;
}

function SidebarItem({ tab, isActive, collapsed, onClick }: SidebarItemProps) {
  const Icon = tab.icon;

  return (
    <div className="relative">
      <button
        type="button"
        role="tab"
        aria-selected={isActive}
        onClick={onClick}
        title={collapsed ? tab.label : undefined}
        className={`w-full flex items-center gap-3 px-3 py-2.5 text-sm font-sans transition-colors border-l-2 ${
          isActive
            ? "text-accent bg-accent/10 border-accent"
            : "text-text-secondary hover:text-text-primary hover:bg-surface-base border-transparent"
        }`}
      >
        <Icon className="w-4 h-4 shrink-0" />

        {/* Label — hidden when collapsed */}
        <AnimatePresence initial={false}>
          {!collapsed && (
            <motion.span
              key="label"
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: "auto" }}
              exit={{ opacity: 0, width: 0 }}
              transition={{ duration: motionConfig.duration.normal, ease: motionConfig.ease.enter }}
              className="truncate flex-1 text-left"
              style={{ overflow: "hidden", whiteSpace: "nowrap" }}
            >
              {tab.label}
            </motion.span>
          )}
        </AnimatePresence>

        {/* Active chevron — hidden when collapsed */}
        {!collapsed && (
          <ChevronRight
            className={`w-3 h-3 ml-auto shrink-0 transition-opacity ${isActive ? "opacity-100" : "opacity-0"}`}
          />
        )}
      </button>

      {/* Progress bar — only visible when expanded */}
      <AnimatePresence initial={false}>
        {!collapsed && tab.progress > 0 && (
          <motion.div
            key="progress"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: motionConfig.duration.fast }}
            className="mx-3 mb-1"
          >
            <div className="h-0.5 w-full rounded-full bg-border-default/50">
              <motion.div
                className="h-full rounded-full bg-accent/60"
                initial={{ width: 0 }}
                animate={{ width: `${tab.progress}%` }}
                transition={{ duration: motionConfig.duration.slow, ease: motionConfig.ease.enter }}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export default function LearnRoute() {
  const [activeTab, setActiveTab] = useState<TabId>("basics");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const level = useSkillLevel("learn");

  // Density adaptation — beginner sees fewer sidebar items
  // Beginner: basics + glossary prominently (guided lesson list)
  // Intermediate: all sections
  // Advanced: all sections
  const visibleTabIds: TabId[] = (() => {
    if (level === "beginner") return ["basics", "glossary", "paper"];
    return ["basics", "glossary", "strategies", "paper", "videos"];
  })();

  const visibleTabs = TABS.filter((t) => visibleTabIds.includes(t.id));

  const tabContent: Record<TabId, React.ReactNode> = {
    basics:     <BasicsTab />,
    glossary:   <GlossaryTab />,
    strategies: <StrategiesTab />,
    paper:      <PaperTradingTab />,
    videos:     <VideoHubTab />,
  };

  return (
    <CinematicLayout mode="cinematic">
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <BlurFade delay={0} duration={0.5}>
        <div className="border-b border-border-default bg-surface-card/80 backdrop-blur-sm px-6 py-4" data-tour-target="course-list">
          <div className="flex items-center gap-3">
            <GraduationCap className="w-6 h-6 text-accent" />
            <div>
              <TextGenerateEffect
                words={level === "beginner" ? "Getting Started" : "Learning Center"}
                className="font-bold text-lg text-text-primary"
                duration={0.3}
              />
              <p className="text-xxs text-text-muted">
                {level === "beginner"
                  ? "Learn the basics of trading — one lesson at a time"
                  : "Market basics, strategies, and paper trading guides"}
              </p>
            </div>
          </div>
        </div>
      </BlurFade>

      <div className="flex flex-1 overflow-hidden">
        {/* Collapsible sidebar */}
        <motion.div
          animate={{ width: sidebarCollapsed ? 48 : 224 }}
          transition={{ duration: motionConfig.duration.normal, ease: motionConfig.ease.enter }}
          className="border-r border-border-default bg-surface-card shrink-0 flex flex-col overflow-hidden"
          style={{ minWidth: 0 }}
        >
          {/* Collapse toggle */}
          <div className={`flex py-2 ${sidebarCollapsed ? "justify-center" : "justify-end px-2"}`}>
            <button
              type="button"
              onClick={() => setSidebarCollapsed((v) => !v)}
              title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="p-1.5 rounded-md text-text-muted hover:text-text-primary hover:bg-surface-base transition-colors"
            >
              {sidebarCollapsed ? (
                <PanelLeftOpen className="w-4 h-4" />
              ) : (
                <PanelLeftClose className="w-4 h-4" />
              )}
            </button>
          </div>

          {/* Nav items — filtered by skill level */}
          <nav aria-label="Learning sections" className="flex-1 overflow-y-auto" data-tour-target="glossary">
            <div role="tablist" aria-orientation="vertical" className="flex flex-col">
              {visibleTabs.map((tab) => (
                <SidebarItem
                  key={tab.id}
                  tab={tab}
                  isActive={activeTab === tab.id}
                  collapsed={sidebarCollapsed}
                  onClick={() => setActiveTab(tab.id)}
                />
              ))}
            </div>
          </nav>
        </motion.div>

        {/* Content area */}
        <ScrollArea className="flex-1">
          <div role="tabpanel" className="p-6 max-w-4xl">
            <TabTransition tabKey={activeTab}>
              {tabContent[activeTab]}
            </TabTransition>
          </div>
        </ScrollArea>
      </div>

      {/* Guided tour — beginner only, first visit */}
      {level === "beginner" && (
        <SpotlightTour
          tourId="learn-beginner"
          steps={TOUR_DEFINITIONS["learn-beginner"] ?? []}
        />
      )}
    </div>
    </CinematicLayout>
  );
}
