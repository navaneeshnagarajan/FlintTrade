import React, { useState } from "react";
import {
  BookOpen,
  GraduationCap,
  BarChart3,
  PlayCircle,
  Search,
  ChevronRight,
  ExternalLink,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TabId = "basics" | "glossary" | "strategies" | "paper" | "videos";

interface TabDef {
  id: TabId;
  label: string;
  icon: typeof BookOpen;
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
}

interface VideoCard {
  title: string;
  channel: string;
  topic: string;
  url: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TABS: TabDef[] = [
  { id: "basics", label: "Market Basics", icon: BookOpen },
  { id: "glossary", label: "Glossary", icon: GraduationCap },
  { id: "strategies", label: "Strategy Library", icon: BarChart3 },
  { id: "paper", label: "Paper Trading", icon: TrendingUp },
  { id: "videos", label: "Video Hub", icon: PlayCircle },
];

const BASICS_SECTIONS = [
  {
    title: "What are Stocks?",
    content:
      "Stocks represent ownership in a company. When you buy a stock, you become a shareholder. Stock prices change based on supply and demand — if more people want to buy than sell, the price goes up. In India, stocks trade on NSE (National Stock Exchange) and BSE (Bombay Stock Exchange).",
  },
  {
    title: "Understanding F&O",
    content:
      "Futures & Options (F&O) are derivative instruments. A Future is an agreement to buy/sell an asset at a predetermined price on a specific date. An Option gives you the right (not obligation) to buy (Call) or sell (Put) at a specific price (Strike). F&O requires less capital than stocks but carries higher risk.",
  },
  {
    title: "Mutual Funds & SIPs",
    content:
      "A Mutual Fund pools money from many investors to invest in stocks, bonds, or other assets. A SIP (Systematic Investment Plan) lets you invest a fixed amount regularly (monthly). SIPs average out the purchase price over time (rupee cost averaging), reducing risk for long-term investors.",
  },
  {
    title: "Index Trading",
    content:
      "An index tracks the performance of a group of stocks. NIFTY 50 tracks the top 50 companies on NSE. SENSEX tracks the top 30 on BSE. BANKNIFTY tracks banking stocks. Index trading through F&O is popular because it provides market-level exposure without picking individual stocks.",
  },
  {
    title: "Understanding Risk",
    content:
      "Never invest money you cannot afford to lose. Use stop-losses to limit downside. Diversify across stocks and sectors. For F&O, understand margin requirements — you can lose more than your invested amount. Start with paper trading before using real money.",
  },
  {
    title: "SEBI Regulations",
    content:
      "SEBI (Securities and Exchange Board of India) regulates Indian markets. Key rules: maximum 10 orders per second for algo trading, mandatory 5-year audit trail, static IP required for API trading. FlintTrade is designed to comply with all SEBI regulations automatically.",
  },
];

const GLOSSARY: GlossaryEntry[] = [
  { term: "ATM", definition: "At The Money — option strike closest to current market price" },
  { term: "Bid/Ask", definition: "Bid is the highest buy price, Ask is the lowest sell price" },
  { term: "Call Option", definition: "Right to BUY an asset at a specific price (bullish)" },
  { term: "Delta", definition: "Rate of change of option price per ₹1 move in underlying" },
  { term: "EMA", definition: "Exponential Moving Average — weighted average giving more importance to recent prices" },
  { term: "F&O", definition: "Futures and Options — derivative instruments" },
  { term: "Gamma", definition: "Rate of change of Delta — measures acceleration of price change" },
  { term: "Hedge", definition: "A position taken to offset potential losses in another position" },
  { term: "IV", definition: "Implied Volatility — market's expectation of future price movement" },
  { term: "Lot Size", definition: "Minimum quantity for F&O trading. NIFTY=25, BANKNIFTY=15" },
  { term: "Margin", definition: "Deposit required to open F&O positions. Can be SPAN + Exposure." },
  { term: "MTM", definition: "Mark To Market — daily P&L calculation based on closing price" },
  { term: "NRML", definition: "Normal position — can be carried overnight, higher margin" },
  { term: "OI", definition: "Open Interest — total outstanding derivative contracts" },
  { term: "PCR", definition: "Put-Call Ratio — Put OI / Call OI. >1 = bearish, <1 = bullish" },
  { term: "Put Option", definition: "Right to SELL an asset at a specific price (bearish)" },
  { term: "RSI", definition: "Relative Strength Index — momentum oscillator (0-100, >70 overbought, <30 oversold)" },
  { term: "SL", definition: "Stop Loss — automatic exit to limit losses" },
  { term: "Straddle", definition: "Buying both Call and Put at same strike — profits from big moves in either direction" },
  { term: "Theta", definition: "Time decay — how much option value decreases per day" },
  { term: "Underlying", definition: "The asset an F&O contract derives its value from (e.g., NIFTY index)" },
  { term: "Vega", definition: "Sensitivity of option price to changes in implied volatility" },
  { term: "VIX", definition: "India Volatility Index — measures expected market volatility over 30 days" },
  { term: "VWAP", definition: "Volume Weighted Average Price — average price weighted by trading volume" },
];

const STRATEGIES: StrategyCard[] = [
  { name: "EMA Crossover", category: "Trend", difficulty: "Beginner", description: "Buy when fast EMA crosses above slow EMA, sell on reverse" },
  { name: "RSI Reversal", category: "Momentum", difficulty: "Beginner", description: "Buy below RSI 30, sell above RSI 70" },
  { name: "Supertrend", category: "Trend", difficulty: "Beginner", description: "Follow ATR-based trend indicator — green = long, red = short" },
  { name: "Bollinger Squeeze", category: "Volatility", difficulty: "Intermediate", description: "Enter breakout when bands contract then expand" },
  { name: "MACD Signal", category: "Momentum", difficulty: "Intermediate", description: "Trade MACD line crossing signal line" },
  { name: "Straddle Selling", category: "Options", difficulty: "Advanced", description: "Sell ATM CE + PE, profit from time decay if market stays in range" },
  { name: "Iron Condor", category: "Options", difficulty: "Advanced", description: "Sell OTM strangle + buy further OTM hedge — defined risk range strategy" },
  { name: "VWAP Revert", category: "Mean Reversion", difficulty: "Intermediate", description: "Short above VWAP, long below VWAP — mean reversion intraday" },
  { name: "OBV Divergence", category: "Volume", difficulty: "Intermediate", description: "Trade when OBV diverges from price — hidden supply/demand" },
  { name: "ATR Breakout", category: "Volatility", difficulty: "Beginner", description: "Enter when price moves > 1.5x ATR from previous close" },
  { name: "Donchian Channel", category: "Trend", difficulty: "Beginner", description: "Buy at 20-day high breakout, sell at 10-day low breakdown" },
  { name: "Wheel Strategy", category: "Options", difficulty: "Advanced", description: "Sell CSP → get assigned → sell CC → repeat. Income generation." },
];

const VIDEOS: VideoCard[] = [
  { title: "Options Trading for Beginners", channel: "CA Rachana Ranade", topic: "Options Basics", url: "https://www.youtube.com/results?search_query=options+trading+beginners+india" },
  { title: "Technical Analysis Full Course", channel: "Trading Chanakya", topic: "Charts & Indicators", url: "https://www.youtube.com/results?search_query=technical+analysis+full+course+india" },
  { title: "NIFTY Intraday Strategy", channel: "Power of Stocks", topic: "Intraday", url: "https://www.youtube.com/results?search_query=nifty+intraday+strategy" },
  { title: "Mutual Fund Investing", channel: "Groww", topic: "Investing Basics", url: "https://www.youtube.com/results?search_query=mutual+fund+investing+india+beginners" },
  { title: "Option Greeks Explained", channel: "Sensibull", topic: "Options Advanced", url: "https://www.youtube.com/results?search_query=option+greeks+explained+india" },
  { title: "Risk Management in Trading", channel: "Vivek Bajaj", topic: "Risk", url: "https://www.youtube.com/results?search_query=risk+management+trading+india" },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function BasicsTab() {
  return (
    <div className="space-y-6">
      {BASICS_SECTIONS.map((section) => (
        <Card key={section.title} className="bg-surface-card border border-border-default rounded-lg p-6">
          <h3 className="font-heading font-semibold text-lg text-text-primary mb-2">{section.title}</h3>
          <p className="text-sm text-text-secondary leading-relaxed">{section.content}</p>
        </Card>
      ))}
    </div>
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
        />
      </div>
      <div className="space-y-2">
        {filtered.map((entry) => (
          <div key={entry.term} className="flex gap-3 p-3 rounded-lg bg-surface-card border border-border-default shadow-sm">
            <span className="text-sm font-mono font-semibold text-accent shrink-0 w-24">
              {entry.term}
            </span>
            <span className="text-sm text-text-secondary">{entry.definition}</span>
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="text-sm text-text-muted text-center py-8">No matching terms</p>
        )}
      </div>
    </div>
  );
}

function StrategiesTab() {
  const [filter, setFilter] = useState<string>("all");
  const categories = ["all", ...new Set(STRATEGIES.map((s) => s.category))];
  const filtered = filter === "all" ? STRATEGIES : STRATEGIES.filter((s) => s.category === filter);

  const difficultyColor = (d: string) =>
    d === "Beginner" ? "bg-green-500/20 text-green-400" :
    d === "Intermediate" ? "bg-yellow-500/20 text-yellow-400" :
    "bg-red-500/20 text-red-400";

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
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {filtered.map((s) => (
          <Card key={s.name} className="bg-surface-card border border-border-default rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold text-text-primary">{s.name}</h4>
              <Badge className={`text-xs ${difficultyColor(s.difficulty)}`}>{s.difficulty}</Badge>
            </div>
            <Badge variant="outline" className="text-xs mb-2">{s.category}</Badge>
            <p className="text-xs text-text-secondary">{s.description}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}

function PaperTradingTab() {
  return (
    <div className="space-y-6">
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-3">What is Paper Trading?</h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4">
          Paper trading lets you practice trading with virtual money. You execute the same strategies,
          see the same market data, but don&apos;t risk real capital. It&apos;s the best way to learn
          before going live.
        </p>
        <h4 className="font-heading font-semibold text-sm text-text-primary mb-2">How to Paper Trade with FlintTrade:</h4>
        <ol className="space-y-2 text-sm text-text-secondary list-decimal list-inside">
          <li>Set up OpenAlgo with your broker&apos;s <strong>Sandbox mode</strong> (Dhan Sandbox provides ₹10L virtual capital)</li>
          <li>Connect FlintTrade to the sandbox instance</li>
          <li>Trade normally — all orders execute against virtual funds</li>
          <li>Review your P&L Dashboard to analyze performance</li>
          <li>When confident, switch to your real broker credentials</li>
        </ol>
      </Card>
      <Card className="bg-surface-card border border-border-default rounded-lg p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-3">Supported Sandboxes</h3>
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <Badge className="bg-green-500/20 text-green-400">Active</Badge>
            <span className="text-sm text-text-primary">Dhan Sandbox</span>
            <span className="text-xs text-text-muted">— ₹10L virtual funds, 24/7, all instruments</span>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="outline" className="text-xs">Planned</Badge>
            <span className="text-sm text-text-primary">Kotak Neo Sandbox</span>
            <span className="text-xs text-text-muted">— when available</span>
          </div>
        </div>
      </Card>
    </div>
  );
}

function VideoHubTab() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {VIDEOS.map((v) => (
        <a
          key={v.title}
          href={v.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block"
        >
          <Card className="bg-surface-card border border-border-default rounded-lg p-4 hover:border-accent/40 transition-colors cursor-pointer">
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
          </Card>
        </a>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export default function LearnRoute() {
  const [activeTab, setActiveTab] = useState<TabId>("basics");

  const tabContent: Record<TabId, React.ReactNode> = {
    basics: <BasicsTab />,
    glossary: <GlossaryTab />,
    strategies: <StrategiesTab />,
    paper: <PaperTradingTab />,
    videos: <VideoHubTab />,
  };

  return (
    <div className="h-full bg-surface-base flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 py-4">
        <div className="flex items-center gap-3">
          <GraduationCap className="w-6 h-6 text-accent" />
          <div>
            <h1 className="font-heading font-bold text-lg text-text-primary">Learning Center</h1>
            <p className="text-xxs text-text-muted">Market basics, strategies, and paper trading guides</p>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar tabs */}
        <div className="w-56 border-r border-border-default bg-surface-card shrink-0 py-2">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm font-sans transition-colors ${
                  isActive
                    ? "text-accent bg-accent/10 border-l-2 border-accent"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-base"
                }`}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
                <ChevronRight className={`w-3 h-3 ml-auto ${isActive ? "opacity-100" : "opacity-0"}`} />
              </button>
            );
          })}
        </div>

        {/* Content */}
        <ScrollArea className="flex-1">
          <div className="p-6 max-w-4xl">{tabContent[activeTab]}</div>
        </ScrollArea>
      </div>
    </div>
  );
}
