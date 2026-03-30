/**
 * CompanySnapshot.tsx
 *
 * A card component showing key metrics for any stock in plain language.
 * Designed for casual investors who need "Explain like I'm 5" company analysis.
 *
 * Features:
 *   - Company name + sector + market cap tier (Large/Mid/Small)
 *   - Key ratios: PE, PB, ROE, ROCE, Dividend Yield
 *   - 52-week high/low with position indicator
 *   - Color-coded health indicators (green/amber/red)
 *   - One-line AI summary based on ratio analysis
 *
 * Data: Accepts StockFundamentals from useStockScan hook.
 */

import {
  TrendingUp,
  TrendingDown,
  Building2,
  CircleDot,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SnapshotData {
  symbol: string;
  name: string;
  sector: string;
  market_cap: number;
  pe_ratio: number;
  pb_ratio: number;
  roe: number;
  roce: number;
  dividend_yield: number;
  high_52w?: number;
  low_52w?: number;
  ltp?: number;
}

export type HealthLevel = "green" | "amber" | "red";

export interface RatioHealth {
  label: string;
  value: string;
  level: HealthLevel;
}

// ---------------------------------------------------------------------------
// Pure logic — exported for testing
// ---------------------------------------------------------------------------

/** Classify market cap tier. Thresholds in INR crore. */
export function getMarketCapTier(crore: number): "Large Cap" | "Mid Cap" | "Small Cap" {
  if (crore >= 50_000) return "Large Cap";
  if (crore >= 10_000) return "Mid Cap";
  return "Small Cap";
}

/** Assess PE ratio health. */
export function assessPE(pe: number): HealthLevel {
  if (pe <= 0) return "red"; // Negative earnings
  if (pe <= 20) return "green";
  if (pe <= 35) return "amber";
  return "red";
}

/** Assess PB ratio health. */
export function assessPB(pb: number): HealthLevel {
  if (pb <= 0) return "red";
  if (pb <= 3) return "green";
  if (pb <= 6) return "amber";
  return "red";
}

/** Assess ROE health. */
export function assessROE(roe: number): HealthLevel {
  if (roe >= 20) return "green";
  if (roe >= 12) return "amber";
  return "red";
}

/** Assess ROCE health. */
export function assessROCE(roce: number): HealthLevel {
  if (roce >= 20) return "green";
  if (roce >= 12) return "amber";
  return "red";
}

/** Assess dividend yield health. */
export function assessDividendYield(dy: number): HealthLevel {
  if (dy >= 3) return "green";
  if (dy >= 1) return "amber";
  return "red";
}

/** Calculate 52-week position as percentage (0 = at low, 100 = at high). */
export function calculate52WeekPosition(
  ltp: number,
  low: number,
  high: number,
): number {
  if (high <= low) return 50;
  const position = ((ltp - low) / (high - low)) * 100;
  return Math.max(0, Math.min(100, position));
}

/** Build all ratio health assessments. */
export function buildRatioHealthList(data: SnapshotData): RatioHealth[] {
  return [
    { label: "PE Ratio", value: data.pe_ratio > 0 ? data.pe_ratio.toFixed(1) : "N/A", level: assessPE(data.pe_ratio) },
    { label: "PB Ratio", value: data.pb_ratio > 0 ? data.pb_ratio.toFixed(1) : "N/A", level: assessPB(data.pb_ratio) },
    { label: "ROE", value: `${data.roe.toFixed(1)}%`, level: assessROE(data.roe) },
    { label: "ROCE", value: `${data.roce.toFixed(1)}%`, level: assessROCE(data.roce) },
    { label: "Div Yield", value: `${data.dividend_yield.toFixed(1)}%`, level: assessDividendYield(data.dividend_yield) },
  ];
}

/** Generate a plain-language summary based on ratio analysis. */
export function generateSummary(data: SnapshotData): string {
  const scores = {
    pe: assessPE(data.pe_ratio),
    pb: assessPB(data.pb_ratio),
    roe: assessROE(data.roe),
    roce: assessROCE(data.roce),
    dy: assessDividendYield(data.dividend_yield),
  };

  const greenCount = Object.values(scores).filter((s) => s === "green").length;
  const redCount = Object.values(scores).filter((s) => s === "red").length;

  // Valuation assessment
  const valuation =
    scores.pe === "green" && scores.pb === "green"
      ? "attractively valued"
      : scores.pe === "red" || scores.pb === "red"
        ? "appears expensive"
        : "fairly valued";

  // Quality assessment
  const quality =
    scores.roe === "green" && scores.roce === "green"
      ? "strong fundamentals"
      : scores.roe === "red" && scores.roce === "red"
        ? "weak fundamentals"
        : "moderate fundamentals";

  // Dividend assessment
  const dividend =
    scores.dy === "green"
      ? "good dividend payer"
      : scores.dy === "amber"
        ? "modest dividends"
        : "low dividends";

  // Overall sentiment
  if (greenCount >= 4) {
    return `${quality}, ${valuation}, ${dividend}. Looks solid overall.`;
  }
  if (redCount >= 3) {
    return `${quality}, ${valuation}, ${dividend}. Needs careful evaluation.`;
  }
  return `${quality}, ${valuation}, ${dividend}.`;
}

// ---------------------------------------------------------------------------
// Styling helpers
// ---------------------------------------------------------------------------

const HEALTH_TEXT_CLASSES: Record<HealthLevel, string> = {
  green: "text-profit",
  amber: "text-warning",
  red: "text-loss",
};

const TIER_CLASSES: Record<string, string> = {
  "Large Cap": "border-profit/30 text-profit",
  "Mid Cap": "border-warning/30 text-warning",
  "Small Cap": "border-loss/30 text-loss",
};

function formatMarketCapDisplay(crore: number): string {
  if (crore >= 100_000) {
    return `${(crore / 100_000).toFixed(1)}L Cr`;
  }
  return `${crore.toLocaleString("en-IN")} Cr`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface CompanySnapshotProps {
  data: SnapshotData;
  className?: string;
}

export function CompanySnapshot({ data, className }: CompanySnapshotProps) {
  const tier = getMarketCapTier(data.market_cap);
  const ratios = buildRatioHealthList(data);
  const summary = generateSummary(data);

  const has52Week =
    data.high_52w !== undefined &&
    data.low_52w !== undefined &&
    data.ltp !== undefined;

  const weekPos = has52Week
    ? calculate52WeekPosition(data.ltp!, data.low_52w!, data.high_52w!)
    : null;

  return (
    <GlassCard
      className={cn("p-4 gap-3", className)}
      aria-label={`Company snapshot for ${data.name}`}
    >
      {/* Header: Name + Sector + Tier */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Building2 className="size-4 text-text-muted shrink-0" aria-hidden="true" />
            <h4 className="font-heading font-semibold text-sm text-text-primary truncate">
              {data.name}
            </h4>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-mono text-xs text-text-muted">{data.symbol}</span>
            <Badge
              variant="outline"
              className="text-xxs border-border-default text-text-muted font-normal h-4 px-1.5"
            >
              {data.sector}
            </Badge>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <Badge
            variant="outline"
            className={cn("text-xxs font-medium h-4 px-1.5", TIER_CLASSES[tier])}
          >
            {tier}
          </Badge>
          <span className="font-mono text-xs text-text-muted tabular-nums">
            {formatMarketCapDisplay(data.market_cap)}
          </span>
        </div>
      </div>

      {/* Ratio grid with health indicators */}
      <div className="grid grid-cols-5 gap-2">
        {ratios.map((ratio) => (
          <div
            key={ratio.label}
            className="flex flex-col items-center gap-0.5 text-center"
          >
            <span className="text-xxs text-text-muted">{ratio.label}</span>
            <div className="flex items-center gap-1">
              <CircleDot
                className={cn("size-2.5 shrink-0", HEALTH_TEXT_CLASSES[ratio.level])}
                aria-hidden="true"
              />
              <span
                className={cn(
                  "font-mono text-xs tabular-nums font-semibold",
                  HEALTH_TEXT_CLASSES[ratio.level],
                )}
              >
                {ratio.value}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* 52-week range */}
      {has52Week && weekPos !== null && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xxs text-text-muted">
            <span className="flex items-center gap-1">
              <TrendingDown className="size-3" aria-hidden="true" />
              {data.low_52w!.toLocaleString("en-IN")}
            </span>
            <span className="text-xxs text-text-muted">52W Range</span>
            <span className="flex items-center gap-1">
              {data.high_52w!.toLocaleString("en-IN")}
              <TrendingUp className="size-3" aria-hidden="true" />
            </span>
          </div>
          <div className="relative h-1.5 rounded-full bg-surface-elevated overflow-hidden">
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-accent/40"
              style={{ width: `${weekPos}%` }}
            />
            <div
              className="absolute top-1/2 -translate-y-1/2 size-2.5 rounded-full bg-accent border border-surface-card"
              style={{ left: `${weekPos}%`, transform: `translateX(-50%) translateY(-50%)` }}
              aria-label={`Current price at ${weekPos.toFixed(0)}% of 52-week range`}
            />
          </div>
        </div>
      )}

      {/* AI Summary */}
      <div className="flex items-start gap-2 pt-1 border-t border-border-default">
        <div
          className="size-5 rounded-md flex items-center justify-center bg-accent/10 shrink-0 mt-0.5"
          aria-hidden="true"
        >
          <span className="text-xxs font-bold text-accent">AI</span>
        </div>
        <p className="text-xs text-text-secondary leading-relaxed">{summary}</p>
      </div>
    </GlassCard>
  );
}

export default CompanySnapshot;
