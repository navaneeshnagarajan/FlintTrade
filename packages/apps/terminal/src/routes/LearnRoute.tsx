import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { Link, useLocation } from "react-router";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillStore } from "@/stores/skillStore";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
import { motion, AnimatePresence } from "framer-motion";
import {
  BookOpen,
  GraduationCap,
  BarChart3,
  PlayCircle,
  Search,
  ChevronRight,
  TrendingUp,
  PanelLeftClose,
  PanelLeftOpen,
  Clock,
  ChevronDown,
  ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { GlassCard } from "@/components/ui/GlassCard";
import TabTransition from "@/components/motion/TabTransition";
import { motionConfig } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TabId = "basics" | "glossary" | "strategies" | "paper" | "resources";

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
  /** Exchange circular or contract file for figures that get revised. */
  verifyHref?: string;
  verifyLabel?: string;
}

interface StrategyCard {
  name: string;
  category: string;
  difficulty: "Beginner" | "Intermediate" | "Advanced";
  description: string;
  /** Extra detail revealed on click */
  detail: string;
}

interface ResourceCard {
  title: string;
  source: string;
  topic: string;
  path: string;
}

interface SelectedDoc {
  path: string;
  title: string;
  snippet?: string;
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

const LEARN_DESKTOP_MEDIA_QUERY = "(min-width: 768px)";

const TABS: TabDef[] = [
  { id: "basics",     label: "Market Basics",    icon: BookOpen,     progress: 33 },
  { id: "glossary",   label: "Glossary",          icon: GraduationCap, progress: 0  },
  { id: "strategies", label: "Strategy Library",  icon: BarChart3,    progress: 16 },
  { id: "paper",      label: "Practice Trading",  icon: TrendingUp,   progress: 0  },
  { id: "resources",  label: "Resource Hub",      icon: PlayCircle,   progress: 0  },
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
      "Never invest money you cannot afford to lose. Use stop-losses to limit downside. Diversify across stocks and sectors. For F&O, understand margin requirements — you can lose more than your invested amount. Start with practice trading before using real money.",
  },
  {
    title: "Market Rules",
    readingTime: 2,
    difficulty: "Beginner",
    content:
      "Indian market access is governed by exchanges, brokers, and regulators. If you connect a broker API, review your broker's static-IP, session, order-rate, and account-safety requirements first. FlintTrade is personal-use software and does not make a regulatory-compliance guarantee.",
  },
];

/**
 * Learn Glossary entries. Any figure an exchange revises must ship with an
 * “as of” date and a verify link — stale undated lots are a bug (FT-LEARN-002).
 */
const LEARN_INDEX_LOT_VERIFY_HREF =
  "https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf";

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
  {
    term: "Lot Size",
    definition:
      "Minimum quantity for F&O trading. NIFTY 65 · BANKNIFTY 30 · FINNIFTY 60 · MIDCPNIFTY 120 (as of Jan 2026 NSE cycle).",
    verifyHref: LEARN_INDEX_LOT_VERIFY_HREF,
    verifyLabel: "Verify on NSE",
  },
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
    description: "Study fast/slow EMA crossover behaviour",
    detail: "Commonly used pairs include 9/21 EMA and 50/200 EMA. Review crossover timing, sideways-market false signals, and timeframe sensitivity in Practice analysis.",
  },
  {
    name: "RSI Reversal",     category: "Momentum",       difficulty: "Beginner",
    description: "Study RSI overbought and oversold regimes",
    detail: "Use RSI(14) as a default diagnostic. Compare RSI with price support/resistance and trend filters because strong trends can keep RSI elevated or depressed for extended periods.",
  },
  {
    name: "Supertrend",       category: "Trend",          difficulty: "Beginner",
    description: "Follow ATR-based trend indicator — green = long, red = short",
    detail: "Default parameters: ATR(10), multiplier 3. Flip position on color change. Add volume filter to reduce whipsaws. Best on daily chart for swing trades.",
  },
  {
    name: "Bollinger Squeeze",category: "Volatility",     difficulty: "Intermediate",
    description: "Study volatility compression before expansion",
    detail: "Look for BB width at multi-month lows, then inspect how later expansion behaves in historical replay. Compare RSI, MACD, and ATR diagnostics before treating it as a Practice hypothesis.",
  },
  {
    name: "MACD Signal",      category: "Momentum",       difficulty: "Intermediate",
    description: "Understand how MACD line and signal-line crossovers are interpreted",
    detail: "Settings: 12/26/9 EMA. Crossovers, zero-line position, and histogram divergence are examples of momentum diagnostics. Use them for study and Practice review, not as standalone instructions.",
  },
  {
    name: "Straddle Selling", category: "Options",        difficulty: "Advanced",
    description: "Study ATM CE + PE short-premium payoff shape and risk",
    detail: "This concept shows how theta decay and range-bound assumptions affect a short-premium payoff. Review margin, hedging, and gap-risk behaviour in Practice only; unhedged short options can carry open-ended loss.",
  },
  {
    name: "Iron Condor",      category: "Options",        difficulty: "Advanced",
    description: "Study OTM short legs with further OTM hedges as a defined-risk payoff",
    detail: "This concept combines two short OTM legs with further OTM hedges. Use the payoff view to inspect max gain, max loss, breakevens, and margin assumptions before any live-mode consideration.",
  },
  {
    name: "VWAP Revert",      category: "Mean Reversion", difficulty: "Intermediate",
    description: "Study VWAP deviation as a mean-reversion diagnostic",
    detail: "Use intraday VWAP reset examples to compare price deviation, liquidity, and reversion assumptions in replay or Practice mode. The lesson is a diagnostic pattern, not an entry rule.",
  },
  {
    name: "OBV Divergence",   category: "Volume",         difficulty: "Intermediate",
    description: "Study when OBV diverges from price as a supply/demand clue",
    detail: "Bullish and bearish divergence examples show how volume can disagree with price. Use them to annotate charts and backtests; require independent validation before any live workflow.",
  },
  {
    name: "ATR Breakout",     category: "Volatility",     difficulty: "Beginner",
    description: "Study moves that exceed an ATR-based volatility band",
    detail: "Calculate ATR(14) on historical data and compare price moves against volatility bands. This helps explain breakout tests, trail assumptions, and false-break behaviour in Practice analysis.",
  },
  {
    name: "Donchian Channel", category: "Trend",          difficulty: "Beginner",
    description: "Study channel breakout and breakdown concepts",
    detail: "Classic channel systems use rolling highs/lows to model trend following. Review 20-day, 10-day, and 55-day channel examples in backtests and inspect drawdown before any live workflow.",
  },
  {
    name: "Wheel Strategy",   category: "Options",        difficulty: "Advanced",
    description: "Study cash-secured put and covered-call assignment workflow",
    detail: "This concept explains the mechanics of cash-secured puts, assignment, and covered calls. It is included for payoff education and operational understanding, not as a recommendation.",
  },
];

const RESOURCES: ResourceCard[] = [
  { title: "User Guide",            source: "Project docs", topic: "Setup",        path: "USER_GUIDE.md" },
  { title: "Order Safety Notes",    source: "Project docs", topic: "Safety",       path: "ORDER_SAFETY.md" },
  { title: "API Reference",         source: "Project docs", topic: "Integration",  path: "API.md" },
  { title: "Compatibility Matrix",  source: "Project docs", topic: "Environment",  path: "COMPATIBILITY.md" },
  { title: "Architecture Overview", source: "Project docs", topic: "Design",       path: "ARCHITECTURE.md" },
  { title: "Developer Guide",       source: "Project docs", topic: "Contribution", path: "DEVELOPER_GUIDE.md" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function difficultyColor(d: "Beginner" | "Intermediate" | "Advanced"): string {
  if (d === "Beginner")     return "bg-bullish-bg text-profit border-0";
  if (d === "Intermediate") return "bg-atm-bg text-warning border-0";
  return "bg-bearish-bg text-loss border-0";
}

function titleFromDocPath(path: string): string {
  return path
    .replace(/\.[^.]+$/, "")
    .split(/[/-]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function getSelectedDoc(state: unknown): SelectedDoc | null {
  if (!state || typeof state !== "object") return null;
  const maybeDoc = (state as { selectedDoc?: unknown }).selectedDoc;
  if (maybeDoc && typeof maybeDoc === "object") {
    const doc = maybeDoc as { path?: unknown; title?: unknown; snippet?: unknown };
    if (typeof doc.path === "string") {
      return {
        path: doc.path,
        title: typeof doc.title === "string" ? doc.title : titleFromDocPath(doc.path),
        snippet: typeof doc.snippet === "string" ? doc.snippet : undefined,
      };
    }
  }

  const path = (state as { selectedDocPath?: unknown }).selectedDocPath;
  if (typeof path === "string") {
    return { path, title: titleFromDocPath(path) };
  }

  return null;
}

async function fetchDocsDocument(path: string, signal?: AbortSignal): Promise<{ title: string; content: string }> {
  const params = new URLSearchParams({ path });
  const response = await fetch(`/ft-api/v1/docs/document?${params.toString()}`, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = (await response.json()) as { title?: unknown; content?: unknown };
  if (typeof body.title !== "string" || typeof body.content !== "string") {
    throw new Error("Unexpected docs response");
  }
  return { title: body.title, content: body.content };
}

function renderDocLine(line: string, key: number) {
  if (/^#\s/.test(line)) {
    return <h2 key={key} className="text-base font-semibold text-text-primary mt-3">{line.replace(/^#\s+/, "")}</h2>;
  }
  if (/^##\s/.test(line)) {
    return <h3 key={key} className="text-sm font-semibold text-text-primary mt-3">{line.replace(/^##\s+/, "")}</h3>;
  }
  if (/^###\s/.test(line)) {
    return (
      <h4 key={key} className="text-xs font-semibold text-text-secondary uppercase tracking-wider mt-3">
        {line.replace(/^###\s+/, "")}
      </h4>
    );
  }
  if (/^[-*]\s/.test(line)) {
    return (
      <li key={key} className="text-xs text-text-secondary leading-relaxed list-disc list-inside">
        {line.replace(/^[-*]\s+/, "")}
      </li>
    );
  }
  if (/^\d+\.\s/.test(line)) {
    return (
      <li key={key} className="text-xs text-text-secondary leading-relaxed list-decimal list-inside">
        {line.replace(/^\d+\.\s+/, "")}
      </li>
    );
  }
  if (line.trim() === "") return <div key={key} className="h-1" />;
  return <p key={key} className="text-xs text-text-secondary leading-relaxed">{line}</p>;
}

function DocMarkdown({ content }: { content: string }) {
  return <div className="space-y-1">{content.split(/\r?\n/).map(renderDocLine)}</div>;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function BasicsTab() {
  return (
    <div className="space-y-5 animate-fade-in">
      {BASICS_SECTIONS.map((section) => (
        <GlassCard
          key={section.title}
          className="rounded-lg p-6 hover:border-border-strong transition-colors duration-150 cursor-default"
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
    </div>
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
    <GlassCard className="rounded-lg p-0 hover:border-border-strong transition-colors duration-150">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full text-left"
      >
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
      </button>

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
            <div className="flex flex-col gap-2 border-t border-border-default/50 px-4 pb-3 pt-2">
              <p className="text-left text-sm leading-relaxed text-text-secondary">
                {entry.definition}
              </p>
              {entry.verifyHref && entry.verifyLabel && (
                <Button asChild variant="link" size="sm" className="h-auto w-fit px-0">
                  <a
                    href={entry.verifyHref}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink data-icon="inline-start" />
                    {entry.verifyLabel}
                  </a>
                </Button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </GlassCard>
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

      <div className="space-y-2 animate-fade-in">
        {filtered.map((entry) => (
          <GlossaryItem key={entry.term} entry={entry} />
        ))}
        {filtered.length === 0 && (
          <p className="text-sm text-text-muted text-center py-8">No matching terms</p>
        )}
      </div>
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
      <GlassCard className="rounded-lg p-4 hover:border-border-strong transition-colors duration-150 cursor-pointer">
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

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 animate-fade-in">
        {filtered.map((s) => (
          <StrategyCardItem key={s.name} s={s} />
        ))}
      </div>
    </div>
  );
}

function PaperTradingTab() {
  return (
    <div data-testid="practice-trading" className="min-w-0 max-w-full space-y-6 animate-fade-in">
      <GlassCard className="min-w-0 rounded-lg p-4 sm:p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-3 break-words">
          What is Practice Trading?
        </h3>
        <p className="text-sm text-text-secondary leading-relaxed mb-4 break-words">
          Practice trading lets you trade with virtual money. You execute the same strategies,
          see the same market data, but don&apos;t risk real capital. It&apos;s the best way to learn
          before going live.
        </p>
        <h4 className="font-heading font-semibold text-sm text-text-primary mb-2 break-words">
          How to start Practice Trading:
        </h4>
        <ol className="min-w-0 space-y-2 pl-5 text-sm text-text-secondary list-decimal list-outside break-words">
          <li>
            Set up OpenAlgo with your broker&apos;s <strong>Practice mode</strong>{" "}
            (Dhan Sandbox provides ₹10L virtual capital)
          </li>
          <li>Configure FlintTrade&apos;s Broker Gateway to reach that OpenAlgo Practice instance</li>
          <li>Trade normally — all orders execute against virtual funds</li>
          <li>Review your P&L Dashboard to analyse performance</li>
          <li>When confident, point OpenAlgo at your live broker credentials</li>
        </ol>
        <div className="mt-4 min-w-0">
          <p className="mb-3 text-sm text-text-secondary break-words">
            Configure OpenAlgo in Settings → Broker Gateway.
          </p>
          <Button
            asChild
            className="h-auto w-full min-w-0 max-w-full shrink whitespace-normal break-words sm:w-auto"
          >
            <Link to="/settings#api">Open Settings → Broker Gateway</Link>
          </Button>
        </div>
      </GlassCard>

      <GlassCard className="min-w-0 rounded-lg p-4 sm:p-6">
        <h3 className="font-heading font-semibold text-lg text-text-primary mb-3 break-words">
          Supported Sandboxes
        </h3>
        <div className="space-y-3">
          <div
            data-testid="practice-sandbox-row"
            className="flex min-w-0 flex-wrap items-center gap-2"
          >
            <Badge className="shrink-0 bg-bullish-bg text-profit border-0">Active</Badge>
            <span className="text-sm text-text-primary">Dhan Sandbox</span>
            <span className="min-w-0 break-words text-xs text-text-muted">
              — ₹10L virtual funds, 24/7, all instruments
            </span>
          </div>
          <div
            data-testid="practice-sandbox-row"
            className="flex min-w-0 flex-wrap items-center gap-2"
          >
            <Badge variant="outline" className="shrink-0 text-xs">Planned</Badge>
            <span className="text-sm text-text-primary">Kotak Neo Sandbox</span>
            <span className="min-w-0 break-words text-xs text-text-muted">— when available</span>
          </div>
        </div>
      </GlassCard>
    </div>
  );
}

function ResourceHubTab({ selectedDoc }: { selectedDoc: SelectedDoc | null }) {
  const [activeDoc, setActiveDoc] = useState<SelectedDoc | null>(selectedDoc);
  const [docContent, setDocContent] = useState<{ title: string; content: string } | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [docError, setDocError] = useState<string | null>(null);

  useEffect(() => {
    if (selectedDoc) setActiveDoc(selectedDoc);
  }, [selectedDoc]);

  useEffect(() => {
    if (!activeDoc) {
      setDocContent(null);
      setDocError(null);
      setDocLoading(false);
      return;
    }

    const controller = new AbortController();
    setDocLoading(true);
    setDocError(null);
    fetchDocsDocument(activeDoc.path, controller.signal)
      .then((document) => setDocContent(document))
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setDocContent(null);
        setDocError("Could not load this document from the local backend.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setDocLoading(false);
      });

    return () => controller.abort();
  }, [activeDoc]);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 animate-fade-in">
      {activeDoc && (
        <GlassCard className="rounded-lg p-4 border-accent/40 bg-accent/5 md:col-span-2">
          <div className="flex items-start gap-3 mb-3">
            <BookOpen className="w-8 h-8 text-accent shrink-0 mt-0.5" />
            <div className="min-w-0">
              <h4 className="text-sm font-semibold text-text-primary">{docContent?.title ?? activeDoc.title}</h4>
              <p className="text-xs text-text-muted mt-0.5">
                {activeDoc.snippet ?? "Selected from documentation search"}
              </p>
              <p className="mt-2 font-mono text-[10px] text-text-muted/70 truncate">
                docs/{activeDoc.path}
              </p>
            </div>
          </div>
          {docLoading && <p className="text-xs text-text-muted">Loading document...</p>}
          {docError && <p role="alert" className="text-xs text-loss">{docError}</p>}
          {docContent && (
            <article className="max-h-[38rem] overflow-y-auto rounded-md border border-border-default bg-surface-base/70 p-4">
              <DocMarkdown content={docContent.content} />
            </article>
          )}
        </GlassCard>
      )}
      {RESOURCES.map((v) => (
        <button
          type="button"
          key={v.title}
          onClick={() => setActiveDoc({ path: v.path, title: v.title, snippet: v.source })}
          className="block text-left"
        >
          <GlassCard className="rounded-lg p-4 hover:border-border-strong transition-colors duration-150 cursor-pointer">
            <div className="flex items-start gap-3">
              <BookOpen className="w-8 h-8 text-accent shrink-0 mt-0.5" />
              <div className="min-w-0">
                <h4 className="text-sm font-semibold text-text-primary">{v.title}</h4>
                <p className="text-xs text-text-muted">{v.source}</p>
                <Badge variant="outline" className="text-xs mt-1">{v.topic}</Badge>
              </div>
            </div>
          </GlassCard>
        </button>
      ))}
    </div>
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
        id={`learn-tab-${tab.id}`}
        aria-selected={isActive}
        aria-controls={`learn-tabpanel-${tab.id}`}
        tabIndex={isActive ? 0 : -1}
        onClick={onClick}
        title={collapsed ? tab.label : undefined}
        className={`flex w-auto min-w-0 items-center gap-3 border-l-2 px-3 py-2.5 text-sm font-sans transition-colors md:w-full ${
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
  useEffect(() => { useSkillStore.getState().trackAction("learn", "daysActive"); }, []);

  const location = useLocation();
  const [activeTab, setActiveTab] = useState<TabId>("basics");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isDesktopTablist, setIsDesktopTablist] = useState(
    () => window.matchMedia(LEARN_DESKTOP_MEDIA_QUERY).matches,
  );
  const level = useSkillLevel("learn");
  const selectedDoc = useMemo(() => getSelectedDoc(location.state), [location.state]);

  useEffect(() => {
    const mediaQuery = window.matchMedia(LEARN_DESKTOP_MEDIA_QUERY);
    const handleChange = (event: MediaQueryListEvent) => {
      setIsDesktopTablist(event.matches);
    };
    setIsDesktopTablist(mediaQuery.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (selectedDoc) setActiveTab("resources");
  }, [selectedDoc]);

  // Density adaptation — beginner sees fewer sidebar items
  // Beginner: basics + glossary prominently (guided lesson list)
  // Intermediate: all sections
  // Advanced: all sections
  const visibleTabIds: TabId[] = (() => {
    if (level === "beginner") {
      return selectedDoc
        ? ["basics", "glossary", "paper", "resources"]
        : ["basics", "glossary", "paper"];
    }
    return ["basics", "glossary", "strategies", "paper", "resources"];
  })();

  const visibleTabs = TABS.filter((t) => visibleTabIds.includes(t.id));
  const tablistRef = useRef<HTMLDivElement>(null);

  // Roving tabindex: arrow keys follow tablist orientation
  const handleTablistKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      const previousKey = isDesktopTablist ? "ArrowUp" : "ArrowLeft";
      const nextKey = isDesktopTablist ? "ArrowDown" : "ArrowRight";
      if (e.key !== previousKey && e.key !== nextKey) return;
      e.preventDefault();
      const tabs = tablistRef.current?.querySelectorAll<HTMLButtonElement>("[role='tab']");
      if (!tabs || tabs.length === 0) return;
      const idx = Array.from(tabs).indexOf(document.activeElement as HTMLButtonElement);
      const next =
        e.key === nextKey
          ? (idx + 1) % tabs.length
          : (idx - 1 + tabs.length) % tabs.length;
      const nextTab = tabs[next];
      nextTab?.focus();
      const tabId = visibleTabs[next]?.id;
      if (tabId) setActiveTab(tabId);
    },
    [isDesktopTablist, visibleTabs],
  );

  const tabContent = useMemo<Record<TabId, React.ReactNode>>(() => ({
    basics:     <BasicsTab />,
    glossary:   <GlossaryTab />,
    strategies: <StrategiesTab />,
    paper:      <PaperTradingTab />,
    resources:  <ResourceHubTab selectedDoc={selectedDoc} />,
  }), [selectedDoc]);

  const desktopCollapsed = isDesktopTablist && sidebarCollapsed;

  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden">
      {/* Header */}
      <div className="min-w-0 border-b border-border-default bg-surface-card/80 px-4 py-4 backdrop-blur-sm sm:px-6" data-tour-target="course-list">
          <div className="flex min-w-0 items-center gap-3">
            <GraduationCap className="h-6 w-6 shrink-0 text-accent" />
            <div className="min-w-0">
              <h1 className="font-heading break-words font-bold text-lg text-text-primary">
                {level === "beginner" ? "Getting Started" : "Learning Center"}
              </h1>
              <p className="break-words text-xxs text-text-muted">
                {level === "beginner"
                  ? "Learn market basics one lesson at a time"
                  : "Market concepts, Practice workflows, and project resources"}
              </p>
            </div>
          </div>
      </div>

      <div
        data-testid="learn-body"
        className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden md:flex-row"
      >
        {/* Section tabs: stacked/wrapping rail on narrow viewports, collapsible column on desktop */}
        <motion.div
          data-testid="learn-sidebar"
          animate={isDesktopTablist ? { width: sidebarCollapsed ? 48 : 224 } : { width: "100%" }}
          transition={{ duration: motionConfig.duration.normal, ease: motionConfig.ease.enter }}
          className="flex w-full min-w-0 flex-col border-b border-border-default bg-surface-card md:border-b-0 md:border-r md:shrink-0"
        >
          {/* Collapse toggle — desktop column only */}
          <div className={`hidden py-2 md:flex ${sidebarCollapsed ? "justify-center" : "justify-end px-2"}`}>
            <button
              type="button"
              onClick={() => setSidebarCollapsed((v) => !v)}
              title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-expanded={!sidebarCollapsed}
              className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-base hover:text-text-primary"
            >
              {sidebarCollapsed ? (
                <PanelLeftOpen className="h-4 w-4" />
              ) : (
                <PanelLeftClose className="h-4 w-4" />
              )}
            </button>
          </div>

          {/* Nav items — filtered by skill level */}
          <nav aria-label="Learning sections" className="min-w-0 md:flex-1 md:overflow-y-auto" data-tour-target="glossary">
            <div
              ref={tablistRef}
              role="tablist"
              aria-orientation={isDesktopTablist ? "vertical" : "horizontal"}
              className="flex min-w-0 flex-row flex-wrap md:flex-col"
              onKeyDown={handleTablistKeyDown}
            >
              {visibleTabs.map((tab) => (
                <SidebarItem
                  key={tab.id}
                  tab={tab}
                  isActive={activeTab === tab.id}
                  collapsed={desktopCollapsed}
                  onClick={() => setActiveTab(tab.id)}
                />
              ))}
            </div>
          </nav>
        </motion.div>

        {/* Content area — plain overflow-y pane so Radix ScrollArea cannot pin a min-content width */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          <div role="tabpanel" id={`learn-tabpanel-${activeTab}`} aria-labelledby={`learn-tab-${activeTab}`} className="mx-auto min-w-0 max-w-4xl p-4 sm:p-6">
            <TabTransition tabKey={activeTab}>
              {tabContent[activeTab]}
            </TabTransition>
          </div>
        </div>
      </div>

      {/* Guided tour — beginner only, first visit */}
      {level === "beginner" && (
        <SpotlightTour
          tourId="learn-beginner"
          steps={TOUR_DEFINITIONS["learn-beginner"] ?? []}
        />
      )}
    </div>
  );
}
