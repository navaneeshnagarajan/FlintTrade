/**
 * AI Strategy Suggestions Panel
 *
 * Recommends backtest strategies based on market conditions, user risk profile,
 * and preferred instruments. Bridges the gap: "No Indian platform offers
 * AI-powered strategy building."
 *
 * Rendered as an overlay section inside AIRoute alongside Chat/Signals/Sentiment/KB.
 */

import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Lightbulb,
  TrendingUp,
  TrendingDown,
  ArrowUpDown,
  Rocket,
  BarChart3,
  ShieldAlert,
  RefreshCw,
  AlertCircle,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useSettingsStore } from "@/stores/settingsStore";
import { motionConfig } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Market mood types
// ---------------------------------------------------------------------------

type MarketMood = "volatile" | "trending" | "range-bound";

interface MoodDef {
  id: MarketMood;
  label: string;
  icon: typeof TrendingUp;
  color: string;
  bgColor: string;
}

const MOODS: MoodDef[] = [
  {
    id: "volatile",
    label: "Volatile",
    icon: ArrowUpDown,
    color: "text-warning",
    bgColor: "bg-atm-bg",
  },
  {
    id: "trending",
    label: "Trending",
    icon: TrendingUp,
    color: "text-profit",
    bgColor: "bg-bullish-bg",
  },
  {
    id: "range-bound",
    label: "Sideways",
    icon: TrendingDown,
    color: "text-text-muted",
    bgColor: "bg-surface-base",
  },
];

// ---------------------------------------------------------------------------
// Strategy suggestion data
// ---------------------------------------------------------------------------

interface StrategySuggestion {
  name: string;
  registryKey: string;
  reason: string;
  winRate: number;
  returnPct: number;
  maxDD: number;
  category: string;
  moods: MarketMood[];
  riskLevel: "low" | "medium" | "high";
}

/**
 * Static recommendation pool. In production this would come from the AI
 * advisor backend; for now we use curated entries from the 101 backtest
 * strategies, tagged with the market moods they suit best.
 */
const SUGGESTION_POOL: StrategySuggestion[] = [
  // ── Volatile market ────────────────────────────────────────────────
  {
    name: "ATR Breakout",
    registryKey: "ATRBreakout",
    reason: "Capitalises on wide ranges during volatile sessions by entering breakouts confirmed by ATR expansion.",
    winRate: 58.2,
    returnPct: 72.3,
    maxDD: 12.1,
    category: "volatility",
    moods: ["volatile"],
    riskLevel: "high",
  },
  {
    name: "Indian Short Straddle",
    registryKey: "IndianShortStraddle",
    reason: "Sells ATM straddle to harvest elevated implied volatility premium with intraday adjustment rules.",
    winRate: 64.5,
    returnPct: 45.8,
    maxDD: 8.4,
    category: "options",
    moods: ["volatile"],
    riskLevel: "medium",
  },
  {
    name: "Bollinger Squeeze",
    registryKey: "BollingerSqueeze",
    reason: "Detects compression before expansion. Enters when bands tighten then break, ideal for volatility spikes.",
    winRate: 61.3,
    returnPct: 68.7,
    maxDD: 10.5,
    category: "volatility",
    moods: ["volatile"],
    riskLevel: "medium",
  },
  {
    name: "Range Expansion",
    registryKey: "RangeExpansion",
    reason: "Triggers on NR7 / inside-bar expansion patterns. Best when market swings between consolidation and breakout.",
    winRate: 56.8,
    returnPct: 54.2,
    maxDD: 11.8,
    category: "volatility",
    moods: ["volatile"],
    riskLevel: "high",
  },
  {
    name: "India VIX Regime",
    registryKey: "IndiaVIXRegime",
    reason: "Switches between trend-following and mean-reversion based on India VIX levels. Built for volatile NSE conditions.",
    winRate: 63.1,
    returnPct: 82.6,
    maxDD: 14.2,
    category: "volatility",
    moods: ["volatile"],
    riskLevel: "high",
  },

  // ── Trending market ────────────────────────────────────────────────
  {
    name: "Trend EMA Crossover",
    registryKey: "TrendEMACrossover",
    reason: "Classic multi-EMA trend strategy with confirmation filters. Rides directional moves with trailing stops.",
    winRate: 62.7,
    returnPct: 88.4,
    maxDD: 11.3,
    category: "trend",
    moods: ["trending"],
    riskLevel: "medium",
  },
  {
    name: "MTF Supertrend Confluence",
    registryKey: "MTFSupertrendConfluence",
    reason: "Aligns Supertrend across 3 timeframes for high-probability trend entries. Reduces false signals.",
    winRate: 67.4,
    returnPct: 95.2,
    maxDD: 9.7,
    category: "trend",
    moods: ["trending"],
    riskLevel: "medium",
  },
  {
    name: "Momentum RSI",
    registryKey: "RSIMomentum",
    reason: "Enters on RSI momentum shifts with trend-following bias. Works well in sustained directional moves.",
    winRate: 60.1,
    returnPct: 64.5,
    maxDD: 10.8,
    category: "momentum",
    moods: ["trending"],
    riskLevel: "medium",
  },
  {
    name: "Portfolio Momentum Rotation",
    registryKey: "PortfolioMomentumRotation",
    reason: "Rotates into strongest trending sectors. Systematic allocation to relative strength leaders.",
    winRate: 65.8,
    returnPct: 42.1,
    maxDD: 7.2,
    category: "portfolio",
    moods: ["trending"],
    riskLevel: "low",
  },
  {
    name: "Ichimoku Cloud",
    registryKey: "IchimokuCloud",
    reason: "Multi-signal trend system with cloud support/resistance. Filters entries using Kumo twist and Chikou span.",
    winRate: 59.6,
    returnPct: 76.3,
    maxDD: 13.1,
    category: "trend",
    moods: ["trending"],
    riskLevel: "medium",
  },

  // ── Range-bound / sideways ─────────────────────────────────────────
  {
    name: "Iron Condor Strategy",
    registryKey: "IronCondorStrategy",
    reason: "Sells wings in a range-bound market to collect premium. Defined risk with adjustable breakevens.",
    winRate: 71.2,
    returnPct: 38.5,
    maxDD: 5.6,
    category: "options",
    moods: ["range-bound"],
    riskLevel: "low",
  },
  {
    name: "VWAP Reversion",
    registryKey: "VWAPReversion",
    reason: "Mean-reverts to VWAP when price deviates in a sideways regime. High win rate in choppy markets.",
    winRate: 68.4,
    returnPct: 52.3,
    maxDD: 6.8,
    category: "mean_reversion",
    moods: ["range-bound"],
    riskLevel: "low",
  },
  {
    name: "Keltner Channel Reversion",
    registryKey: "KeltnerReversion",
    reason: "Fades moves to Keltner channel extremes. Profits from the predictable snap-back in range-bound regimes.",
    winRate: 66.9,
    returnPct: 48.7,
    maxDD: 7.3,
    category: "mean_reversion",
    moods: ["range-bound"],
    riskLevel: "low",
  },
  {
    name: "Z-Score Mean Reversion",
    registryKey: "ZScoreMeanReversion",
    reason: "Enters when z-score exceeds 2 standard deviations. Statistical edge in non-trending conditions.",
    winRate: 64.2,
    returnPct: 41.6,
    maxDD: 6.1,
    category: "mean_reversion",
    moods: ["range-bound"],
    riskLevel: "low",
  },
  {
    name: "Wheel Strategy",
    registryKey: "WheelStrategy",
    reason: "Sells cash-secured puts, then covered calls if assigned. Generates income in flat to mildly bullish markets.",
    winRate: 72.5,
    returnPct: 28.4,
    maxDD: 4.2,
    category: "options",
    moods: ["range-bound"],
    riskLevel: "low",
  },
];

// ---------------------------------------------------------------------------
// Risk-based filtering
// ---------------------------------------------------------------------------

function riskFromPersona(persona: string, experience: string): "low" | "medium" | "high" {
  if (persona === "beginner" || experience === "beginner") return "low";
  if (persona === "investor") return "medium";
  return "high";
}

function filterByRisk(
  suggestions: StrategySuggestion[],
  userRisk: "low" | "medium" | "high",
): StrategySuggestion[] {
  const riskOrder = { low: 0, medium: 1, high: 2 };
  const userLevel = riskOrder[userRisk];
  // Include strategies at or below the user's risk tolerance
  return suggestions.filter((s) => riskOrder[s.riskLevel] <= userLevel);
}

// ---------------------------------------------------------------------------
// Strategy card
// ---------------------------------------------------------------------------

function riskBadgeClass(risk: "low" | "medium" | "high"): string {
  if (risk === "low") return "bg-bullish-bg text-profit border-profit/30";
  if (risk === "medium") return "bg-atm-bg text-warning border-warning/30";
  return "bg-bearish-bg text-loss border-loss/30";
}

interface StrategyCardProps {
  suggestion: StrategySuggestion;
  index: number;
  onDeploy: (registryKey: string) => void;
}

function StrategyCard({ suggestion, index, onDeploy }: StrategyCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionConfig.stagger(index)}
    >
      <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <h4 className="text-sm font-semibold text-text-primary truncate">
              {suggestion.name}
            </h4>
            <div className="flex items-center gap-1.5 mt-1">
              <Badge
                variant="outline"
                className="text-xxs font-mono px-1.5 py-0 border-border-default text-text-muted"
              >
                {suggestion.category}
              </Badge>
              <Badge
                className={`text-xxs px-1.5 py-0 border rounded-full ${riskBadgeClass(suggestion.riskLevel)}`}
              >
                {suggestion.riskLevel} risk
              </Badge>
            </div>
          </div>
          <Lightbulb className="w-4 h-4 text-accent shrink-0 mt-0.5" />
        </div>

        {/* Reason */}
        <p className="text-xs text-text-secondary leading-relaxed">
          {suggestion.reason}
        </p>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-surface-base border border-border-default rounded px-2 py-1.5 text-center">
            <p className="text-xxs text-text-muted">Win Rate</p>
            <p className="text-xs font-mono font-bold text-profit">
              {suggestion.winRate.toFixed(1)}%
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded px-2 py-1.5 text-center">
            <p className="text-xxs text-text-muted">Return</p>
            <p className="text-xs font-mono font-bold text-text-primary">
              {suggestion.returnPct.toFixed(1)}%
            </p>
          </div>
          <div className="bg-surface-base border border-border-default rounded px-2 py-1.5 text-center">
            <p className="text-xxs text-text-muted">Max DD</p>
            <p className="text-xs font-mono font-bold text-loss">
              {suggestion.maxDD.toFixed(1)}%
            </p>
          </div>
        </div>

        {/* Deploy button */}
        <Button
          variant="outline"
          size="sm"
          className="w-full gap-1.5 text-xs"
          onClick={() => onDeploy(suggestion.registryKey)}
        >
          <Rocket className="w-3.5 h-3.5" />
          Deploy to Strategy Lab
        </Button>
      </Card>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function AISuggestionsPanel() {
  const navigate = useNavigate();
  const persona = useSettingsStore((s) => s.persona);
  const experience = useSettingsStore((s) => s.experience);

  const [mood, setMood] = useState<MarketMood>("volatile");

  const userRisk = useMemo(() => riskFromPersona(persona, experience), [persona, experience]);

  const suggestions = useMemo(() => {
    const moodFiltered = SUGGESTION_POOL.filter((s) => s.moods.includes(mood));
    const riskFiltered = filterByRisk(moodFiltered, userRisk);
    // Return up to 5 suggestions
    return riskFiltered.slice(0, 5);
  }, [mood, userRisk]);

  function handleDeploy(registryKey: string) {
    navigate(`/lab?strategy=${registryKey}`);
  }

  function handleRefresh() {
    // Cycle to next mood for demo
    const moodIds = MOODS.map((m) => m.id);
    const idx = moodIds.indexOf(mood);
    setMood(moodIds[(idx + 1) % moodIds.length]);
  }

  return (
    <div className="space-y-4">
      {/* Intro card */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-heading font-semibold text-base text-text-primary">
            AI Strategy Suggestions
          </h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRefresh}
            className="text-text-muted hover:text-text-primary gap-1.5 h-7 text-xs"
          >
            <RefreshCw className="w-3 h-3" />
            Refresh
          </Button>
        </div>
        <p className="text-xs text-text-secondary leading-relaxed">
          Strategy recommendations based on current market conditions and your risk profile
          ({userRisk} risk). Powered by {SUGGESTION_POOL.length} backtest strategies.
        </p>
      </Card>

      {/* Market mood selector */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <div className="flex items-center gap-2 mb-3">
          <BarChart3 className="w-4 h-4 text-accent" />
          <h4 className="text-sm font-semibold text-text-primary">Market Mood</h4>
        </div>
        <div className="flex gap-2">
          {MOODS.map((m) => {
            const Icon = m.icon;
            const isActive = mood === m.id;
            return (
              <button
                key={m.id}
                onClick={() => setMood(m.id)}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all border ${
                  isActive
                    ? `${m.bgColor} ${m.color} border-current`
                    : "bg-surface-base border-border-default text-text-muted hover:text-text-secondary"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {m.label}
              </button>
            );
          })}
        </div>
      </Card>

      {/* Risk profile indicator */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-4">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-text-muted" />
          <span className="text-xs text-text-secondary">
            Your risk profile:{" "}
            <Badge className={`text-xxs ${riskBadgeClass(userRisk)}`}>
              {userRisk}
            </Badge>
          </span>
          <span className="text-xxs text-text-muted ml-auto">
            Based on persona &amp; experience
          </span>
        </div>
      </Card>

      {/* Disclaimer */}
      <div className="flex items-center gap-2 px-3 py-2 rounded border border-amber-500/30 bg-amber-500/10 text-amber-400 text-xs">
        <AlertCircle size={14} />
        <span>Performance figures are illustrative estimates, not actual backtest results.</span>
      </div>

      {/* Suggestion cards */}
      {suggestions.length === 0 ? (
        <Card className="bg-surface-card border border-border-default rounded-lg p-6 text-center">
          <Lightbulb className="w-7 h-7 text-text-muted mx-auto mb-2" />
          <p className="text-sm text-text-secondary">
            No strategies match this mood + risk combination.
          </p>
          <p className="text-xs text-text-muted mt-1">
            Try adjusting the market mood or update your experience in Settings.
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          {suggestions.map((s, idx) => (
            <StrategyCard
              key={s.registryKey}
              suggestion={s}
              index={idx}
              onDeploy={handleDeploy}
            />
          ))}
        </div>
      )}
    </div>
  );
}
