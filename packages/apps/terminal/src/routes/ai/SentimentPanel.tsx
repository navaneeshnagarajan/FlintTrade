/**
 * Market Sentiment Dashboard Panel
 *
 * Fetches a structured AI-generated market summary from the FlintTrade
 * backend (GET /ft-api/v1/ai/sentiment/summary) and renders:
 *   - Big sentiment score gauge (-10 to +10, red → amber → green)
 *   - Sentiment label badge
 *   - Index cards (value, change %, signal arrow)
 *   - Sector performance grid with outlook badges
 *   - FII/DII flow card
 *   - Key points bullet list
 *   - Risks (red) and Opportunities (green) cards
 *
 * Auto-refreshes every 5 minutes.
 */

import { useMemo } from "react";
import { motion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Eye,
  AlertCircle,
  Loader2,
  RefreshCw,
  AlertTriangle,
  Lightbulb,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  getMarketSentimentSummary,
  getTickerSentiments,
  type MarketSummary,
  type SentimentLabel,
  type IndexSignal,
  type IndexSnapshot,
  type SectorOutlook,
  type TickerSentiment,
} from "@/services/ftApi";
import { motionConfig } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

/** Maps sentiment score in [-10, +10] to a Tailwind text colour. */
function scoreToTextColour(score: number): string {
  if (score >= 3) return "text-profit";
  if (score <= -3) return "text-loss";
  return "text-warning";
}

/** Width percentage of the gauge needle — 0% = -10, 50% = 0, 100% = +10. */
function scoreToGaugePct(score: number): number {
  return ((score + 10) / 20) * 100;
}

function sentimentLabelBadgeClass(label: SentimentLabel): string {
  switch (label) {
    case "STRONGLY_BULLISH":
      return "bg-profit/20 text-profit border-profit/40";
    case "BULLISH":
      return "bg-bullish-bg text-profit border-profit/30";
    case "NEUTRAL":
      return "bg-atm-bg text-warning border-warning/30";
    case "BEARISH":
      return "bg-bearish-bg text-loss border-loss/30";
    case "STRONGLY_BEARISH":
      return "bg-loss/20 text-loss border-loss/40";
  }
}

function sentimentLabelText(label: SentimentLabel): string {
  return label.replace("_", " ").replace("_", " ");
}

// ---------------------------------------------------------------------------
// Index signal icon
// ---------------------------------------------------------------------------

function SignalIcon({ signal }: { signal: IndexSignal }) {
  switch (signal) {
    case "BUY":
      return <ArrowUpRight className="w-4 h-4 text-profit" aria-label="Buy signal" />;
    case "SELL":
      return <ArrowDownRight className="w-4 h-4 text-loss" aria-label="Sell signal" />;
    case "HOLD":
      return <Minus className="w-4 h-4 text-warning" aria-label="Hold signal" />;
    case "WATCH":
      return <Eye className="w-4 h-4 text-text-muted" aria-label="Watch signal" />;
  }
}

// ---------------------------------------------------------------------------
// Gauge component — score from -10 to +10
// ---------------------------------------------------------------------------

function SentimentGauge({ score }: { score: number }) {
  const pct = scoreToGaugePct(score);
  const textColour = scoreToTextColour(score);

  return (
    <div className="space-y-2" aria-label={`Sentiment score: ${score.toFixed(1)}`}>
      {/* Score label */}
      <div className="flex items-baseline justify-center gap-2">
        <span className={`text-5xl font-mono font-bold ${textColour}`}>
          {score >= 0 ? "+" : ""}
          {score.toFixed(1)}
        </span>
        <span className="text-sm text-text-muted">/ 10</span>
      </div>

      {/* Gradient track */}
      <div className="relative h-3 rounded-full overflow-hidden bg-gradient-to-r from-red-600 via-amber-500 to-green-500">
        {/* Needle / marker */}
        <motion.div
          className="absolute top-0 h-full w-1 bg-white shadow-lg rounded-full"
          initial={{ left: "50%" }}
          animate={{ left: `${pct}%` }}
          transition={{ type: "spring", stiffness: 120, damping: 18 }}
          style={{ transform: "translateX(-50%)" }}
        />
      </div>

      {/* Scale labels */}
      <div className="flex justify-between text-xxs text-text-muted font-mono">
        <span>-10</span>
        <span>0</span>
        <span>+10</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Index cards
// ---------------------------------------------------------------------------

function IndexCard({ index, i }: { index: IndexSnapshot; i: number }) {
  const changePositive = index.change_pct >= 0;
  const changeCls = changePositive ? "text-profit" : "text-loss";
  const ChangeTrend = changePositive ? TrendingUp : TrendingDown;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionConfig.stagger(i)}
    >
      <Card className="bg-surface-base border border-border-default rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-text-primary truncate">{index.name}</span>
          <SignalIcon signal={index.signal} />
        </div>
        <div className="flex items-end justify-between gap-2">
          <span className="text-base font-mono font-bold text-text-primary">
            {index.value.toLocaleString("en-IN")}
          </span>
          <div className={`flex items-center gap-0.5 ${changeCls}`}>
            <ChangeTrend className="w-3 h-3" />
            <span className="text-xs font-mono font-semibold">
              {changePositive ? "+" : ""}
              {index.change_pct.toFixed(2)}%
            </span>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Sector performance grid
// ---------------------------------------------------------------------------

function performanceBadgeClass(performance: string): string {
  const p = performance.toLowerCase();
  if (p.includes("outperform")) return "bg-bullish-bg text-profit border-profit/30";
  if (p.includes("underperform")) return "bg-bearish-bg text-loss border-loss/30";
  return "bg-atm-bg text-warning border-warning/30";
}

function SectorRow({ sector, i }: { sector: SectorOutlook; i: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={motionConfig.stagger(i)}
      className="flex items-start gap-3 py-2 border-b border-border-default last:border-0"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-xs font-semibold text-text-primary">{sector.name}</span>
          <Badge
            variant="outline"
            className={`text-xxs px-1.5 py-0 border rounded-full ${performanceBadgeClass(sector.performance)}`}
          >
            {sector.performance}
          </Badge>
        </div>
        <p className="text-xxs text-text-secondary leading-relaxed">{sector.outlook}</p>
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// FII/DII flow card
// ---------------------------------------------------------------------------

function FiiDiiCard({ flow }: { flow: MarketSummary["fii_dii_flow"] }) {
  const unavailable = /not connected|unavailable|placeholder/i.test(flow.interpretation);
  const fiiPositive = flow.fii_net >= 0;
  const diiPositive = flow.dii_net >= 0;

  function formatCrore(val: number): string {
    const abs = Math.abs(val);
    const sign = val >= 0 ? "+" : "-";
    if (abs >= 1000) {
      return `${sign}₹${(abs / 1000).toFixed(1)}K Cr`;
    }
    return `${sign}₹${abs.toFixed(0)} Cr`;
  }

  return (
    <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3">
      <h4 className="text-sm font-semibold text-text-primary">FII / DII Flows</h4>
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-surface-base border border-border-default rounded-lg p-3">
          <p className="text-xxs text-text-muted mb-1">FII Net</p>
          <p
            className={`text-sm font-mono font-bold ${unavailable ? "text-text-muted" : fiiPositive ? "text-profit" : "text-loss"}`}
          >
            {unavailable ? "Unavailable" : formatCrore(flow.fii_net)}
          </p>
        </div>
        <div className="bg-surface-base border border-border-default rounded-lg p-3">
          <p className="text-xxs text-text-muted mb-1">DII Net</p>
          <p
            className={`text-sm font-mono font-bold ${unavailable ? "text-text-muted" : diiPositive ? "text-profit" : "text-loss"}`}
          >
            {unavailable ? "Unavailable" : formatCrore(flow.dii_net)}
          </p>
        </div>
      </div>
      <p className="text-xs text-text-secondary leading-relaxed">{flow.interpretation}</p>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Ticker Sentiment Table
// ---------------------------------------------------------------------------

function tickerScoreColour(score: number): string {
  if (score >= 3) return "text-profit";
  if (score <= -3) return "text-loss";
  return "text-text-muted";
}

function tickerScoreBg(score: number): string {
  if (score >= 3) return "bg-profit/10";
  if (score <= -3) return "bg-loss/10";
  return "bg-surface-base";
}

function tickerLabelBadge(label: TickerSentiment["label"]): string {
  if (label === "positive") return "bg-bullish-bg text-profit border-profit/30";
  if (label === "negative") return "bg-bearish-bg text-loss border-loss/30";
  return "bg-surface-base text-text-muted border-border-default";
}

function TickerSentimentTable() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["ticker-sentiments"],
    queryFn: getTickerSentiments,
    refetchInterval: FIVE_MINUTES_MS,
    staleTime: FIVE_MINUTES_MS,
  });

  const tickers = data?.tickers ?? [];

  return (
    <Card className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-text-primary">Ticker Sentiment</h4>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          disabled={isLoading}
          aria-label="Refresh ticker sentiments"
          className="text-text-muted hover:text-text-primary gap-1.5 h-7 text-xs"
        >
          <RefreshCw className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-text-muted text-xs py-4 justify-center">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Loading ticker sentiments…
        </div>
      )}

      {isError && (
        <p className="text-xs text-loss flex items-center gap-1.5">
          <AlertCircle className="w-3.5 h-3.5" />
          Ticker sentiment unavailable.
        </p>
      )}

      {!isLoading && !isError && tickers.length === 0 && (
        <p className="text-xs text-text-muted text-center py-3">
          No ticker sentiment data available.
        </p>
      )}

      {tickers.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs" role="table" aria-label="Per-ticker sentiment scores">
            <thead>
              <tr className="border-b border-border-default text-left text-text-muted">
                <th className="py-1.5 pr-3 font-medium">Ticker</th>
                <th className="py-1.5 pr-3 font-medium text-right">Score</th>
                <th className="py-1.5 pr-3 font-medium">Label</th>
                <th className="py-1.5 font-medium">Key Factor</th>
              </tr>
            </thead>
            <tbody>
              {tickers.map((t, i) => (
                <motion.tr
                  key={t.ticker}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={motionConfig.stagger(i)}
                  className="border-b border-border-default last:border-0"
                >
                  <td className="py-2 pr-3 font-mono font-semibold text-text-primary">
                    {t.ticker}
                  </td>
                  <td className={`py-2 pr-3 text-right font-mono font-bold ${tickerScoreColour(t.score)}`}>
                    <span className={`inline-block px-1.5 py-0.5 rounded ${tickerScoreBg(t.score)}`}>
                      {t.score >= 0 ? "+" : ""}
                      {t.score.toFixed(1)}
                    </span>
                  </td>
                  <td className="py-2 pr-3">
                    <Badge
                      variant="outline"
                      className={`text-xxs px-1.5 py-0 border rounded-full ${tickerLabelBadge(t.label)}`}
                    >
                      {t.label}
                    </Badge>
                  </td>
                  <td className="py-2 text-text-secondary leading-relaxed max-w-50 truncate">
                    {t.key_factor}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const FIVE_MINUTES_MS = 5 * 60 * 1000;

export default function SentimentPanel() {
  const { data, isLoading, isError, refetch, dataUpdatedAt } = useQuery({
    queryKey: ["market-sentiment-summary"],
    queryFn: getMarketSentimentSummary,
    refetchInterval: FIVE_MINUTES_MS,
    staleTime: FIVE_MINUTES_MS,
  });

  const lastUpdated = useMemo(() => {
    if (!dataUpdatedAt) return null;
    return new Date(dataUpdatedAt).toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }, [dataUpdatedAt]);

  return (
    <div className="space-y-4" data-tour-target="ai-sentiment-dashboard">
      {/* Header card */}
      <Card className="bg-surface-card border border-border-default rounded-lg p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-heading font-semibold text-base text-text-primary">
            Market Sentiment Dashboard
          </h3>
          <div className="flex items-center gap-2">
            {lastUpdated && (
              <span className="text-xxs text-text-muted font-mono">{lastUpdated}</span>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => refetch()}
              disabled={isLoading}
              aria-label="Refresh sentiment data"
              className="text-text-muted hover:text-text-primary gap-1.5 h-7 text-xs"
            >
              <RefreshCw className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </div>
        <p className="text-xs text-text-secondary leading-relaxed">
          AI-generated structured market summary. Refreshes every 5 minutes.
        </p>
      </Card>

      {/* Loading state */}
      {isLoading && (
        <div className="flex flex-col items-center gap-3 py-10 text-text-muted">
          <Loader2 className="w-6 h-6 animate-spin" />
          <span className="text-sm">Generating market summary…</span>
        </div>
      )}

      {/* Unavailable state — honest "coming soon" rather than an error.
          The AI sentiment service is not yet enabled in this build (the
          endpoint is not wired / no LLM is configured), so the request
          fails closed. We degrade to a calm preview placeholder instead of
          surfacing a raw backend error. */}
      {isError && (
        <Card className="bg-surface-card border border-border-default rounded-lg p-5">
          <div className="flex items-start gap-3 text-text-secondary">
            <Eye className="w-4 h-4 shrink-0 mt-0.5 text-text-muted" />
            <div>
              <p className="text-sm font-semibold mb-1 text-text-primary">
                Market sentiment coming soon
              </p>
              <p className="text-xs text-text-muted">
                AI-generated market sentiment is not yet available in this build.
                Once the AI backend is enabled and an LLM is configured, the live
                dashboard will appear here.
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            className="mt-3 text-text-muted hover:text-text-primary text-xs"
          >
            Check again
          </Button>
        </Card>
      )}

      {/* Data loaded */}
      {data && (
        <motion.div
          className="space-y-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={motionConfig.transitions.tab}
        >
          {/* Sentiment score gauge + label */}
          <Card className="bg-surface-card border border-border-default rounded-lg p-5 space-y-4">
            <SentimentGauge score={data.sentiment_score} />
            <div className="flex justify-center">
              <Badge
                variant="outline"
                className={`text-sm font-bold px-4 py-1.5 border rounded-full ${sentimentLabelBadgeClass(data.market_sentiment)}`}
              >
                {sentimentLabelText(data.market_sentiment)}
              </Badge>
            </div>
          </Card>

          {/* Index cards */}
          {data.indices.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2 px-1">
                Indices
              </h4>
              <div className="grid grid-cols-2 gap-2">
                {data.indices.map((idx, i) => (
                  <IndexCard key={idx.name} index={idx} i={i} />
                ))}
              </div>
            </div>
          )}

          {/* Key points */}
          {data.key_points.length > 0 && (
            <Card className="bg-surface-card border border-border-default rounded-lg p-4">
              <h4 className="text-sm font-semibold text-text-primary mb-3">Key Points</h4>
              <ul className="space-y-2">
                {data.key_points.map((point, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                    <span className="shrink-0 w-4 h-4 flex items-center justify-center rounded-full bg-accent/20 text-accent text-xxs font-bold mt-0.5">
                      {i + 1}
                    </span>
                    <span className="leading-relaxed">{point}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* FII / DII flow */}
          <FiiDiiCard flow={data.fii_dii_flow} />

          {/* Per-ticker sentiment table */}
          <TickerSentimentTable />

          {/* Sector performance */}
          {data.sectors.length > 0 && (
            <Card className="bg-surface-card border border-border-default rounded-lg p-4">
              <h4 className="text-sm font-semibold text-text-primary mb-2">Sector Performance</h4>
              <div>
                {data.sectors.map((s, i) => (
                  <SectorRow key={s.name} sector={s} i={i} />
                ))}
              </div>
            </Card>
          )}

          {/* Risks */}
          {data.risks.length > 0 && (
            <Card className="bg-bearish-bg border border-loss/30 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="w-4 h-4 text-loss shrink-0" />
                <h4 className="text-sm font-semibold text-loss">Risks to Watch</h4>
              </div>
              <ul className="space-y-1.5">
                {data.risks.map((risk, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                    <span className="text-loss mt-0.5">•</span>
                    <span className="leading-relaxed">{risk}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* Opportunities */}
          {data.opportunities.length > 0 && (
            <Card className="bg-bullish-bg border border-profit/30 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <Lightbulb className="w-4 h-4 text-profit shrink-0" />
                <h4 className="text-sm font-semibold text-profit">Opportunities</h4>
              </div>
              <ul className="space-y-1.5">
                {data.opportunities.map((opp, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                    <span className="text-profit mt-0.5">•</span>
                    <span className="leading-relaxed">{opp}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </motion.div>
      )}
    </div>
  );
}
