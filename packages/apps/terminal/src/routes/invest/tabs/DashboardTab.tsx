/**
 * DashboardTab.tsx
 *
 * Bento-grid overview: net worth hero, 3 KPI cards, allocation donut,
 * top movers list, and 3 stat pills. All data sourced from InvestContext.
 */

import { useMemo } from "react";
import { FlintDonutBreakdown, FlintRankedBarList } from "@flinttrade/design-system";
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
import { cn } from "@/lib/utils";
import { GlossaryTooltip } from "@/components/ui/GlossaryTooltip";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { ExampleLabel } from "@/components/data/ExampleLabel";
import {
  accountNetWorth,
  accountNetWorthAccessibleName,
  formatAccountNetWorth,
  NET_WORTH_LABEL,
  netWorthFigureTitle,
} from "@/lib/accountNetWorth";
import { useModeStore } from "@/stores/modeStore";
import { useInvest } from "../InvestContext";
import { formatINR, formatINRCompact, formatPercent } from "../formatters";
import { maskValue, VALUE_MASK } from "@/lib/formatters";
import { useValueVisibilityStore } from "@/stores/valueVisibilityStore";

// ─── Sample XIRR cash flows (Explore / Practice with no broker) ──────────────

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
  hex: string;
}

interface TopMover {
  symbol: string;
  pnl: number;
  pnlPercent: number;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function DashboardTab() {
  const {
    holdings,
    summary: liveSummary,
    isLoading,
    isError,
    isSampleData,
    positionBookReady,
  } = useInvest();
  const isPractice = useModeStore((s) => s.mode === "practice");

  // Count and rows come from InvestContext only — never a local sample
  // overlay that would disagree with the header badge (FT-TRADE-010).
  const isDemo = Boolean(isSampleData);
  const currentValue = liveSummary.currentValue;
  const totalInvested = liveSummary.totalInvested;
  const totalPnl = liveSummary.totalPnl;
  const totalPnlPercent = liveSummary.totalPnlPercent;
  const availableCash = liveSummary.availableCash;
  const ledgerCash = liveSummary.ledgerCash ?? availableCash;
  // Same helper as Home. A sample book is labelled Example; a Practice
  // snapshot never mixes the demo portfolio into this figure.
  const netWorth = typeof liveSummary.netWorth === "number"
    ? liveSummary.netWorth
    : accountNetWorth(holdings, availableCash);
  const netWorthPublished = !isError && positionBookReady !== false;

  const valuesHidden = useValueVisibilityStore((s) => s.hidden);
  // Wrap the compact-INR formatter so masked mode hides the figure everywhere it
  // is passed to a counter/list without changing each call site's shape.
  const money = (v: number) => maskValue(formatINRCompact(v), valuesHidden);
  const approximate = liveSummary.approximateNetWorth === true;
  const fallbackSymbols = liveSummary.fallbackSymbols ?? [];
  const figureTitle = netWorthFigureTitle(approximate, fallbackSymbols);
  const netWorthLabel = (v: number) => maskValue(formatAccountNetWorth(v, approximate), valuesHidden);

  const positionValue = liveSummary.positionValue ?? 0;

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
    { label: "Equity", value: equityValue, color: "text-neutral-text", bg: "bg-neutral-text", hex: "#60a5fa" },
    { label: "Positions", value: positionValue, color: "text-profit", bg: "bg-profit", hex: "#22c55e" },
    { label: "Commodity", value: commodityValue, color: "text-warning", bg: "bg-warning", hex: "#fbbf24" },
    { label: "Cash", value: ledgerCash, color: "text-profit", bg: "bg-profit", hex: "#34d399" },
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

  // XIRR is computed from cash flows. An empty book has no return to show.
  const portfolioXirr = useMemo(() => {
    if (holdings.length === 0) return null;
    if (!isDemo) {
      const flows = DEMO_CASH_FLOWS.slice(0, -1).concat({
        date: new Date(),
        amount: currentValue + availableCash,
      });
      return xirr(flows);
    }
    return xirr(DEMO_CASH_FLOWS);
  }, [holdings.length, isDemo, currentValue, availableCash]);

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
            <p
              className="text-xxs text-text-muted uppercase tracking-wider font-medium flex items-center gap-1.5"
              title={figureTitle}
            >
              <GlossaryTooltip term="Net Worth">{NET_WORTH_LABEL}</GlossaryTooltip>
              {isDemo && <ExampleLabel testId="invest-net-worth-example" />}
            </p>
            <div className="flex items-baseline gap-3">
              <span
                className="text-4xl font-mono font-bold tabular-nums text-text-primary"
                data-testid="invest-net-worth"
                title={figureTitle}
                aria-label={
                  netWorthPublished && approximate && !valuesHidden
                    ? accountNetWorthAccessibleName(netWorth)
                    : undefined
                }
                {...(netWorthPublished ? { "data-value": netWorth } : {})}
              >
                {netWorthPublished ? (
                  <AnimatedCounter
                    value={netWorth}
                    formatter={netWorthLabel}
                    accessibleLabel={
                      approximate && !valuesHidden ? accountNetWorthAccessibleName(netWorth) : undefined
                    }
                    duration={1.2}
                  />
                ) : "—"}
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
              {holdings.length} holdings &middot; {money(totalInvested)} invested
              {" "}&middot;{" "}
              <span
                data-testid="invest-xirr-subline"
                className={cn(
                  "font-mono font-semibold tabular-nums",
                  portfolioXirr === null
                    ? "text-text-muted"
                    : portfolioXirr >= 0 ? "text-profit" : "text-loss",
                )}
              >
                {portfolioXirr === null ? "XIRR —" : `XIRR ${formatPercent(portfolioXirr * 100)}`}
              </span>
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
              {money(Math.abs(totalPnl))}
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
          <span className="text-xxs text-text-muted uppercase tracking-wider inline-flex items-center gap-1.5">
            Available Funds
            {isDemo && <ExampleLabel testId="invest-funds-example" />}
          </span>
        </div>
        <div className="text-2xl font-mono font-bold tabular-nums text-text-primary" data-testid="invest-available-funds">
          <AnimatedCounter value={availableCash} formatter={netWorthLabel} duration={1.0} />
        </div>
        <p className="text-xs text-text-muted">Withdrawable cash</p>
      </GlassCard>

      <GlassCard className="p-4 gap-2">
        <div className="flex items-center gap-2">
          <div className="size-7 rounded-lg flex items-center justify-center bg-surface-elevated">
            <DollarSign className="size-3.5 text-text-secondary" />
          </div>
          <span className="text-xxs text-text-muted uppercase tracking-wider inline-flex items-center gap-1.5">
            Invested Value
            {isDemo && <ExampleLabel testId="invest-invested-example" />}
          </span>
        </div>
        <div className="text-2xl font-mono font-bold tabular-nums text-text-primary">
          <AnimatedCounter value={totalInvested} formatter={money} duration={1.0} />
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
          <span className="text-xxs text-text-muted uppercase tracking-wider inline-flex items-center gap-1.5">
            <GlossaryTooltip term="Day P&L">Day P&amp;L</GlossaryTooltip>
            {isDemo && <ExampleLabel testId="invest-pnl-example" />}
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
            formatter={(v) => (valuesHidden ? VALUE_MASK : (totalPnl >= 0 ? "+" : "-") + formatINRCompact(v))}
            duration={1.0}
          />
        </div>
        <p className="text-xs text-text-muted">{formatPercent(totalPnlPercent)} unrealised</p>
      </GlassCard>

      {/* Row 3: Allocation donut + Top Movers */}
      <GlassCard className="lg:col-span-2 p-5 gap-3">
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary inline-flex items-center gap-1.5">
            Portfolio Allocation
            {isDemo && <ExampleLabel testId="invest-allocation-example" />}
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            {isPractice
              ? "Practice account. Debt / MF requires NAV data source."
              : "Equity + Cash from your connected broker. Debt / MF requires NAV data source."}
          </p>
        </div>

        {bands.length > 0 ? (
          <div className="flex flex-col sm:flex-row gap-4 items-start">
            <FlintDonutBreakdown
              ariaLabel="Portfolio allocation donut"
              slices={bands.map((b) => ({ label: b.label, value: b.value, color: b.hex }))}
              className="size-36"
            />
            <div className="flex-1 min-w-0">
              <FlintRankedBarList
                ariaLabel="Portfolio allocation values"
                entries={bands.filter((b) => b.value > 0).map((b) => ({
                  label: b.label,
                  value: b.value,
                  color: b.hex,
                }))}
                valueFormatter={(v: number) => formatINR(v)}
                className="text-xs"
              />
            </div>
          </div>
        ) : (
          <div className="text-center py-6 text-text-muted text-xs">
            {isPractice
              ? "No holdings or cash in this account yet."
              : "No holdings or cash data available. Connect a broker to see allocation."}
          </div>
        )}
      </GlassCard>

      <GlassCard className="p-5 gap-3">
        <h3 className="font-heading font-semibold text-sm text-text-primary inline-flex items-center gap-1.5">
          Top Movers
          {isDemo && <ExampleLabel testId="invest-movers-example" />}
        </h3>

        {holdings.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-xs text-text-muted text-center">
            {isPractice ? "No movers in this account yet." : "Connect a broker to see movers."}
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
          <span className="text-xxs text-text-muted uppercase tracking-wider inline-flex items-center gap-1.5">
            Holdings
            {isDemo && <ExampleLabel testId="invest-holdings-count-example" />}
          </span>
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
          <span className="text-xxs text-text-muted uppercase tracking-wider inline-flex items-center gap-1.5">
            Sector Breakdown
            {isDemo && <ExampleLabel testId="invest-sector-count-example" />}
          </span>
        </div>
        <div className="text-3xl font-mono font-bold tabular-nums text-text-primary">
          {sectorCount}
        </div>
        <p className="text-xs text-text-muted">Sectors represented</p>
      </GlassCard>

      <GlassCard className="lg:col-span-3 p-4 gap-2">
        <div className="flex items-center gap-2">
          <div
            className={cn(
              "size-7 rounded-lg flex items-center justify-center",
              portfolioXirr === null
                ? "bg-surface-elevated"
                : portfolioXirr >= 0 ? "bg-bullish-bg" : "bg-bearish-bg",
            )}
          >
            <Percent className={cn(
              "size-3.5",
              portfolioXirr === null
                ? "text-text-muted"
                : portfolioXirr >= 0 ? "text-profit" : "text-loss",
            )} />
          </div>
          <span className="text-xxs text-text-muted uppercase tracking-wider">
            Portfolio XIRR
          </span>
        </div>
        <div className="flex items-baseline gap-3">
          <span
            data-testid="invest-xirr"
            className={cn(
              "text-2xl font-mono font-bold tabular-nums",
              portfolioXirr === null
                ? "text-text-muted"
                : portfolioXirr >= 0 ? "text-profit" : "text-loss",
            )}
          >
            {portfolioXirr === null ? "—" : formatPercent(portfolioXirr * 100)}
          </span>
          <span className="text-xs text-text-muted">
            Annualised return on irregular cash flows (SIPs + lump sum)
          </span>
        </div>
      </GlassCard>

      <p className="lg:col-span-3 text-xs text-text-muted">
        {isPractice
          ? "Holdings refresh every 60s. Cash refreshes every 30s."
          : "Holdings refresh every 60s. Cash refreshes every 30s from your active broker data source."}
      </p>
    </div>
  );
}
