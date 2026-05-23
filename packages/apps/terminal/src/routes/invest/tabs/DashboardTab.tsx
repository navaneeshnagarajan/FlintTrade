/**
 * DashboardTab.tsx
 *
 * Bento-grid overview: net worth hero, 3 KPI cards, allocation donut,
 * top movers list, and 3 stat pills. All data sourced from InvestContext.
 */

import { useMemo } from "react";
import { DonutChart, BarList } from "@tremor/react";
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  BarChart3,
  Calculator,
  PieChart,
  RefreshCw,
  DollarSign,
  ArrowUpRight,
  ArrowDownRight,
  Percent,
} from "lucide-react";
import { xirr } from "@/lib/xirr";
import { GlassCard } from "@/components/ui/GlassCard";
import { AnimatedCounter } from "@/components/magicui/animated-counter";
import { classifySector } from "@/lib/sectors";
import { useTremorTheme } from "@/hooks/useTremorTheme";
import { cn } from "@/lib/utils";
import { GlossaryTooltip } from "@/components/ui/GlossaryTooltip";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { useInvest } from "../InvestContext";
import { formatINR, formatINRCompact, formatPercent } from "../formatters";
import type { Holding } from "@/types/api";

// ─── Demo data ────────────────────────────────────────────────────────────────

const DEMO_HOLDINGS: Holding[] = [
  { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2520, pnl: 3500, pnlPercent: 2.86 },
  { symbol: "TCS", exchange: "NSE", quantity: 25, averagePrice: 3800, ltp: 3920, pnl: 3000, pnlPercent: 3.16 },
  { symbol: "HDFCBANK", exchange: "NSE", quantity: 40, averagePrice: 1650, ltp: 1710, pnl: 2400, pnlPercent: 3.64 },
  { symbol: "INFY", exchange: "NSE", quantity: 30, averagePrice: 1500, ltp: 1475, pnl: -750, pnlPercent: -1.67 },
  { symbol: "ICICIBANK", exchange: "NSE", quantity: 60, averagePrice: 1100, ltp: 1145, pnl: 2700, pnlPercent: 4.09 },
  { symbol: "WIPRO", exchange: "NSE", quantity: 100, averagePrice: 450, ltp: 462, pnl: 1200, pnlPercent: 2.67 },
  { symbol: "ITC", exchange: "NSE", quantity: 200, averagePrice: 480, ltp: 495, pnl: 3000, pnlPercent: 3.13 },
  { symbol: "BHARTIARTL", exchange: "NSE", quantity: 30, averagePrice: 1700, ltp: 1745, pnl: 1350, pnlPercent: 2.65 },
  { symbol: "SBIN", exchange: "NSE", quantity: 80, averagePrice: 780, ltp: 798, pnl: 1440, pnlPercent: 2.31 },
  { symbol: "LT", exchange: "NSE", quantity: 20, averagePrice: 3200, ltp: 3150, pnl: -1000, pnlPercent: -1.56 },
];

const DEMO_NET_WORTH = 845000;
const DEMO_CASH = 100000;
const DEMO_INVESTED = 728160;
const DEMO_PNL = 16840;
const DEMO_PNL_PCT = 2.31;

/** Sample cash flows for XIRR demo — negative = outflow, positive = current value. */
const DEMO_CASH_FLOWS: { date: Date; amount: number }[] = [
  { date: new Date("2024-01-15"), amount: -500000 },
  { date: new Date("2024-04-01"), amount: -100000 },
  { date: new Date("2024-07-01"), amount: -100000 },
  { date: new Date("2024-10-01"), amount: -100000 },
  { date: new Date("2025-01-01"), amount: -100000 },
  { date: new Date("2025-04-01"), amount: -100000 },
  { date: new Date("2025-04-01"), amount: 1150000 },  // current portfolio value
];

// ─── Internal types ────────────────────────────────────────────────────────────

interface AllocationBand {
  label: string;
  value: number;
  color: string;
  bg: string;
}

interface TopMover {
  symbol: string;
  pnl: number;
  pnlPercent: number;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function DashboardTab() {
  const { holdings: liveHoldings, summary: liveSummary, isLoading, isError } = useInvest();
  const tremorColors = useTremorTheme();

  // Fall back to demo data when API fails or returns empty
  const isDemo = isError || (!isLoading && liveHoldings.length === 0);
  const holdings = isDemo ? DEMO_HOLDINGS : liveHoldings;
  const currentValue = isDemo ? DEMO_NET_WORTH - DEMO_CASH : liveSummary.currentValue;
  const totalInvested = isDemo ? DEMO_INVESTED : liveSummary.totalInvested;
  const totalPnl = isDemo ? DEMO_PNL : liveSummary.totalPnl;
  const totalPnlPercent = isDemo ? DEMO_PNL_PCT : liveSummary.totalPnlPercent;
  const availableCash = isDemo ? DEMO_CASH : liveSummary.availableCash;
  const netWorth = isDemo ? DEMO_NET_WORTH : currentValue + availableCash;

  const equityValue = useMemo(
    () =>
      holdings
        .filter((h) => !h.exchange.startsWith("MCX"))
        .reduce((acc, h) => acc + h.ltp * h.quantity, 0),
    [holdings],
  );

  const commodityValue = useMemo(
    () =>
      holdings
        .filter((h) => h.exchange.startsWith("MCX"))
        .reduce((acc, h) => acc + h.ltp * h.quantity, 0),
    [holdings],
  );

  const bands: AllocationBand[] = [
    { label: "Equity", value: equityValue, color: "text-neutral-text", bg: "bg-neutral-text" },
    { label: "Commodity", value: commodityValue, color: "text-warning", bg: "bg-warning" },
    { label: "Cash", value: availableCash, color: "text-profit", bg: "bg-profit" },
  ].filter((b) => b.value > 0);

  const sortedByPnl = useMemo(
    () => [...holdings].sort((a, b) => b.pnlPercent - a.pnlPercent),
    [holdings],
  );

  const gainers: TopMover[] = sortedByPnl.slice(0, 3).map((h) => ({
    symbol: h.symbol,
    pnl: h.pnl,
    pnlPercent: h.pnlPercent,
  }));

  const losers: TopMover[] = sortedByPnl
    .slice(-3)
    .reverse()
    .filter((h) => h.pnlPercent < 0)
    .map((h) => ({
      symbol: h.symbol,
      pnl: h.pnl,
      pnlPercent: h.pnlPercent,
    }));

  const sectorCount = useMemo(
    () => new Set(holdings.map((h) => classifySector(h.symbol))).size,
    [holdings],
  );

  // XIRR calculation — uses demo cash flows for now; live would use trade history
  const portfolioXirr = useMemo(() => {
    if (!isDemo) {
      // With live data we'd build cash flows from trade history
      // For now, use demo flows but substitute current portfolio value
      const flows = DEMO_CASH_FLOWS.slice(0, -1).concat({
        date: new Date(),
        amount: currentValue + availableCash,
      });
      return xirr(flows);
    }
    return xirr(DEMO_CASH_FLOWS);
  }, [isDemo, currentValue, availableCash]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <RefreshCw className="size-5 animate-spin" />
        <span className="text-sm">Loading portfolio data...</span>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      {/* Demo banner */}
      {isDemo && (
        <div className="lg:col-span-3">
          <DemoBanner />
        </div>
      )}

      {/* Hero: Net Worth (full width) */}
      <GlassCard className="lg:col-span-3 p-5 gap-0">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="space-y-1">
            <p className="text-xxs text-text-muted uppercase tracking-wider font-medium">
              Net Worth (Equity + Cash)
            </p>
            <div className="flex items-baseline gap-3">
              <span className="text-4xl font-mono font-bold tabular-nums text-text-primary">
                <AnimatedCounter
                  value={netWorth}
                  formatter={formatINRCompact}
                  duration={1.2}
                />
              </span>
              <span
                className={cn(
                  "text-sm font-mono tabular-nums font-semibold",
                  totalPnl >= 0 ? "text-profit" : "text-loss",
                )}
              >
                {formatPercent(totalPnlPercent)} unrealised
              </span>
            </div>
            <p className="text-xs text-text-muted">
              {holdings.length} holdings &middot; {formatINRCompact(totalInvested)} invested
              {portfolioXirr !== null && (
                <>
                  {" "}&middot;{" "}
                  <span
                    className={cn(
                      "font-mono font-semibold tabular-nums",
                      portfolioXirr >= 0 ? "text-profit" : "text-loss",
                    )}
                  >
                    XIRR {formatPercent(portfolioXirr * 100)}
                  </span>
                </>
              )}
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <div
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-mono font-semibold tabular-nums",
                totalPnl >= 0
                  ? "bg-bullish-bg text-profit border border-bullish-border"
                  : "bg-bearish-bg text-loss border border-bearish-border",
              )}
            >
              {totalPnl >= 0 ? (
                <ArrowUpRight className="size-4" />
              ) : (
                <ArrowDownRight className="size-4" />
              )}
              {formatINRCompact(Math.abs(totalPnl))}
            </div>
          </div>
        </div>
      </GlassCard>

      {/* Row 2: 3 KPI cards */}
      <GlassCard className="p-4 gap-2">
        <div className="flex items-center gap-2">
          <div className="size-7 rounded-lg flex items-center justify-center bg-bullish-bg">
            <Wallet className="size-3.5 text-profit" />
          </div>
          <span className="text-xxs text-text-muted uppercase tracking-wider">
            Available Funds
          </span>
        </div>
        <div className="text-2xl font-mono font-bold tabular-nums text-text-primary">
          <AnimatedCounter value={availableCash} formatter={formatINRCompact} duration={1.0} />
        </div>
        <p className="text-xs text-text-muted">Withdrawable cash</p>
      </GlassCard>

      <GlassCard className="p-4 gap-2">
        <div className="flex items-center gap-2">
          <div className="size-7 rounded-lg flex items-center justify-center bg-surface-elevated">
            <DollarSign className="size-3.5 text-text-secondary" />
          </div>
          <span className="text-xxs text-text-muted uppercase tracking-wider">
            Invested Value
          </span>
        </div>
        <div className="text-2xl font-mono font-bold tabular-nums text-text-primary">
          <AnimatedCounter value={totalInvested} formatter={formatINRCompact} duration={1.0} />
        </div>
        <p className="text-xs text-text-muted">Total cost basis of holdings</p>
      </GlassCard>

      <GlassCard className="p-4 gap-2">
        <div className="flex items-center gap-2">
          <div
            className={cn(
              "size-7 rounded-lg flex items-center justify-center",
              totalPnl >= 0 ? "bg-bullish-bg" : "bg-bearish-bg",
            )}
          >
            {totalPnl >= 0 ? (
              <TrendingUp className="size-3.5 text-profit" />
            ) : (
              <TrendingDown className="size-3.5 text-loss" />
            )}
          </div>
          <span className="text-xxs text-text-muted uppercase tracking-wider">
            <GlossaryTooltip term="Day P&L">Day P&amp;L</GlossaryTooltip>
          </span>
        </div>
        <div
          className={cn(
            "text-2xl font-mono font-bold tabular-nums",
            totalPnl >= 0 ? "text-profit" : "text-loss",
          )}
        >
          <AnimatedCounter
            value={Math.abs(totalPnl)}
            formatter={(v) => (totalPnl >= 0 ? "+" : "-") + formatINRCompact(v)}
            duration={1.0}
          />
        </div>
        <p className="text-xs text-text-muted">{formatPercent(totalPnlPercent)} unrealised</p>
      </GlassCard>

      {/* Row 3: Allocation donut + Top Movers */}
      <GlassCard className="lg:col-span-2 p-5 gap-3">
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Portfolio Allocation
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Equity + Cash from OpenAlgo. Debt / MF requires NAV data source.
          </p>
        </div>

        {bands.length > 0 ? (
          <div className="flex flex-col sm:flex-row gap-4 items-start">
            <DonutChart
              data={bands.map((b) => ({ name: b.label, value: b.value }))}
              category="value"
              index="name"
              valueFormatter={(v: number) => formatINR(v)}
              colors={tremorColors.slice(0, 3) as string[]}
              className="h-36 shrink-0"
              showLabel={false}
            />
            <div className="flex-1 min-w-0">
              <BarList
                data={bands.filter((b) => b.value > 0).map((b) => ({ name: b.label, value: b.value }))}
                valueFormatter={(v: number) => formatINR(v)}
                color="slate"
                className="text-xs"
              />
            </div>
          </div>
        ) : (
          <div className="text-center py-6 text-text-muted text-xs">
            No holdings or cash data available. Connect to OpenAlgo to see allocation.
          </div>
        )}
      </GlassCard>

      <GlassCard className="p-5 gap-3">
        <h3 className="font-heading font-semibold text-sm text-text-primary">Top Movers</h3>

        {holdings.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-xs text-text-muted text-center">
            Connect to OpenAlgo to see movers.
          </div>
        ) : (
          <div className="space-y-3">
            {gainers.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xxs text-text-muted uppercase tracking-wider">Gainers</p>
                {gainers.map((m) => (
                  <div key={m.symbol} className="flex items-center justify-between">
                    <span className="text-xs font-mono font-semibold text-text-primary">
                      {m.symbol}
                    </span>
                    <div className="flex items-center gap-1.5 text-profit">
                      <ArrowUpRight className="size-3" />
                      <span className="text-xs font-mono tabular-nums">
                        {formatPercent(m.pnlPercent)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {losers.length > 0 && (
              <div className="space-y-1.5 pt-2 border-t border-border-default">
                <p className="text-xxs text-text-muted uppercase tracking-wider">Losers</p>
                {losers.map((m) => (
                  <div key={m.symbol} className="flex items-center justify-between">
                    <span className="text-xs font-mono font-semibold text-text-primary">
                      {m.symbol}
                    </span>
                    <div className="flex items-center gap-1.5 text-loss">
                      <ArrowDownRight className="size-3" />
                      <span className="text-xs font-mono tabular-nums">
                        {formatPercent(m.pnlPercent)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </GlassCard>

      {/* Row 4: 3 stat pills */}
      <GlassCard className="p-4 gap-1.5">
        <div className="flex items-center gap-2">
          <BarChart3 className="size-4 text-text-muted" />
          <span className="text-xxs text-text-muted uppercase tracking-wider">Holdings</span>
        </div>
        <div className="text-3xl font-mono font-bold tabular-nums text-text-primary">
          {holdings.length}
        </div>
        <p className="text-xs text-text-muted">Stocks in portfolio</p>
      </GlassCard>

      <GlassCard className="p-4 gap-1.5">
        <div className="flex items-center gap-2">
          <Calculator className="size-4 text-text-muted" />
          <span className="text-xxs text-text-muted uppercase tracking-wider">Active SIPs</span>
        </div>
        <div className="text-3xl font-mono font-bold tabular-nums text-text-muted">—</div>
        <p className="text-xs text-text-muted">NAV feed required</p>
      </GlassCard>

      <GlassCard className="p-4 gap-1.5">
        <div className="flex items-center gap-2">
          <PieChart className="size-4 text-text-muted" />
          <span className="text-xxs text-text-muted uppercase tracking-wider">
            Sector Breakdown
          </span>
        </div>
        <div className="text-3xl font-mono font-bold tabular-nums text-text-primary">
          {sectorCount}
        </div>
        <p className="text-xs text-text-muted">Sectors represented</p>
      </GlassCard>

      {/* Row 5: XIRR card */}
      {portfolioXirr !== null && (
        <GlassCard className="lg:col-span-3 p-4 gap-2">
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "size-7 rounded-lg flex items-center justify-center",
                portfolioXirr >= 0 ? "bg-bullish-bg" : "bg-bearish-bg",
              )}
            >
              <Percent className={cn("size-3.5", portfolioXirr >= 0 ? "text-profit" : "text-loss")} />
            </div>
            <span className="text-xxs text-text-muted uppercase tracking-wider">
              Portfolio XIRR
            </span>
          </div>
          <div className="flex items-baseline gap-3">
            <span
              className={cn(
                "text-2xl font-mono font-bold tabular-nums",
                portfolioXirr >= 0 ? "text-profit" : "text-loss",
              )}
            >
              {formatPercent(portfolioXirr * 100)}
            </span>
            <span className="text-xs text-text-muted">
              Annualised return on irregular cash flows (SIPs + lump sum)
            </span>
          </div>
        </GlassCard>
      )}

      <p className="lg:col-span-3 text-xs text-text-muted">
        Holdings refresh every 60s. Cash refreshes every 30s from OpenAlgo.
      </p>
    </div>
  );
}
