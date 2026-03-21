import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { DonutChart, AreaChart, BarList } from "@tremor/react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  BarChart3,
  Calculator,
  PieChart,
  RefreshCw,
  AlertCircle,
  ChevronRight,
  Layers,
  RotateCcw,
  Filter,
  Search,
  Ticket,
  Bell,
  Globe,
  DollarSign,
  Plus,
  Info,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useHoldings } from "@/hooks/useHoldings";
import { useFunds } from "@/hooks/useFunds";
import { getMultiQuotes } from "@/services/api";
import type { Holding, Quote } from "@/types/api";
import { cn } from "@/lib/utils";

// ─── Tab registry ─────────────────────────────────────────────────────────────

type TabId =
  | "overview"
  | "holdings"
  | "networth"
  | "mf"
  | "sip"
  | "quilt"
  | "sector"
  | "etf"
  | "stocks"
  | "ipo";

interface TabDef {
  id: TabId;
  label: string;
  icon: typeof TrendingUp;
}

const TABS: TabDef[] = [
  { id: "overview", label: "Portfolio Overview", icon: PieChart },
  { id: "holdings", label: "Holdings", icon: BarChart3 },
  { id: "networth", label: "Net Worth", icon: Wallet },
  { id: "mf", label: "Mutual Funds", icon: TrendingDown },
  { id: "sip", label: "SIP Calculator", icon: Calculator },
  { id: "quilt", label: "Asset Quilt", icon: Layers },
  { id: "sector", label: "Sector Rotation", icon: RotateCcw },
  { id: "etf", label: "ETF Screener", icon: Filter },
  { id: "stocks", label: "Stock Screener", icon: Search },
  { id: "ipo", label: "IPO Tracker", icon: Ticket },
];

// ─── Formatters ───────────────────────────────────────────────────────────────

function formatINR(value: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatINRCompact(value: number): string {
  if (Math.abs(value) >= 1_00_00_000) {
    return `₹${(value / 1_00_00_000).toFixed(2)}Cr`;
  }
  if (Math.abs(value) >= 1_00_000) {
    return `₹${(value / 1_00_000).toFixed(2)}L`;
  }
  return formatINR(value);
}

function formatPercent(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

// ─── Shared: Disabled action button with tooltip ───────────────────────────────

function DisabledActionButton({
  label,
  tooltip,
  icon: Icon = Plus,
}: {
  label: string;
  tooltip: string;
  icon?: typeof Plus;
}) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0}>
            <Button
              variant="outline"
              size="sm"
              disabled
              className="text-xs border-border-default text-text-muted gap-1 cursor-not-allowed opacity-60"
            >
              <Icon className="size-3" />
              {label}
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="bg-surface-card border-border-default text-text-secondary text-xs max-w-52"
        >
          {tooltip}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ─── Placeholder card (shared by coming-soon tabs) ────────────────────────────

interface PlaceholderTabProps {
  icon: typeof TrendingUp;
  title: string;
  version: string;
  description: string;
  bullets: string[];
}

function PlaceholderTab({
  icon: Icon,
  title,
  version,
  description,
  bullets,
}: PlaceholderTabProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-100 px-8 text-center gap-6">
      <div className="w-16 h-16 rounded-2xl bg-surface-card border border-border-default flex items-center justify-center">
        <Icon className="w-8 h-8 text-accent" />
      </div>

      <div className="space-y-2 max-w-md">
        <h2 className="font-heading font-semibold text-lg text-text-primary">{title}</h2>
        <p className="text-sm text-text-secondary leading-relaxed">{description}</p>
      </div>

      <ul className="space-y-2 text-left max-w-sm w-full">
        {bullets.map((b) => (
          <li key={b} className="flex items-start gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-accent mt-1.5 shrink-0" />
            <span className="text-xs text-text-secondary">{b}</span>
          </li>
        ))}
      </ul>

      <div className="flex items-center gap-2">
        <Badge className="bg-amber-500/20 text-amber-400 border-amber-700/50 text-xs">
          Coming in {version}
        </Badge>
        <Badge variant="outline" className="text-xs text-text-muted border-border-default gap-1">
          <Bell className="w-3 h-3" />
          Notify me when ready
        </Badge>
      </div>
    </div>
  );
}

// ─── 1. Portfolio Overview ────────────────────────────────────────────────────

interface AllocationBand {
  label: string;
  value: number;
  color: string;
  bg: string;
}

function OverviewTab({
  holdings,
  availableCash,
  totalInvested,
  currentValue,
  totalPnl,
  totalPnlPercent,
  isLoading,
}: {
  holdings: Holding[];
  availableCash: number;
  totalInvested: number;
  currentValue: number;
  totalPnl: number;
  totalPnlPercent: number;
  isLoading: boolean;
}) {
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

  const metrics = [
    {
      label: "Total Portfolio",
      value: isLoading ? "—" : formatINR(currentValue + availableCash),
      sub: "Holdings + Cash",
      positive: null as boolean | null,
      icon: Wallet,
      iconColor: "text-neutral-text",
      iconBg: "bg-neutral-bg",
    },
    {
      label: "Invested",
      value: isLoading ? "—" : formatINR(totalInvested),
      sub: "Cost basis",
      positive: null as boolean | null,
      icon: DollarSign,
      iconColor: "text-text-secondary",
      iconBg: "bg-surface-elevated",
    },
    {
      label: "Current Value",
      value: isLoading ? "—" : formatINR(currentValue),
      sub: "Holdings MTM",
      positive: null as boolean | null,
      icon: TrendingUp,
      iconColor: "text-text-secondary",
      iconBg: "bg-surface-elevated",
    },
    {
      label: "Total P&L",
      value: isLoading ? "—" : formatINR(totalPnl),
      sub: isLoading ? "" : formatPercent(totalPnlPercent),
      positive: totalPnl >= 0,
      icon: totalPnl >= 0 ? TrendingUp : TrendingDown,
      iconColor: totalPnl >= 0 ? "text-profit" : "text-loss",
      iconBg: totalPnl >= 0 ? "bg-bullish-bg" : "bg-bearish-bg",
    },
    {
      label: "Available Cash",
      value: isLoading ? "—" : formatINR(availableCash),
      sub: "Withdrawable",
      positive: null as boolean | null,
      icon: Wallet,
      iconColor: "text-profit",
      iconBg: "bg-bullish-bg",
    },
  ];

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <RefreshCw className="size-5 animate-spin" />
        <span className="text-sm">Loading portfolio data...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Metric cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {metrics.map((m) => {
          const Icon = m.icon;
          return (
            <Card
              key={m.label}
              className="p-4 bg-surface-card border-border-default space-y-2"
            >
              <div className="flex items-center gap-2">
                <div className={cn("size-7 rounded-lg flex items-center justify-center", m.iconBg)}>
                  <Icon className={cn("size-3.5", m.iconColor)} />
                </div>
                <span className="text-xxs text-text-muted uppercase tracking-wider">{m.label}</span>
              </div>
              <div
                className={cn(
                  "text-2xl font-mono font-bold tabular-nums",
                  m.positive === true && "text-profit",
                  m.positive === false && "text-loss",
                  m.positive === null && "text-text-primary",
                )}
              >
                {m.value}
              </div>
              {m.sub && (
                <div
                  className={cn(
                    "text-xs font-mono tabular-nums",
                    m.positive === true && "text-profit",
                    m.positive === false && "text-loss",
                    m.positive === null && "text-text-muted",
                  )}
                >
                  {m.sub}
                </div>
              )}
            </Card>
          );
        })}
      </div>

      {/* Allocation breakdown — Tremor DonutChart + BarList */}
      <Card className="p-5 bg-surface-card border-border-default space-y-4">
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary">Asset Allocation</h3>
          <p className="text-xs text-text-muted mt-0.5">
            Derived from live holdings and available cash. Debt / MF requires NAV data source.
          </p>
        </div>

        {bands.length > 0 ? (
          <div className="flex flex-col sm:flex-row gap-4 items-start">
            <DonutChart
              data={bands.map((b) => ({ name: b.label, value: b.value }))}
              category="value"
              index="name"
              valueFormatter={(v: number) => formatINR(v)}
              colors={["blue", "amber", "emerald"]}
              className="h-36 shrink-0"
              showLabel={false}
            />
            <div className="flex-1 min-w-0">
              <BarList
                data={bands
                  .filter((b) => b.value > 0)
                  .map((b) => ({ name: b.label, value: b.value }))}
                valueFormatter={(v: number) => formatINR(v)}
                color="blue"
                className="text-xs"
              />
            </div>
          </div>
        ) : (
          <div className="text-center py-6 text-text-muted text-xs">
            No holdings or cash data available. Connect to OpenAlgo to see allocation.
          </div>
        )}
      </Card>

      <p className="text-xs text-text-muted">
        Holdings refresh every 60s. Cash refreshes every 30s from OpenAlgo.
      </p>
    </div>
  );
}

// ─── 2. Holdings ──────────────────────────────────────────────────────────────

function PnLCell({ value, percent }: { value: number; percent: number }) {
  const pos = value >= 0;
  return (
    <div className={cn("text-right", pos ? "text-profit" : "text-loss")}>
      <div className="font-mono tabular-nums text-xs font-semibold">{formatINR(value)}</div>
      <div className="font-mono tabular-nums text-xs opacity-75">{formatPercent(percent)}</div>
    </div>
  );
}

function HoldingsTab({
  holdings,
  isLoading,
  isError,
  refetch,
}: {
  holdings: Holding[];
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns: ColumnDef<Holding>[] = useMemo(
    () => [
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => (
          <div>
            <div className="text-xs font-semibold text-text-primary font-mono">
              {row.original.symbol}
            </div>
            <div className="text-xs text-text-muted">{row.original.exchange}</div>
          </div>
        ),
      },
      {
        accessorKey: "quantity",
        header: () => <span className="block text-right">Qty</span>,
        cell: ({ getValue }) => (
          <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
            {(getValue() as number).toLocaleString("en-IN")}
          </div>
        ),
      },
      {
        accessorKey: "averagePrice",
        header: () => <span className="block text-right">Avg Price</span>,
        cell: ({ getValue }) => (
          <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
            {formatINR(getValue() as number)}
          </div>
        ),
      },
      {
        accessorKey: "ltp",
        header: () => <span className="block text-right">LTP</span>,
        cell: ({ getValue }) => (
          <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
            {formatINR(getValue() as number)}
          </div>
        ),
      },
      {
        id: "invested",
        header: () => <span className="block text-right">Invested</span>,
        accessorFn: (row) => row.averagePrice * row.quantity,
        cell: ({ getValue }) => (
          <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
            {formatINR(getValue() as number)}
          </div>
        ),
      },
      {
        accessorKey: "pnl",
        header: () => <span className="block text-right">P&amp;L</span>,
        cell: ({ row }) => (
          <PnLCell value={row.original.pnl} percent={row.original.pnlPercent} />
        ),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: holdings,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const totalInvested = useMemo(
    () => holdings.reduce((acc, h) => acc + h.averagePrice * h.quantity, 0),
    [holdings],
  );
  const totalCurrent = useMemo(
    () => holdings.reduce((acc, h) => acc + h.ltp * h.quantity, 0),
    [holdings],
  );
  const totalPnl = useMemo(
    () => holdings.reduce((acc, h) => acc + h.pnl, 0),
    [holdings],
  );
  const totalPnlPct = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0;

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <RefreshCw className="size-5 animate-spin" />
        <span className="text-sm">Fetching holdings from OpenAlgo...</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <AlertCircle className="size-5 text-loss" />
        <span className="text-sm">Failed to load holdings.</span>
        <Button variant="outline" size="sm" onClick={refetch} className="text-xs">
          Retry
        </Button>
      </div>
    );
  }

  if (holdings.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <BarChart3 className="size-8 text-text-disabled" />
        <span className="text-sm font-medium text-text-secondary">No holdings found</span>
        <span className="text-xs text-text-muted max-w-sm text-center">
          Buy equities via your broker (via OpenAlgo) and they will appear here after settlement.
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-2 py-2 border-b border-border-default">
        <span className="text-xs text-text-muted">
          {holdings.length} stock{holdings.length !== 1 ? "s" : ""}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={refetch}
          className="text-xs text-text-muted h-6 px-2 gap-1"
        >
          <RefreshCw className="size-3" />
          Refresh
        </Button>
      </div>

      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id} className="border-border-default hover:bg-transparent">
                {hg.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider cursor-pointer select-none"
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getIsSorted() === "asc" && " ↑"}
                    {header.column.getIsSorted() === "desc" && " ↓"}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                className="border-border-default hover:bg-surface-card transition-colors"
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className="py-2 text-xs">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Totals row */}
      <div className="border-t border-border-default bg-surface-card px-4 py-2 grid grid-cols-6 gap-2 text-xs font-mono tabular-nums">
        <span className="text-text-secondary font-semibold col-span-1">Total</span>
        <span className="text-right text-text-muted" />
        <span className="text-right text-text-muted" />
        <span className="text-right text-text-muted" />
        <span className="text-right text-text-secondary">{formatINR(totalInvested)}</span>
        <div className={cn("text-right", totalPnl >= 0 ? "text-profit" : "text-loss")}>
          <div className="font-semibold">{formatINR(totalPnl)}</div>
          <div className="text-xs opacity-75">
            {formatPercent(totalPnlPct)} on {formatINR(totalCurrent)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── 3. Net Worth ─────────────────────────────────────────────────────────────

interface AssetCategory {
  label: string;
  value: number | null;
  note: string;
  hexColor: string;
  tailwindBg: string;
  tailwindText: string;
  icon: typeof TrendingUp;
  addLabel: string;
  addTooltip: string;
}

// Approximate monthly equity value trend from holdings — uses current value
// as baseline and back-fills 5 months with illustrative relative fluctuations.
// Real historical values will come from trade history in v0.2.0.
function buildEquityTrend(currentValue: number): { month: string; value: number }[] {
  const months = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar"];
  // Synthetic growth: each prior month is ~2–5% less than next (simple illustrative)
  const factors = [0.88, 0.91, 0.94, 0.96, 0.98, 1.0];
  return months.map((month, i) => ({
    month,
    value: currentValue * factors[i],
  }));
}

function NetWorthMonthlyBar({ trend }: { trend: { month: string; value: number }[] }) {
  const chartData = trend.map((t) => ({ month: t.month, "Portfolio Value": t.value }));
  return (
    <AreaChart
      data={chartData}
      index="month"
      categories={["Portfolio Value"]}
      colors={["emerald"]}
      valueFormatter={(v: number) => formatINRCompact(v)}
      showLegend={false}
      showYAxis={false}
      showXAxis={true}
      showGridLines={false}
      className="h-20 text-xs"
      curveType="monotone"
    />
  );
}

function NetWorthTab({
  currentValue,
  availableCash,
  totalPnl,
  totalPnlPercent,
  isLoading,
}: {
  currentValue: number;
  availableCash: number;
  totalPnl: number;
  totalPnlPercent: number;
  isLoading: boolean;
}) {
  const knownTotal = currentValue + availableCash;
  const trend = useMemo(() => buildEquityTrend(currentValue), [currentValue]);

  const categories: AssetCategory[] = [
    {
      label: "Equity Holdings",
      value: isLoading ? null : currentValue,
      note: "Live from OpenAlgo",
      hexColor: "#3b82f6",
      tailwindBg: "bg-blue-500",
      tailwindText: "text-blue-400",
      icon: TrendingUp,
      addLabel: "Add Equity",
      addTooltip: "Buy via your broker through OpenAlgo — holdings sync automatically.",
    },
    {
      label: "Available Cash",
      value: isLoading ? null : availableCash,
      note: "Live from OpenAlgo",
      hexColor: "#22c55e",
      tailwindBg: "bg-emerald-500",
      tailwindText: "text-emerald-400",
      icon: Wallet,
      addLabel: "Add Cash",
      addTooltip: "Deposit funds via your broker — balance syncs from OpenAlgo.",
    },
    {
      label: "Mutual Funds",
      value: null,
      note: "Connect NAV source — Settings → Data Sources",
      hexColor: "#a855f7",
      tailwindBg: "bg-purple-500",
      tailwindText: "text-purple-400",
      icon: BarChart3,
      addLabel: "Add MF",
      addTooltip: "Connect a NAV provider (jugaad-data / mftool) in Settings to track MF folios.",
    },
    {
      label: "Gold",
      value: null,
      note: "Manual entry available in v0.2.0",
      hexColor: "#f59e0b",
      tailwindBg: "bg-amber-500",
      tailwindText: "text-amber-400",
      icon: Globe,
      addLabel: "Add Gold",
      addTooltip: "Manual gold tracking (sovereign bonds, physical, ETF) coming in v0.2.0.",
    },
    {
      label: "Fixed Deposits",
      value: null,
      note: "Manual entry available in v0.2.0",
      hexColor: "#06b6d4",
      tailwindBg: "bg-cyan-500",
      tailwindText: "text-cyan-400",
      icon: DollarSign,
      addLabel: "Add FD",
      addTooltip: "Track fixed deposits with maturity dates and interest tracking — v0.2.0.",
    },
  ];

  // Build allocation data — only from known values
  const knownCategories = categories.filter((c) => c.value !== null && c.value > 0);
  const donutTotal = knownCategories.reduce((acc, c) => acc + (c.value ?? 0), 0);

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Header */}
      <div>
        <h3 className="font-heading font-semibold text-sm text-text-primary">Net Worth Breakdown</h3>
        <p className="text-xs text-text-muted mt-0.5">
          Live equity and cash from OpenAlgo. Other asset classes require additional data sources.
        </p>
      </div>

      {/* Known total + donut side by side */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Known total card */}
        <Card className="p-5 bg-surface-card border-border-default flex flex-col justify-between gap-3">
          <div className="text-xxs text-text-muted uppercase tracking-wider">
            Known Total (Equity + Cash)
          </div>
          <div
            className={cn(
              "font-mono text-2xl font-bold tabular-nums",
              isLoading ? "text-text-muted" : "text-text-primary",
            )}
          >
            {isLoading ? "—" : formatINRCompact(knownTotal)}
          </div>
          {!isLoading && (
            <div
              className={cn(
                "text-sm font-mono tabular-nums",
                totalPnl >= 0 ? "text-profit" : "text-loss",
              )}
            >
              {formatINRCompact(totalPnl)}{" "}
              <span className="text-xs opacity-75">({formatPercent(totalPnlPercent)} unrealised)</span>
            </div>
          )}

          {/* Monthly equity trend */}
          {!isLoading && currentValue > 0 && (
            <div className="pt-2 border-t border-border-default">
              <div className="text-xxs text-text-muted mb-2 uppercase tracking-wider">
                Equity trend (6M illustrative)
              </div>
              <NetWorthMonthlyBar trend={trend} />
              <p className="text-xxs text-text-muted mt-1">
                Historical values from trade journal available in v0.2.0.
              </p>
            </div>
          )}
        </Card>

        {/* Tremor DonutChart for allocation */}
        <Card className="p-5 bg-surface-card border-border-default flex flex-col items-center gap-4">
          <div className="text-xxs text-text-muted uppercase tracking-wider self-start">
            Allocation (live assets only)
          </div>
          {knownCategories.length > 0 ? (
            <>
              <div className="relative w-36 h-36 shrink-0 flex items-center justify-center">
                <DonutChart
                  data={knownCategories.map((c) => ({ name: c.label, value: c.value ?? 0 }))}
                  category="value"
                  index="name"
                  valueFormatter={(v: number) => formatINRCompact(v)}
                  colors={["blue", "emerald", "violet", "amber", "cyan"]}
                  className="h-36"
                  showLabel={false}
                />
                <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <span className="text-xxs text-text-muted">tracked</span>
                  <span className="font-mono text-xs font-bold text-text-primary tabular-nums">
                    {isLoading ? "—" : formatINRCompact(knownTotal)}
                  </span>
                </div>
              </div>

              {/* Legend */}
              <div className="w-full space-y-1.5">
                {knownCategories.map((cat) => {
                  const pct = donutTotal > 0 ? ((cat.value ?? 0) / donutTotal) * 100 : 0;
                  return (
                    <div key={cat.label} className="flex items-center gap-2 text-xs">
                      <span className={cn("size-2.5 rounded-sm shrink-0", cat.tailwindBg)} />
                      <span className="text-text-secondary flex-1">{cat.label}</span>
                      <span className="font-mono tabular-nums text-text-primary">
                        {pct.toFixed(1)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-xs text-text-muted text-center">
              Connect to OpenAlgo to see allocation chart.
            </div>
          )}
        </Card>
      </div>

      {/* Per-category cards */}
      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          All Asset Classes
        </h4>
        {categories.map((cat) => {
          const Icon = cat.icon;
          return (
            <div
              key={cat.label}
              className="flex items-center gap-3 p-3 rounded-lg bg-surface-card border border-border-default"
            >
              <div
                className={cn(
                  "size-8 rounded-lg flex items-center justify-center shrink-0 opacity-80",
                  cat.tailwindBg.replace("bg-", "bg-") + "/20",
                )}
                style={{ backgroundColor: cat.hexColor + "20" }}
              >
                <Icon className={cn("size-4", cat.tailwindText)} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold text-text-primary">{cat.label}</div>
                <div className="text-xs text-text-muted">{cat.note}</div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {cat.value !== null ? (
                  <span className="font-mono tabular-nums text-xs text-text-primary">
                    {formatINRCompact(cat.value)}
                  </span>
                ) : (
                  <Badge
                    variant="outline"
                    className="text-xs border-border-default text-text-muted"
                  >
                    Not connected
                  </Badge>
                )}
                <DisabledActionButton
                  label={cat.addLabel}
                  tooltip={cat.addTooltip}
                  icon={Plus}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── 4. Mutual Funds ──────────────────────────────────────────────────────────

interface MfCategory {
  name: string;
  risk: string;
  desc: string;
  returnRange: string;
  horizon: string;
  color: string;
}

const MF_CATEGORIES: MfCategory[] = [
  {
    name: "Large Cap",
    risk: "Low",
    desc: "Top 100 companies by market cap. Stable, lower volatility.",
    returnRange: "10–14% p.a.",
    horizon: "3+ years",
    color: "text-blue-400",
  },
  {
    name: "Mid Cap",
    risk: "Medium",
    desc: "101–250 by market cap. Higher growth potential with moderate risk.",
    returnRange: "12–18% p.a.",
    horizon: "5+ years",
    color: "text-amber-400",
  },
  {
    name: "Small Cap",
    risk: "High",
    desc: "251+ by market cap. Aggressive growth, higher drawdown risk.",
    returnRange: "15–25% p.a.",
    horizon: "7+ years",
    color: "text-red-400",
  },
  {
    name: "Flexi Cap",
    risk: "Medium",
    desc: "Fund manager freely allocates across large, mid, and small cap based on market conditions.",
    returnRange: "12–18% p.a.",
    horizon: "5+ years",
    color: "text-orange-400",
  },
  {
    name: "ELSS",
    risk: "Medium",
    desc: "Equity Linked Savings Scheme. 3-year lock-in, 80C deduction up to ₹1.5L.",
    returnRange: "12–18% p.a.",
    horizon: "3 yr lock-in",
    color: "text-purple-400",
  },
  {
    name: "Debt / Liquid",
    risk: "Low",
    desc: "Government bonds, T-bills, corporate debt. Capital preservation focus.",
    returnRange: "6–8% p.a.",
    horizon: "< 1 year",
    color: "text-emerald-400",
  },
  {
    name: "Hybrid / Balanced",
    risk: "Low–Med",
    desc: "Mix of equity and debt. Automatic rebalancing by fund manager.",
    returnRange: "9–13% p.a.",
    horizon: "3–5 years",
    color: "text-cyan-400",
  },
  {
    name: "Index Funds",
    risk: "Low–Med",
    desc: "Passively track NIFTY 50, NIFTY Next 50, or Sensex. Lowest expense ratios.",
    returnRange: "10–14% p.a.",
    horizon: "5+ years",
    color: "text-teal-400",
  },
];

const RISK_COLOR: Record<string, string> = {
  Low: "bg-emerald-900/40 text-emerald-400 border-emerald-800",
  Medium: "bg-amber-900/40 text-amber-400 border-amber-800",
  High: "bg-red-900/40 text-red-400 border-red-800",
  "Low–Med": "bg-cyan-900/40 text-cyan-400 border-cyan-800",
};

// Placeholder AMC logos as text badges
const AMC_NAMES = [
  "SBI MF",
  "HDFC MF",
  "ICICI Pru",
  "Nippon India",
  "Axis MF",
  "Mirae Asset",
  "Kotak MF",
  "DSP MF",
  "Franklin",
  "UTI MF",
  "Canara Robeco",
  "Invesco",
];

function MutualFundsTab() {
  return (
    <div className="space-y-5 max-w-2xl">
      {/* Status banner */}
      <div className="flex items-start gap-3 bg-surface-card border border-border-default rounded-lg p-4">
        <AlertCircle className="size-4 text-amber-400 mt-0.5 shrink-0" />
        <div className="space-y-1">
          <p className="text-xs font-medium text-text-primary">NAV data source not connected</p>
          <p className="text-xs text-text-muted">
            Connect a NAV feed in{" "}
            <span className="text-amber-400 font-mono">Settings → Data Sources</span> to see live
            NAV, folio balances, and returns. Integration with jugaad-data and mftool is planned
            for v0.2.0.
          </p>
        </div>
      </div>

      {/* Search — disabled */}
      <div className="space-y-1.5">
        <Label className="text-xxs text-text-muted uppercase tracking-wider">Search Mutual Funds</Label>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-text-muted" />
          <Input
            disabled
            placeholder="Search by fund name or AMC — requires NAV feed (v0.2.0)"
            className="pl-8 h-9 text-xs bg-surface-card border-border-default text-text-muted cursor-not-allowed opacity-60"
          />
        </div>
      </div>

      {/* AMC placeholder row */}
      <div className="space-y-2">
        <p className="text-xs text-text-muted font-medium">Supported AMCs (after NAV feed is connected)</p>
        <div className="flex flex-wrap gap-2">
          {AMC_NAMES.map((name) => (
            <Badge
              key={name}
              variant="outline"
              className="text-xxs border-border-default text-text-muted opacity-60"
            >
              {name}
            </Badge>
          ))}
        </div>
      </div>

      {/* Category grid */}
      <div className="space-y-1">
        <h3 className="font-heading font-semibold text-sm text-text-primary">SEBI-Defined MF Categories</h3>
        <p className="text-xs text-text-muted">
          Risk ratings and return ranges are indicative based on SEBI product labelling guidelines
          and historical index data. Actual fund returns vary.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {MF_CATEGORIES.map((cat) => (
          <div
            key={cat.name}
            className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3"
          >
            <div className="flex items-center justify-between">
              <span className={cn("text-sm font-semibold", cat.color)}>{cat.name}</span>
              <Badge
                variant="outline"
                className={cn("text-xs h-5", RISK_COLOR[cat.risk])}
              >
                {cat.risk} risk
              </Badge>
            </div>
            <p className="text-xs text-text-muted leading-relaxed">{cat.desc}</p>
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <div className="text-xxs text-text-muted uppercase tracking-wider">Typical returns</div>
                <div className="text-xs font-mono text-text-secondary">{cat.returnRange}</div>
              </div>
              <div className="space-y-0.5 text-right">
                <div className="text-xxs text-text-muted uppercase tracking-wider">Horizon</div>
                <div className="text-xs font-mono text-text-secondary">{cat.horizon}</div>
              </div>
            </div>
            <DisabledActionButton
              label="Track Fund"
              tooltip="Connect a NAV data source in Settings to track individual funds and folios."
            />
          </div>
        ))}
      </div>

      <div className="flex items-center justify-center pt-2">
        <Badge className="bg-amber-500/20 text-amber-400 border-amber-700/50 text-xs gap-1">
          <Bell className="w-3 h-3" />
          Full MF dashboard with folio sync coming in v0.2.0
        </Badge>
      </div>
    </div>
  );
}

// ─── 5. SIP Calculator ────────────────────────────────────────────────────────

// Empty placeholder row for SIP tracking table
const SIP_TABLE_COLUMNS = ["Fund Name", "Monthly (₹)", "Start Date", "Duration", "Expected Return", "Maturity", "Status"];

function SipCalculatorTab() {
  const [monthly, setMonthly] = useState<string>("5000");
  const [rate, setRate] = useState<string>("12");
  const [years, setYears] = useState<string>("10");

  const result = useMemo(() => {
    const P = parseFloat(monthly) || 0;
    const r = (parseFloat(rate) || 0) / 100 / 12;
    const n = (parseFloat(years) || 0) * 12;
    if (P <= 0 || n <= 0) return null;
    const invested = P * n;
    const maturity =
      r > 0 ? P * ((Math.pow(1 + r, n) - 1) / r) * (1 + r) : invested;
    const returns = maturity - invested;
    const progress = invested > 0 ? Math.min((returns / maturity) * 100, 100) : 0;
    // Wealth ratio: maturity / invested
    const wealthRatio = invested > 0 ? maturity / invested : 0;
    return { invested, maturity, returns, progress, wealthRatio };
  }, [monthly, rate, years]);

  return (
    <div className="max-w-xl space-y-6">
      {/* Calculator */}
      <div className="space-y-1">
        <h3 className="font-heading font-semibold text-sm text-text-primary">SIP Calculator</h3>
        <p className="text-xs text-text-muted">
          Estimate future corpus from regular monthly investments using compound interest (CAGR).
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label className="text-xxs text-text-muted uppercase tracking-wider">Monthly SIP (INR)</Label>
          <Input
            type="number"
            value={monthly}
            onChange={(e) => setMonthly(e.target.value)}
            min="100"
            step="500"
            className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xxs text-text-muted uppercase tracking-wider">Expected Return (%/yr)</Label>
          <Input
            type="number"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            min="1"
            max="30"
            step="0.5"
            className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xxs text-text-muted uppercase tracking-wider">Duration (years)</Label>
          <Input
            type="number"
            value={years}
            onChange={(e) => setYears(e.target.value)}
            min="1"
            max="40"
            step="1"
            className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono"
          />
        </div>
      </div>

      {result ? (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-px bg-border-default rounded-lg overflow-hidden">
            <div className="bg-surface-card p-4 space-y-1">
              <span className="text-xxs text-text-muted uppercase tracking-wider">
                Total Invested
              </span>
              <div className="text-xl font-mono font-bold tabular-nums text-text-primary">
                {formatINRCompact(result.invested)}
              </div>
            </div>
            <div className="bg-surface-card p-4 space-y-1">
              <span className="text-xxs text-text-muted uppercase tracking-wider">
                Est. Returns
              </span>
              <div className="text-xl font-mono font-bold tabular-nums text-profit">
                {formatINRCompact(result.returns)}
              </div>
            </div>
            <div className="bg-surface-card p-4 space-y-1">
              <span className="text-xxs text-text-muted uppercase tracking-wider">
                Maturity Value
              </span>
              <div className="text-xl font-mono font-bold tabular-nums text-text-primary">
                {formatINRCompact(result.maturity)}
              </div>
            </div>
          </div>

          {/* Wealth ratio pill */}
          <div className="flex items-center gap-3 text-xs">
            <span className="text-text-muted">Wealth ratio:</span>
            <span className="font-mono font-semibold text-profit">
              {result.wealthRatio.toFixed(2)}x
            </span>
            <span className="text-text-muted">
              — your money multiplies {result.wealthRatio.toFixed(2)} times over {years} years
            </span>
          </div>

          {/* Stacked bar */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs text-text-muted">
              <span>Principal</span>
              <span>Estimated returns</span>
            </div>
            <div className="h-2.5 w-full bg-border-default rounded-full overflow-hidden flex">
              <div
                className="h-full bg-blue-600 transition-all duration-500"
                style={{ width: `${100 - result.progress}%` }}
              />
              <div
                className="h-full bg-emerald-500 transition-all duration-500"
                style={{ width: `${result.progress}%` }}
              />
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-neutral-text font-mono tabular-nums">
                {(100 - result.progress).toFixed(1)}% principal
              </span>
              <span className="text-profit font-mono tabular-nums">{result.progress.toFixed(1)}% gains</span>
            </div>
          </div>

          <p className="text-xs text-text-muted leading-relaxed">
            Investing {formatINR(parseFloat(monthly) || 0)}/month for {years} years at {rate}%
            p.a. compounds to {formatINRCompact(result.maturity)}. Actual MF returns vary; this is
            an illustrative projection only.
          </p>
        </div>
      ) : (
        <div className="text-center py-8 text-text-muted text-xs">
          Enter values above to calculate.
        </div>
      )}

      {/* SIP Tracking section */}
      <div className="pt-4 border-t border-border-default space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h4 className="font-heading font-semibold text-sm text-text-primary">Active SIPs</h4>
            <p className="text-xs text-text-muted mt-0.5">
              Track your running SIP mandates. Requires NAV feed connection to sync auto.
            </p>
          </div>
          <DisabledActionButton
            label="Add SIP"
            tooltip="Connect a NAV data source (Settings → Data Sources) to add and track SIP mandates."
            icon={Plus}
          />
        </div>

        {/* Empty table */}
        <div className="border border-border-default rounded-lg overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="border-border-default hover:bg-transparent">
                {SIP_TABLE_COLUMNS.map((col) => (
                  <TableHead
                    key={col}
                    className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider"
                  >
                    {col}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow className="border-none hover:bg-transparent">
                <TableCell
                  colSpan={SIP_TABLE_COLUMNS.length}
                  className="h-20 text-center text-xs text-text-muted"
                >
                  <div className="flex flex-col items-center gap-2">
                    <Info className="size-4 text-text-disabled" />
                    No SIPs tracked yet. Connect NAV provider to add SIP mandates.
                  </div>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>

        <p className="text-xs text-text-muted leading-relaxed">
          After connecting a NAV feed, FlintTrade will sync your SIP dates, invested amounts, and
          current NAV to show running XIRR alongside this calculator.
        </p>
      </div>
    </div>
  );
}

// ─── 6. Asset Quilt ───────────────────────────────────────────────────────────

// Static representative data for major Indian / global asset classes
// Source: approximate historical calendar-year returns (illustrative)
interface QuiltAsset {
  name: string;
  returns: Record<string, number>;
}

const QUILT_ASSETS: QuiltAsset[] = [
  {
    name: "NIFTY 50",
    returns: { "2019": 12.0, "2020": 14.9, "2021": 24.1, "2022": 4.3, "2023": 20.0, "2024": 8.8 },
  },
  {
    name: "NIFTY Midcap",
    returns: { "2019": 1.4, "2020": 24.4, "2021": 44.7, "2022": -1.6, "2023": 46.0, "2024": 24.7 },
  },
  {
    name: "NIFTY Smallcap",
    returns: { "2019": -8.9, "2020": 28.0, "2021": 63.4, "2022": -8.9, "2023": 55.0, "2024": 22.3 },
  },
  {
    name: "Gold (INR)",
    returns: { "2019": 24.6, "2020": 28.0, "2021": -5.9, "2022": 12.7, "2023": 14.3, "2024": 21.3 },
  },
  {
    name: "Debt (G-Sec)",
    returns: { "2019": 12.8, "2020": 12.2, "2021": 1.8, "2022": 2.7, "2023": 7.0, "2024": 8.4 },
  },
  {
    name: "NASDAQ (INR)",
    returns: { "2019": 43.2, "2020": 44.9, "2021": 25.1, "2022": -28.4, "2023": 43.0, "2024": 29.8 },
  },
  {
    name: "Real Estate (REITs)",
    returns: { "2019": 0.0, "2020": 0.0, "2021": 18.0, "2022": 8.0, "2023": 12.0, "2024": 7.0 },
  },
];

const QUILT_YEARS = ["2019", "2020", "2021", "2022", "2023", "2024"];

function returnColor(r: number): string {
  if (r >= 40) return "bg-emerald-400 text-emerald-950";
  if (r >= 20) return "bg-emerald-600 text-emerald-100";
  if (r >= 10) return "bg-emerald-800 text-emerald-200";
  if (r >= 0) return "bg-surface-elevated text-text-secondary";
  if (r >= -10) return "bg-red-900 text-red-300";
  return "bg-red-700 text-red-100";
}

function AssetQuiltTab() {
  // For each year, rank assets by return (highest first)
  const rankedByYear: Record<string, QuiltAsset[]> = {};
  for (const year of QUILT_YEARS) {
    rankedByYear[year] = [...QUILT_ASSETS].sort(
      (a, b) => (b.returns[year] ?? -Infinity) - (a.returns[year] ?? -Infinity),
    );
  }

  return (
    <div className="space-y-5 max-w-3xl">
      <div className="space-y-1">
        <h3 className="font-heading font-semibold text-sm text-text-primary">Asset Quilt — Annual Returns</h3>
        <p className="text-xs text-text-muted">
          Calendar-year returns ranked from best (top) to worst (bottom). Each column is one year;
          assets are sorted by that year&apos;s return. Illustrative data based on approximate
          index returns. Connect a data source for live NAV-based returns.
        </p>
      </div>

      {/* Quilt grid — columns = years, rows = rank */}
      <div className="overflow-x-auto">
        <div
          className="grid gap-1"
          style={{ gridTemplateColumns: `repeat(${QUILT_YEARS.length}, minmax(100px, 1fr))` }}
        >
          {/* Year headers */}
          {QUILT_YEARS.map((y) => (
            <div
              key={y}
              className="text-center text-xs font-semibold text-text-secondary pb-1 border-b border-border-default"
            >
              {y}
            </div>
          ))}

          {/* Ranked cells — one column per year */}
          {QUILT_YEARS.map((year) =>
            rankedByYear[year].map((asset, rank) => {
              const ret = asset.returns[year];
              return (
                <div
                  key={`${year}-${rank}`}
                  className={cn(
                    "rounded px-2 py-2 text-center space-y-0.5",
                    returnColor(ret ?? 0),
                  )}
                >
                  <div className="text-xs font-semibold leading-tight truncate">
                    {asset.name}
                  </div>
                  <div className="font-mono tabular-nums text-xs font-bold">
                    {ret !== undefined
                      ? `${ret >= 0 ? "+" : ""}${ret.toFixed(1)}%`
                      : "—"}
                  </div>
                </div>
              );
            }),
          )}
        </div>
      </div>

      <p className="text-xs text-text-muted leading-relaxed">
        Data is approximate and illustrative. NIFTY returns are index-only (no dividends). REIT
        data available from 2021. Connect jugaad-data or mftool in Settings for live NAV-based quilt.
      </p>

      {/* Legend */}
      <div className="flex flex-wrap gap-2">
        {[
          { label: "≥40%", cls: "bg-emerald-400" },
          { label: "20–40%", cls: "bg-emerald-600" },
          { label: "10–20%", cls: "bg-emerald-800" },
          { label: "0–10%", cls: "bg-surface-elevated border border-border-default" },
          { label: "-10–0%", cls: "bg-red-900" },
          { label: "<-10%", cls: "bg-red-700" },
        ].map((l) => (
          <div key={l.label} className="flex items-center gap-1.5">
            <span className={cn("size-3 rounded", l.cls)} />
            <span className="text-xs text-text-muted">{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 7. Sector Rotation ───────────────────────────────────────────────────────

interface SectorDef {
  label: string;
  symbol: string;
  exchange: string;
  description: string;
}

const SECTOR_INDICES: SectorDef[] = [
  { label: "Bank Nifty", symbol: "NIFTYBANK", exchange: "NSE_INDEX", description: "Banking sector" },
  { label: "Nifty IT", symbol: "NIFTYIT", exchange: "NSE_INDEX", description: "Information Technology" },
  { label: "Nifty Pharma", symbol: "NIFTYPHARMA", exchange: "NSE_INDEX", description: "Pharmaceuticals" },
  { label: "Nifty FMCG", symbol: "NIFTYFMCG", exchange: "NSE_INDEX", description: "Fast-moving consumer goods" },
  { label: "Nifty Auto", symbol: "NIFTYAUTO", exchange: "NSE_INDEX", description: "Automobiles" },
  { label: "Nifty Metal", symbol: "NIFTYMETAL", exchange: "NSE_INDEX", description: "Metals & Mining" },
  { label: "Nifty Realty", symbol: "NIFTYREALTY", exchange: "NSE_INDEX", description: "Real Estate" },
  { label: "Nifty Energy", symbol: "NIFTYENERGY", exchange: "NSE_INDEX", description: "Energy & Power" },
  { label: "Nifty Infra", symbol: "NIFTYINFRA", exchange: "NSE_INDEX", description: "Infrastructure" },
  { label: "Nifty Media", symbol: "NIFTYMEDIA", exchange: "NSE_INDEX", description: "Media & Entertainment" },
  { label: "Nifty PSU Bank", symbol: "NIFTYPSUBANK", exchange: "NSE_INDEX", description: "Public sector banks" },
  { label: "Nifty Private Bank", symbol: "NIFTYPVTBANK", exchange: "NSE_INDEX", description: "Private sector banks" },
  { label: "Financial Services", symbol: "NIFTYFINSERV", exchange: "NSE_INDEX", description: "NBFCs & Fin Services" },
];

function SectorChangeCell({ change, pct }: { change?: number; pct?: number }) {
  if (change === undefined && pct === undefined) {
    return <span className="text-text-muted font-mono tabular-nums text-xs">—</span>;
  }
  const positive = (pct ?? change ?? 0) >= 0;
  const Icon = positive ? ArrowUpRight : ArrowDownRight;
  return (
    <div className={cn("flex items-center gap-1 justify-end", positive ? "text-profit" : "text-loss")}>
      <Icon className="size-3 shrink-0" />
      <span className="font-mono tabular-nums text-xs font-semibold">
        {pct !== undefined ? formatPercent(pct) : formatPercent(change ?? 0)}
      </span>
    </div>
  );
}

function SectorRotationTab() {
  const symbols = SECTOR_INDICES.map((s) => ({ symbol: s.symbol, exchange: s.exchange }));

  const { data: quotes, isLoading, isError, refetch } = useQuery<Quote[]>({
    queryKey: ["sector-quotes"],
    queryFn: () => getMultiQuotes(symbols),
    refetchInterval: 60_000,
    retry: 1,
  });

  // Build a lookup map from symbol → quote
  const quoteMap = useMemo(() => {
    const map = new Map<string, Quote>();
    if (quotes) {
      for (const q of quotes) {
        map.set(q.symbol, q);
      }
    }
    return map;
  }, [quotes]);

  const rows = useMemo(() =>
    SECTOR_INDICES.map((s) => ({
      ...s,
      quote: quoteMap.get(s.symbol),
    })),
    [quoteMap],
  );

  // Sort by day pct change descending (strongest first)
  const sortedRows = useMemo(
    () =>
      [...rows].sort((a, b) => {
        const ap = a.quote?.pct ?? a.quote?.change ?? 0;
        const bp = b.quote?.pct ?? b.quote?.change ?? 0;
        return bp - ap;
      }),
    [rows],
  );

  return (
    <div className="space-y-5 max-w-3xl">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h3 className="font-heading font-semibold text-sm text-text-primary">Sector Performance</h3>
          <p className="text-xs text-text-muted">
            Live quotes for NSE sector indices via OpenAlgo. Sorted by day change, strongest first.
            RRG analysis (momentum × relative-strength) coming in v0.2.0.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          className="text-xs text-text-muted h-7 px-2 gap-1 shrink-0"
        >
          <RefreshCw className={cn("size-3", isLoading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {isError && (
        <div className="flex items-start gap-3 bg-surface-card border border-border-default rounded-lg p-4">
          <AlertCircle className="size-4 text-amber-400 mt-0.5 shrink-0" />
          <div className="space-y-1">
            <p className="text-xs font-medium text-text-primary">Could not fetch sector data</p>
            <p className="text-xs text-text-muted">
              Ensure OpenAlgo is running and the NSE_INDEX exchange is supported by your broker.
              Symbol names may differ — check OpenAlgo instruments list.
            </p>
          </div>
        </div>
      )}

      <div className="border border-border-default rounded-lg overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider">
                Sector
              </TableHead>
              <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                LTP
              </TableHead>
              <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                Day Change
              </TableHead>
              <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                Open
              </TableHead>
              <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                High / Low
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading
              ? Array.from({ length: 6 }).map((_, i) => (
                  <TableRow key={i} className="border-border-default">
                    <TableCell colSpan={5} className="py-2">
                      <div className="h-5 bg-surface-elevated rounded animate-pulse" />
                    </TableCell>
                  </TableRow>
                ))
              : sortedRows.map((row) => (
                  <TableRow
                    key={row.symbol}
                    className="border-border-default hover:bg-surface-card transition-colors"
                  >
                    <TableCell className="py-2">
                      <div className="text-xs font-semibold text-text-primary">{row.label}</div>
                      <div className="text-xxs text-text-muted">{row.description}</div>
                    </TableCell>
                    <TableCell className="py-2 text-right">
                      <span className="font-mono tabular-nums text-xs text-text-primary font-semibold">
                        {row.quote ? formatINR(row.quote.ltp) : "—"}
                      </span>
                    </TableCell>
                    <TableCell className="py-2 text-right">
                      <SectorChangeCell
                        change={row.quote?.change}
                        pct={row.quote?.pct}
                      />
                    </TableCell>
                    <TableCell className="py-2 text-right">
                      <span className="font-mono tabular-nums text-xs text-text-secondary">
                        {row.quote ? formatINR(row.quote.open) : "—"}
                      </span>
                    </TableCell>
                    <TableCell className="py-2 text-right">
                      {row.quote ? (
                        <div className="text-right">
                          <div className="font-mono tabular-nums text-xxs text-profit">
                            H: {formatINR(row.quote.high)}
                          </div>
                          <div className="font-mono tabular-nums text-xxs text-loss">
                            L: {formatINR(row.quote.low)}
                          </div>
                        </div>
                      ) : (
                        <span className="text-text-muted text-xs font-mono">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
          </TableBody>
        </Table>
      </div>

      {/* RRG placeholder */}
      <div className="rounded-lg border border-border-default bg-surface-card p-5 space-y-3">
        <div className="flex items-center gap-2">
          <RotateCcw className="size-4 text-accent" />
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Relative Rotation Graph (RRG) — v0.2.0
          </h4>
        </div>
        <p className="text-xs text-text-muted leading-relaxed">
          RRG plots each sector on Relative Strength vs. Momentum axes. Sectors cycle
          through four quadrants: <span className="text-profit">Leading</span> →{" "}
          <span className="text-amber-400">Weakening</span> →{" "}
          <span className="text-loss">Lagging</span> →{" "}
          <span className="text-blue-400">Improving</span>. Tail trails show momentum direction.
          Configurable look-back: 1D, 1W, 2W, 1M. Requires OHLCV history from OpenAlgo or
          jugaad-data.
        </p>
        <div className="flex items-center gap-2">
          <Badge className="bg-amber-500/20 text-amber-400 border-amber-700/50 text-xs">
            Coming in v0.2.0
          </Badge>
        </div>
      </div>

      <p className="text-xs text-text-muted">
        Quotes refresh every 60s. Symbol names must match your broker&apos;s instrument list in OpenAlgo.
      </p>
    </div>
  );
}

// ─── 8. ETF Screener ─────────────────────────────────────────────────────────

interface EtfInfo {
  name: string;
  nseSymbol: string;
  trackingIndex: string;
  expenseRatio: string;
  aum: string;
  category: string;
  color: string;
}

const POPULAR_ETFS: EtfInfo[] = [
  {
    name: "Nippon India ETF Nifty BeES",
    nseSymbol: "NIFTYBEES",
    trackingIndex: "NIFTY 50",
    expenseRatio: "0.04%",
    aum: "~₹24,000 Cr",
    category: "Large Cap",
    color: "text-blue-400",
  },
  {
    name: "Nippon India ETF Bank BeES",
    nseSymbol: "BANKBEES",
    trackingIndex: "NIFTY Bank",
    expenseRatio: "0.18%",
    aum: "~₹8,500 Cr",
    category: "Sectoral",
    color: "text-purple-400",
  },
  {
    name: "Nippon India ETF Gold BeES",
    nseSymbol: "GOLDBEES",
    trackingIndex: "Domestic Gold Price",
    expenseRatio: "0.59%",
    aum: "~₹9,000 Cr",
    category: "Commodity",
    color: "text-amber-400",
  },
  {
    name: "Nippon India ETF Liquid BeES",
    nseSymbol: "LIQUIDBEES",
    trackingIndex: "Overnight MIBOR",
    expenseRatio: "0.25%",
    aum: "~₹14,000 Cr",
    category: "Liquid / Debt",
    color: "text-emerald-400",
  },
  {
    name: "Mirae Asset NYSE FANG+ ETF",
    nseSymbol: "MAFANG",
    trackingIndex: "NYSE FANG+",
    expenseRatio: "0.50%",
    aum: "~₹1,800 Cr",
    category: "International",
    color: "text-cyan-400",
  },
  {
    name: "SBI ETF Nifty Next 50",
    nseSymbol: "NEXT50",
    trackingIndex: "NIFTY Next 50",
    expenseRatio: "0.10%",
    aum: "~₹3,200 Cr",
    category: "Large Cap",
    color: "text-blue-400",
  },
  {
    name: "CPSE ETF",
    nseSymbol: "CPSEETF",
    trackingIndex: "CPSE Index (PSU stocks)",
    expenseRatio: "0.01%",
    aum: "~₹28,000 Cr",
    category: "Thematic / PSU",
    color: "text-orange-400",
  },
  {
    name: "Motilal Oswal NASDAQ 100 ETF",
    nseSymbol: "MOM100",
    trackingIndex: "NASDAQ 100",
    expenseRatio: "0.50%",
    aum: "~₹6,800 Cr",
    category: "International",
    color: "text-cyan-400",
  },
];

const ETF_CATEGORY_COLOR: Record<string, string> = {
  "Large Cap": "bg-blue-900/40 text-blue-400 border-blue-800",
  "Sectoral": "bg-purple-900/40 text-purple-400 border-purple-800",
  "Commodity": "bg-amber-900/40 text-amber-400 border-amber-800",
  "Liquid / Debt": "bg-emerald-900/40 text-emerald-400 border-emerald-800",
  "International": "bg-cyan-900/40 text-cyan-400 border-cyan-800",
  "Thematic / PSU": "bg-orange-900/40 text-orange-400 border-orange-800",
};

function EtfScreenerTab() {
  return (
    <div className="space-y-5 max-w-2xl">
      <div className="space-y-1">
        <h3 className="font-heading font-semibold text-sm text-text-primary">Popular ETFs</h3>
        <p className="text-xs text-text-muted">
          Commonly traded ETFs on NSE. Expense ratios and AUM are approximate. Live NAV, tracking
          error, and returns screening require jugaad-data or BSE/NSE instrument feed (v0.2.0).
        </p>
      </div>

      {/* Status banner */}
      <div className="flex items-start gap-3 bg-surface-card border border-border-default rounded-lg p-4">
        <Info className="size-4 text-blue-400 mt-0.5 shrink-0" />
        <div className="space-y-1">
          <p className="text-xs font-medium text-text-primary">Live NAV not connected</p>
          <p className="text-xs text-text-muted">
            Once connected, the screener will show 1M / 1Y / 3Y returns, tracking error, bid-ask
            spread, and average daily volume alongside each ETF. You can filter, compare, and open
            any ETF directly in the Chart widget.
          </p>
        </div>
      </div>

      {/* ETF grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {POPULAR_ETFS.map((etf) => (
          <div
            key={etf.nseSymbol}
            className="bg-surface-card border border-border-default rounded-lg p-4 space-y-3"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className={cn("text-xs font-semibold font-mono", etf.color)}>
                  {etf.nseSymbol}
                </div>
                <div className="text-xxs text-text-secondary mt-0.5 leading-tight">
                  {etf.name}
                </div>
              </div>
              <Badge
                variant="outline"
                className={cn(
                  "text-xxs h-5 shrink-0",
                  ETF_CATEGORY_COLOR[etf.category] ?? "bg-surface-elevated text-text-muted border-border-default",
                )}
              >
                {etf.category}
              </Badge>
            </div>

            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-text-muted">Tracks</span>
                <span className="text-text-secondary font-mono text-xxs text-right max-w-32 truncate">
                  {etf.trackingIndex}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">Expense Ratio</span>
                <span className="text-text-primary font-mono tabular-nums">{etf.expenseRatio}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">AUM (approx)</span>
                <span className="text-text-secondary font-mono tabular-nums">{etf.aum}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">1Y / 3Y return</span>
                <span className="text-text-muted font-mono tabular-nums text-xxs">
                  — / — (NAV feed needed)
                </span>
              </div>
            </div>

            <DisabledActionButton
              label="Track ETF"
              tooltip="Connect a NAV data source in Settings to track this ETF, see live NAV and historical returns."
            />
          </div>
        ))}
      </div>

      {/* ETF vs Index concept */}
      <Card className="p-5 bg-surface-card border-border-default space-y-3">
        <div className="flex items-center gap-2">
          <Filter className="size-4 text-accent" />
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Full ETF Screener — v0.2.0
          </h4>
        </div>
        <p className="text-xs text-text-muted leading-relaxed">
          Filter 200+ NSE/BSE listed ETFs by category, AUM threshold, expense ratio range,
          tracking error, liquidity (average daily volume), and time-based returns. Compare any
          two ETFs against each other and against their benchmark index. Drill into top holdings
          and sector weights for equity ETFs. Export filtered lists to CSV.
        </p>
        <div className="flex flex-wrap gap-2">
          {["Equity ETFs", "Debt ETFs", "Gold ETFs", "International ETFs", "Thematic ETFs", "Factor ETFs"].map((cat) => (
            <Badge
              key={cat}
              variant="outline"
              className="text-xxs border-border-default text-text-muted opacity-60"
            >
              {cat}
            </Badge>
          ))}
        </div>
      </Card>

      <p className="text-xs text-text-muted">
        AUM and expense ratio data sourced from publicly available fund factsheets (as of 2024).
        Always verify current figures before investing.
      </p>
    </div>
  );
}

// ─── 9. Stocks Tab ────────────────────────────────────────────────────────────

// Calculate CAGR: ((currentValue / investedValue) ^ (1/years)) - 1
function calcCAGR(invested: number, current: number, yearsHeld: number): number | null {
  if (invested <= 0 || current <= 0 || yearsHeld <= 0) return null;
  return (Math.pow(current / invested, 1 / yearsHeld) - 1) * 100;
}

// Group holdings by a simple sector heuristic based on symbol suffix / name patterns.
// Real sector data requires NSE master file or screener package integration.
function inferSector(symbol: string): string {
  const s = symbol.toUpperCase();
  if (/BANK|HDFC|ICICI|AXIS|SBI|KOTAK|INDUS|FEDERAL|RBL|BANDHAN/.test(s)) return "Banking";
  if (/TCS|INFY|WIPRO|HCL|TECH|LTI|MPHASIS|COFORGE/.test(s)) return "IT";
  if (/PHARMA|CIPLA|DRRD|SUN|LUPIN|BIOCON|ALKEM|IPCA/.test(s)) return "Pharma";
  if (/AUTO|MARUTI|TATA.*MOTORS|BAJAJ.*AUTO|HERO|EICHER|M&M/.test(s)) return "Auto";
  if (/RELIANCE|ONGC|BPCL|IOC|GAIL|NTPC|POWERGRID/.test(s)) return "Energy";
  if (/HIND.*UNILEVER|NESTLE|ITC|BRITANNIA|DABUR/.test(s)) return "FMCG";
  if (/METAL|STEEL|TATA.*STEEL|HINDALCO|SAIL|JINDAL/.test(s)) return "Metals";
  return "Other";
}

function StocksTab({
  holdings,
  isLoading,
  isError,
  refetch,
}: {
  holdings: Holding[];
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
}) {
  // Assume average holding duration of 2 years for CAGR illustration.
  // Real buy dates will come from trade history in v0.2.0.
  const ASSUMED_YEARS = 2;

  const enrichedHoldings = useMemo(
    () =>
      holdings.map((h) => {
        const invested = h.averagePrice * h.quantity;
        const current = h.ltp * h.quantity;
        const cagr = calcCAGR(invested, current, ASSUMED_YEARS);
        const sector = inferSector(h.symbol);
        return { ...h, invested, current, cagr, sector };
      }),
    [holdings],
  );

  // Sector breakdown
  const sectorMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const h of enrichedHoldings) {
      map.set(h.sector, (map.get(h.sector) ?? 0) + h.current);
    }
    return map;
  }, [enrichedHoldings]);

  const totalCurrent = useMemo(
    () => enrichedHoldings.reduce((acc, h) => acc + h.current, 0),
    [enrichedHoldings],
  );

  const sectorEntries = useMemo(
    () =>
      [...sectorMap.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([sector, value]) => ({
          sector,
          value,
          pct: totalCurrent > 0 ? (value / totalCurrent) * 100 : 0,
        })),
    [sectorMap, totalCurrent],
  );

  const SECTOR_COLORS = [
    "bg-blue-500", "bg-purple-500", "bg-cyan-500", "bg-amber-500",
    "bg-emerald-500", "bg-orange-500", "bg-red-500", "bg-pink-500",
  ];

  const [sorting, setSorting] = useState<SortingState>([{ id: "current", desc: true }]);

  const columns: ColumnDef<typeof enrichedHoldings[number]>[] = useMemo(
    () => [
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => (
          <div>
            <div className="text-xs font-semibold font-mono text-text-primary">{row.original.symbol}</div>
            <div className="text-xxs text-text-muted">{row.original.sector}</div>
          </div>
        ),
      },
      {
        accessorKey: "quantity",
        header: () => <span className="block text-right">Qty</span>,
        cell: ({ getValue }) => (
          <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
            {(getValue() as number).toLocaleString("en-IN")}
          </div>
        ),
      },
      {
        id: "invested",
        header: () => <span className="block text-right">Invested</span>,
        accessorFn: (row) => row.invested,
        cell: ({ getValue }) => (
          <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
            {formatINRCompact(getValue() as number)}
          </div>
        ),
      },
      {
        id: "current",
        header: () => <span className="block text-right">Current</span>,
        accessorFn: (row) => row.current,
        cell: ({ getValue }) => (
          <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
            {formatINRCompact(getValue() as number)}
          </div>
        ),
      },
      {
        accessorKey: "pnl",
        header: () => <span className="block text-right">P&amp;L</span>,
        cell: ({ row }) => (
          <PnLCell value={row.original.pnl} percent={row.original.pnlPercent} />
        ),
      },
      {
        accessorKey: "cagr",
        header: () => (
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="block text-right cursor-help underline decoration-dashed decoration-text-muted">
                  CAGR
                </span>
              </TooltipTrigger>
              <TooltipContent
                side="top"
                className="bg-surface-card border-border-default text-text-secondary text-xs max-w-52"
              >
                Illustrative CAGR assumes {ASSUMED_YEARS}-year hold. Actual buy date from trade
                history available in v0.2.0.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ),
        cell: ({ getValue }) => {
          const cagr = getValue() as number | null;
          if (cagr === null) return <span className="text-text-muted font-mono text-xs block text-right">—</span>;
          return (
            <div
              className={cn(
                "text-right font-mono tabular-nums text-xs font-semibold",
                cagr >= 0 ? "text-profit" : "text-loss",
              )}
            >
              {formatPercent(cagr)} p.a.
            </div>
          );
        },
      },
    ],
    [],
  );

  const table = useReactTable({
    data: enrichedHoldings,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <RefreshCw className="size-5 animate-spin" />
        <span className="text-sm">Loading holdings...</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <AlertCircle className="size-5 text-loss" />
        <span className="text-sm">Failed to load holdings.</span>
        <Button variant="outline" size="sm" onClick={refetch} className="text-xs">
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h3 className="font-heading font-semibold text-sm text-text-primary">Stock Holdings</h3>
          <p className="text-xs text-text-muted">
            Enhanced view of your equity holdings from OpenAlgo with inferred sector breakdown and
            illustrative CAGR. Buy dates from trade history will improve CAGR accuracy in v0.2.0.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={refetch}
          className="text-xs text-text-muted h-7 px-2 gap-1 shrink-0"
        >
          <RefreshCw className="size-3" />
          Refresh
        </Button>
      </div>

      {holdings.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-3 text-text-muted">
          <BarChart3 className="size-8 text-text-disabled" />
          <span className="text-sm font-medium text-text-secondary">No holdings found</span>
          <span className="text-xs text-text-muted max-w-sm text-center">
            Buy equities via your broker through OpenAlgo and they will appear here after
            settlement.
          </span>
        </div>
      ) : (
        <>
          {/* Holdings table with CAGR */}
          <div className="border border-border-default rounded-lg overflow-hidden">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((hg) => (
                  <TableRow key={hg.id} className="border-border-default hover:bg-transparent">
                    {hg.headers.map((header) => (
                      <TableHead
                        key={header.id}
                        className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider cursor-pointer select-none"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {header.column.getIsSorted() === "asc" && " ↑"}
                        {header.column.getIsSorted() === "desc" && " ↓"}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    className="border-border-default hover:bg-surface-card transition-colors"
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} className="py-2 text-xs">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Sector breakdown */}
          {sectorEntries.length > 0 && (
            <Card className="p-5 bg-surface-card border-border-default space-y-4">
              <h4 className="font-heading font-semibold text-sm text-text-primary">
                Sector Breakdown
              </h4>
              <p className="text-xxs text-text-muted">
                Sector classification is inferred from symbol names. Accuracy improves when trade
                history and NSE master data are connected.
              </p>
              <div className="space-y-2">
                {sectorEntries.map(({ sector, value, pct }, idx) => (
                  <div key={sector} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn("size-2.5 rounded-sm", SECTOR_COLORS[idx % SECTOR_COLORS.length])}
                        />
                        <span className="text-text-secondary">{sector}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="font-mono tabular-nums text-text-primary">
                          {formatINRCompact(value)}
                        </span>
                        <span className="font-mono tabular-nums text-text-muted w-12 text-right">
                          {pct.toFixed(1)}%
                        </span>
                      </div>
                    </div>
                    <div className="h-1.5 bg-border-default rounded-full overflow-hidden">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all duration-700",
                          SECTOR_COLORS[idx % SECTOR_COLORS.length],
                        )}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}

      {/* Dividend tracking placeholder */}
      <Card className="p-5 bg-surface-card border-border-default space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bell className="size-4 text-profit" />
            <h4 className="font-heading font-semibold text-sm text-text-primary">
              Dividend Tracking
            </h4>
          </div>
          <DisabledActionButton
            label="Add Dividend"
            tooltip="Dividend auto-detection from OpenAlgo trade history is planned for v0.2.0."
            icon={Plus}
          />
        </div>
        <p className="text-xs text-text-muted leading-relaxed">
          FlintTrade will auto-detect dividend credits from your trade history and map them to
          holdings to show annual yield, total dividends received, and yield-on-cost per stock.
          Requires trade history access via OpenAlgo tradebook.
        </p>
        <div className="grid grid-cols-3 gap-px bg-border-default rounded-lg overflow-hidden">
          {[
            { label: "Total Dividends (FY)", value: "—" },
            { label: "Average Yield", value: "—" },
            { label: "Next Ex-Dividend", value: "—" },
          ].map(({ label, value }) => (
            <div key={label} className="bg-surface-card p-3 space-y-1">
              <div className="text-xxs text-text-muted uppercase tracking-wider">{label}</div>
              <div className="font-mono text-sm font-bold tabular-nums text-text-muted">{value}</div>
            </div>
          ))}
        </div>
        <Badge className="bg-amber-500/20 text-amber-400 border-amber-700/50 text-xs gap-1">
          Auto-detect dividends from trade history — v0.2.0
        </Badge>
      </Card>

      {/* Stock screener concept */}
      <Card className="p-5 bg-surface-card border-border-default space-y-3">
        <div className="flex items-center gap-2">
          <Search className="size-4 text-accent" />
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Stock Screener — v0.2.0
          </h4>
        </div>
        <p className="text-xs text-text-muted leading-relaxed">
          Screen NSE/BSE stocks by P/E, P/B, Dividend Yield, ROE, Debt-to-Equity, 52-week
          high/low, RSI, and promoter holding. Uses the{" "}
          <span className="text-accent font-mono">screener</span> Python package (already in the
          monorepo) once connected to a OHLCV + fundamentals data source.
        </p>
        <div className="flex flex-wrap gap-2">
          {["P/E < 20", "Dividend Yield > 3%", "ROE > 15%", "52W Breakout", "Low Debt", "CANSLIM"].map((screen) => (
            <Badge
              key={screen}
              variant="outline"
              className="text-xxs border-border-default text-text-muted opacity-60 cursor-not-allowed"
            >
              {screen}
            </Badge>
          ))}
        </div>
      </Card>
    </div>
  );
}

// ─── 10. IPO Tracker ──────────────────────────────────────────────────────────

function IpoTrackerTab() {
  return (
    <PlaceholderTab
      icon={Ticket}
      title="IPO Tracker"
      version="v0.2.0"
      description="Track upcoming, open, and recently listed IPOs on NSE and BSE. See subscription
      data (retail, QIB, NII categories), GMP (grey market premium) trends, allotment dates,
      and listing performance — all in one place."
      bullets={[
        "Upcoming IPOs: open/close dates, price band, lot size, issue size",
        "Subscription status: live retail / QIB / NII subscription multiples",
        "GMP tracker: grey market premium history from community sources",
        "Post-listing: day-1 vs. issue price performance, 1-week return",
        "Alert: get Telegram notification 1 day before application deadline",
      ]}
    />
  );
}

// ─── Root ──────────────────────────────────────────────────────────────────────

export default function InvestRoute() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  const {
    data: holdings = [],
    isLoading: holdingsLoading,
    isError: holdingsError,
    refetch: refetchHoldings,
  } = useHoldings();

  const { data: funds, isLoading: fundsLoading } = useFunds();

  const isLoading = holdingsLoading || fundsLoading;
  const availableCash = funds?.availableCash ?? 0;

  const totalInvested = useMemo(
    () => holdings.reduce((acc, h) => acc + h.averagePrice * h.quantity, 0),
    [holdings],
  );
  const currentValue = useMemo(
    () => holdings.reduce((acc, h) => acc + h.ltp * h.quantity, 0),
    [holdings],
  );
  const totalPnl = useMemo(
    () => holdings.reduce((acc, h) => acc + h.pnl, 0),
    [holdings],
  );
  const totalPnlPercent = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0;

  const tabContent: Record<TabId, React.ReactNode> = {
    overview: (
      <OverviewTab
        holdings={holdings}
        availableCash={availableCash}
        totalInvested={totalInvested}
        currentValue={currentValue}
        totalPnl={totalPnl}
        totalPnlPercent={totalPnlPercent}
        isLoading={isLoading}
      />
    ),
    holdings: (
      <HoldingsTab
        holdings={holdings}
        isLoading={holdingsLoading}
        isError={holdingsError}
        refetch={refetchHoldings}
      />
    ),
    networth: (
      <NetWorthTab
        currentValue={currentValue}
        availableCash={availableCash}
        totalPnl={totalPnl}
        totalPnlPercent={totalPnlPercent}
        isLoading={isLoading}
      />
    ),
    mf: <MutualFundsTab />,
    sip: <SipCalculatorTab />,
    quilt: <AssetQuiltTab />,
    sector: <SectorRotationTab />,
    etf: <EtfScreenerTab />,
    stocks: (
      <StocksTab
        holdings={holdings}
        isLoading={holdingsLoading}
        isError={holdingsError}
        refetch={refetchHoldings}
      />
    ),
    ipo: <IpoTrackerTab />,
  };

  // Holdings-only tabs render their own scroll/overflow — wrap them differently
  const fullHeightTabs: TabId[] = ["holdings"];

  return (
    <div className="h-full bg-surface-base flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <TrendingUp className="w-6 h-6 text-profit" />
            <div>
              <h1 className="font-heading font-bold text-lg text-text-primary">Investor Dashboard</h1>
              <p className="text-xxs text-text-muted">
                Portfolio, holdings, net worth, and investment tools
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isLoading && <RefreshCw className="size-3 text-text-muted animate-spin" />}
            {!isLoading && (
              <Badge
                variant="outline"
                className="text-xxs h-5 border-border-default text-text-muted"
              >
                {holdings.length} holdings
              </Badge>
            )}
          </div>
        </div>
      </div>

      {/* Body: sidebar + content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
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
                <Icon className="w-4 h-4 shrink-0" />
                <span className="truncate">{tab.label}</span>
                <ChevronRight
                  className={`w-3 h-3 ml-auto shrink-0 ${isActive ? "opacity-100" : "opacity-0"}`}
                />
              </button>
            );
          })}
        </div>

        {/* Content */}
        {fullHeightTabs.includes(activeTab) ? (
          <div className="flex-1 flex flex-col overflow-hidden">
            {tabContent[activeTab]}
          </div>
        ) : (
          <ScrollArea className="flex-1">
            <div className="p-6 max-w-4xl">{tabContent[activeTab]}</div>
          </ScrollArea>
        )}
      </div>
    </div>
  );
}
