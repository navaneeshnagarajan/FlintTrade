/**
 * ShareholdingTab.tsx
 *
 * Shareholding pattern viewer + financial summary + corporate announcements.
 *
 * Data flow:
 *   Symbol input → GET /ft-api/api/v1/screener/shareholding?symbol=X
 *   → TanStack Query (10 min stale)
 *   → stacked bar chart (quarterly promoter/FII/DII/Public trend)
 *   → financial summary cards (Revenue, Net Profit, ROE, ROCE, D/E, P/E)
 *   → corporate announcements list (last 30 days)
 *
 * Accessibility:
 *   - Chart bars carry aria-label with percentage value
 *   - Announcement list uses <ul>/<li> semantics
 *   - Search input labelled; loading state uses role="status"
 *   - Colour coding supplemented by text labels (not colour-only)
 */

import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { FlintStackedBarChart, type FlintStackedBarSeries } from "@flinttrade/design-system";
import {
  AlertCircle,
  Building2,
  ExternalLink,
  RefreshCw,
  Search,
  TrendingUp,
  X,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";
import {
  getShareholding,
  type ShareholdingResponse,
  type ShareholdingData,
  type FinancialSummary,
  type CorporateAnnouncement,
} from "@/services/ftApi";

// ─── Demo data ─────────────────────────────────────────────────────────────

const DEMO_RESPONSE: ShareholdingResponse = {
  is_sample_data: true,
  shareholding: {
    symbol: "RELIANCE",
    as_of_quarter: "Mar 2025",
    promoter_pct: 50.34,
    fii_pct: 20.15,
    dii_pct: 16.42,
    public_pct: 13.09,
    government_pct: 0.00,
    promoter_history: [
      { quarter: "Mar 2025", percentage: 50.34 },
      { quarter: "Dec 2024", percentage: 50.41 },
      { quarter: "Sep 2024", percentage: 50.48 },
      { quarter: "Jun 2024", percentage: 50.60 },
      { quarter: "Mar 2024", percentage: 50.68 },
    ],
    fii_history: [
      { quarter: "Mar 2025", percentage: 20.15 },
      { quarter: "Dec 2024", percentage: 20.42 },
      { quarter: "Sep 2024", percentage: 21.03 },
      { quarter: "Jun 2024", percentage: 21.58 },
      { quarter: "Mar 2024", percentage: 22.01 },
    ],
    dii_history: [
      { quarter: "Mar 2025", percentage: 16.42 },
      { quarter: "Dec 2024", percentage: 15.98 },
      { quarter: "Sep 2024", percentage: 15.44 },
      { quarter: "Jun 2024", percentage: 14.82 },
      { quarter: "Mar 2024", percentage: 14.24 },
    ],
    public_history: [
      { quarter: "Mar 2025", percentage: 13.09 },
      { quarter: "Dec 2024", percentage: 13.19 },
      { quarter: "Sep 2024", percentage: 13.05 },
      { quarter: "Jun 2024", percentage: 13.00 },
      { quarter: "Mar 2024", percentage: 13.07 },
    ],
  },
  financials: {
    symbol: "RELIANCE",
    revenue: 1000212,
    net_profit: 79020,
    operating_cash_flow: 156000,
    debt_to_equity: 0.44,
    roe: 9.8,
    roce: 11.2,
    pe_ratio: 24.3,
    market_cap: 1742000,
    book_value: 1260,
    annual_history: [
      { year: "Mar 2025", revenue: 1000212, net_profit: 79020, operating_cash_flow: 156000 },
      { year: "Mar 2024", revenue: 899133, net_profit: 69621, operating_cash_flow: 141000 },
      { year: "Mar 2023", revenue: 875028, net_profit: 66702, operating_cash_flow: 130000 },
    ],
  },
  announcements: [
    {
      symbol: "RELIANCE",
      date: "2025-04-08",
      category: "Board Meeting",
      headline: "Board Meeting to consider Q4 FY25 results on 25 April 2025",
      attachment_url: "",
    },
    {
      symbol: "RELIANCE",
      date: "2025-04-02",
      category: "Dividend",
      headline: "Record Date for Interim Dividend of ₹5 per share",
      attachment_url: "",
    },
    {
      symbol: "RELIANCE",
      date: "2025-03-28",
      category: "Acquisition",
      headline: "Acquisition of strategic stake in Altigreen Propulsion Labs",
      attachment_url: "",
    },
  ],
};

// ─── Holding category colours ─────────────────────────────────────────────────

const HOLDING_META: {
  key: keyof ShareholdingData;
  label: string;
  color: string;
}[] = [
  { key: "promoter_pct", label: "Promoter", color: "#6366f1" },
  { key: "fii_pct", label: "FII", color: "#22d3ee" },
  { key: "dii_pct", label: "DII", color: "#34d399" },
  { key: "public_pct", label: "Public", color: "#a78bfa" },
  { key: "government_pct", label: "Govt", color: "#fb923c" },
];

// ─── Financial summary cards ──────────────────────────────────────────────────

function FinancialCards({ fin }: { fin: FinancialSummary }) {
  const fmt = (v: number | null, prefix = "", suffix = "") => {
    if (v === null || v === undefined) return "—";
    if (Math.abs(v) >= 100000) return `${prefix}${(v / 100000).toFixed(1)}L Cr${suffix}`;
    if (Math.abs(v) >= 1000) return `${prefix}${(v / 1000).toFixed(1)}K Cr${suffix}`;
    return `${prefix}${v.toFixed(1)}${suffix}`;
  };

  const cards: { label: string; value: string; positive?: boolean }[] = [
    { label: "Revenue (Cr)", value: fmt(fin.revenue, "₹") },
    {
      label: "Net Profit (Cr)",
      value: fmt(fin.net_profit, "₹"),
      positive: fin.net_profit !== null ? fin.net_profit > 0 : undefined,
    },
    {
      label: "ROE",
      value: fin.roe !== null ? `${fin.roe.toFixed(1)}%` : "—",
      positive: fin.roe !== null ? fin.roe > 12 : undefined,
    },
    {
      label: "ROCE",
      value: fin.roce !== null ? `${fin.roce.toFixed(1)}%` : "—",
      positive: fin.roce !== null ? fin.roce > 12 : undefined,
    },
    {
      label: "D/E Ratio",
      value: fin.debt_to_equity !== null ? fin.debt_to_equity.toFixed(2) : "—",
      positive: fin.debt_to_equity !== null ? fin.debt_to_equity < 1 : undefined,
    },
    {
      label: "P/E Ratio",
      value: fin.pe_ratio !== null ? fin.pe_ratio.toFixed(1) : "—",
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-px bg-border-default rounded-lg overflow-hidden">
      {cards.map((c) => (
        <GlassCard key={c.label} className="rounded-none p-3 gap-0.5">
          <span className="text-xxs text-text-muted uppercase tracking-wider leading-none">{c.label}</span>
          <span
            className={cn(
              "text-base font-mono font-bold tabular-nums leading-tight",
              c.positive === true
                ? "text-profit"
                : c.positive === false
                  ? "text-loss"
                  : "text-text-primary",
            )}
          >
            {c.value}
          </span>
        </GlassCard>
      ))}
    </div>
  );
}

// ─── Announcements list ───────────────────────────────────────────────────────

function AnnouncementsList({ announcements }: { announcements: CorporateAnnouncement[] }) {
  if (announcements.length === 0) {
    return (
      <p className="text-xs text-text-muted py-4 text-center">No announcements in the last 30 days.</p>
    );
  }

  return (
    <ul className="space-y-2" aria-label="Corporate announcements">
      {announcements.map((ann, i) => (
        <li
          key={i}
          className="flex items-start gap-3 p-3 rounded-lg border border-border-default bg-surface-card hover:bg-surface-elevated transition-colors"
        >
          <Building2 className="size-4 text-text-muted shrink-0 mt-0.5" aria-hidden="true" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant="outline" className="text-xxs h-4 border-border-default text-text-muted shrink-0">
                {ann.category}
              </Badge>
              <span className="text-xxs text-text-disabled">{ann.date}</span>
            </div>
            <p className="text-xs text-text-secondary mt-0.5 leading-snug">{ann.headline}</p>
          </div>
          {ann.attachment_url && (
            <a
              href={ann.attachment_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-text-muted hover:text-accent shrink-0"
              aria-label={`Open attachment for: ${ann.headline}`}
            >
              <ExternalLink className="size-3.5" aria-hidden="true" />
            </a>
          )}
        </li>
      ))}
    </ul>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ShareholdingTab() {
  const [inputValue, setInputValue] = useState("");
  const [symbol, setSymbol] = useState<string | null>(null);

  const handleSearch = useCallback(() => {
    const s = inputValue.trim().toUpperCase();
    if (s) setSymbol(s);
  }, [inputValue]);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["shareholding", symbol],
    queryFn: () => getShareholding(symbol!),
    enabled: symbol !== null,
    staleTime: 10 * 60_000,
    retry: 1,
  });

  const isDemo = !symbol || isError || (!isLoading && data?.is_sample_data);
  const displayData: ShareholdingResponse = data ?? DEMO_RESPONSE;

  // Build chart series from history (align on quarters from promoter_history)
  const { quarters, chartSeries } = useMemo<{ quarters: string[]; chartSeries: FlintStackedBarSeries[] }>(() => {
    const shp = displayData.shareholding;
    const qs = shp.promoter_history.map((h) => h.quarter);

    const buildValues = (history: { quarter: string; percentage: number }[]) => {
      const map = Object.fromEntries(history.map((h) => [h.quarter, h.percentage]));
      return qs.map((q) => map[q] ?? 0);
    };

    const series = HOLDING_META
      .map((m) => {
        const histKey = m.key.replace("_pct", "_history") as keyof ShareholdingData;
        const history = (shp[histKey] ?? []) as { quarter: string; percentage: number }[];
        return {
          label: m.label,
          color: m.color,
          values: buildValues(history),
        };
      })
      .filter((s) => s.values.some((v) => v > 0));

    return { quarters: qs, chartSeries: series };
  }, [displayData]);

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div>
        <h3 className="font-heading font-semibold text-sm text-text-primary">Shareholding Pattern</h3>
        <p className="text-xs text-text-muted mt-0.5">
          Quarterly promoter/FII/DII/public breakdown, financials, and corporate announcements.
        </p>
      </div>

      {/* Symbol search */}
      <div className="flex gap-2">
        <div className="relative flex-1 max-w-64">
          <Search
            className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3 text-text-muted"
            aria-hidden="true"
          />
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Enter symbol e.g. RELIANCE"
            aria-label="Enter NSE/BSE symbol to look up shareholding"
            className="pl-7 pr-7 h-8 text-xs bg-surface-card border-border-default placeholder:text-text-muted"
          />
          {inputValue && (
            <button
              onClick={() => { setInputValue(""); setSymbol(null); }}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
              aria-label="Clear symbol"
            >
              <X className="size-3" aria-hidden="true" />
            </button>
          )}
        </div>
        <Button
          size="sm"
          onClick={handleSearch}
          disabled={!inputValue.trim() || isLoading}
          className="h-8 px-4 text-xs"
        >
          {isLoading ? (
            <RefreshCw className="size-3 animate-spin" aria-hidden="true" />
          ) : (
            <Search className="size-3 mr-1.5" aria-hidden="true" />
          )}
          {isLoading ? "Loading..." : "Fetch"}
        </Button>
        {symbol && !isLoading && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void refetch()}
            className="h-8 px-2 text-xs text-text-muted"
            aria-label="Refresh shareholding data"
          >
            <RefreshCw className="size-3" aria-hidden="true" />
          </Button>
        )}
      </div>

      {/* Error */}
      {isError && (
        <div className="flex items-center gap-2 text-loss text-xs p-3 rounded-lg border border-loss/30 bg-loss/5">
          <AlertCircle className="size-4 shrink-0" aria-hidden="true" />
          Could not fetch shareholding for {symbol}. Try a valid NSE symbol (e.g. RELIANCE, TCS).
        </div>
      )}

      {isDemo && !isError && <DemoBanner />}

      {/* Symbol + quarter badge */}
      <div className="flex items-center gap-2">
        <TrendingUp className="size-4 text-accent" aria-hidden="true" />
        <span className="font-mono font-bold text-sm text-text-primary">
          {displayData.shareholding.symbol}
        </span>
        <Badge variant="outline" className="text-xxs border-border-default text-text-muted h-5">
          As of {displayData.shareholding.as_of_quarter}
        </Badge>
        {isDemo && (
          <Badge variant="outline" className="text-xxs border-amber-400/40 text-amber-400 h-5">
            Sample data
          </Badge>
        )}
      </div>

      {/* Loading skeleton */}
      {isLoading && (
        <div
          className="space-y-3 animate-pulse"
          role="status"
          aria-label="Loading shareholding data"
          aria-live="polite"
        >
          <div className="h-32 rounded-lg bg-surface-card border border-border-default" />
          <div className="h-24 rounded-lg bg-surface-card border border-border-default" />
        </div>
      )}

      {!isLoading && (
        <>
          {/* Shareholding stacked bar chart */}
          <GlassCard className="p-4 space-y-4">
            <div>
              <h4 className="font-heading font-semibold text-xs text-text-primary">Quarterly Trend</h4>
              <p className="text-xs text-text-muted mt-0.5">
                Promoter: <strong className="text-text-primary">{displayData.shareholding.promoter_pct.toFixed(2)}%</strong>
                &ensp;FII: <strong className="text-text-primary">{displayData.shareholding.fii_pct.toFixed(2)}%</strong>
                &ensp;DII: <strong className="text-text-primary">{displayData.shareholding.dii_pct.toFixed(2)}%</strong>
                &ensp;Public: <strong className="text-text-primary">{displayData.shareholding.public_pct.toFixed(2)}%</strong>
              </p>
            </div>
            {quarters.length > 0 ? (
              <FlintStackedBarChart
                labels={quarters}
                series={chartSeries}
                ariaLabel="Shareholding trend — stacked bar chart"
              />
            ) : (
              <p className="text-xs text-text-muted">No quarterly history available.</p>
            )}
          </GlassCard>

          {/* Financial summary */}
          <div className="space-y-2">
            <h4 className="font-heading font-semibold text-xs text-text-primary">Financial Highlights</h4>
            <FinancialCards fin={displayData.financials} />
          </div>

          {/* Corporate announcements */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="font-heading font-semibold text-xs text-text-primary">
                Corporate Announcements
              </h4>
              <span className="text-xxs text-text-muted">Last 30 days</span>
            </div>
            <AnnouncementsList announcements={displayData.announcements} />
          </div>

          <p className="text-xs text-text-muted">
            Source: Screener.in (financials + shareholding), BSE API (announcements).
            {isDemo ? " Sample data shown — enter a symbol above to fetch live data." : ""}
          </p>
        </>
      )}
    </div>
  );
}

export default ShareholdingTab;
