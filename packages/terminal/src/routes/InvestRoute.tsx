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
  LayoutDashboard,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { GlassCard } from "@/components/ui/GlassCard";
import TabTransition from "@/components/motion/TabTransition";
import { StaggeredList } from "@/components/motion/StaggeredList";
import { AnimatedCounter } from "@/components/magicui/animated-counter";
import { useHoldings } from "@/hooks/useHoldings";
import { useFunds } from "@/hooks/useFunds";
import { getMultiQuotes } from "@/services/api";
import type { Holding, Quote } from "@/types/api";
import { cn } from "@/lib/utils";

// ─── Tab registry ─────────────────────────────────────────────────────────────

type TabId =
  | "dashboard"
  | "holdings"
  | "sip"
  | "networth"
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
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "holdings", label: "Holdings", icon: BarChart3 },
  { id: "sip", label: "SIPs", icon: Calculator },
  { id: "networth", label: "Net Worth", icon: Wallet },
  { id: "sector", label: "Sector", icon: RotateCcw },
  { id: "etf", label: "ETFs", icon: Filter },
  { id: "stocks", label: "Stocks", icon: Search },
  { id: "ipo", label: "IPO", icon: Ticket },
];

// ─── Formatters ───────────────────────────────────────────────────────────────

const INR_FORMATTER = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});
function formatINR(value: number): string {
  return INR_FORMATTER.format(value);
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
        <Badge className="bg-atm-bg text-warning border-atm-border text-xs">
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

// ─── 1. Dashboard (Bento Grid) ────────────────────────────────────────────────

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

function DashboardTab({
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
  const netWorth = currentValue + availableCash;

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

  // Top movers — top 3 gainers and losers by P&L %
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

  // Sector counts for breakdown pill
  const sectorCount = useMemo(() => {
    const sectors = new Set(
      holdings.map((h) => {
        const s = h.symbol.toUpperCase();
        if (/BANK|HDFC|ICICI|AXIS|SBI|KOTAK|INDUS|FEDERAL|RBL|BANDHAN/.test(s)) return "Banking";
        if (/TCS|INFY|WIPRO|HCL|TECH|LTI|MPHASIS|COFORGE/.test(s)) return "IT";
        if (/PHARMA|CIPLA|DRRD|SUN|LUPIN|BIOCON|ALKEM|IPCA/.test(s)) return "Pharma";
        if (/AUTO|MARUTI|BAJAJ.*AUTO|HERO|EICHER/.test(s)) return "Auto";
        if (/RELIANCE|ONGC|BPCL|IOC|GAIL|NTPC|POWERGRID/.test(s)) return "Energy";
        if (/HIND.*UNILEVER|NESTLE|ITC|BRITANNIA|DABUR/.test(s)) return "FMCG";
        if (/METAL|STEEL|TATA.*STEEL|HINDALCO|SAIL|JINDAL/.test(s)) return "Metals";
        return "Other";
      }),
    );
    return sectors.size;
  }, [holdings]);

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
      {/* ── Hero card: Net Worth (full width) ─── */}
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

      {/* ── Row 2: 3 KPI cards ─── */}
      <StaggeredList className="contents" staggerDelay={50}>
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
            <AnimatedCounter
              value={availableCash}
              formatter={formatINRCompact}
              duration={1.0}
            />
          </div>
          <p className="text-xs text-text-muted">Withdrawable cash</p>
        </GlassCard>

        <GlassCard className="p-4 gap-2">
          <div className="flex items-center gap-2">
            <div className="size-7 rounded-lg flex items-center justify-center bg-surface-elevated">
              <DollarSign className="size-3.5 text-text-secondary" />
            </div>
            <span className="text-xxs text-text-muted uppercase tracking-wider">
              Margin Used
            </span>
          </div>
          <div className="text-2xl font-mono font-bold tabular-nums text-text-primary">
            <AnimatedCounter
              value={totalInvested}
              formatter={formatINRCompact}
              duration={1.0}
            />
          </div>
          <p className="text-xs text-text-muted">Cost basis of holdings</p>
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
              Day P&amp;L
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
          <p className="text-xs text-text-muted">
            {formatPercent(totalPnlPercent)} unrealised
          </p>
        </GlassCard>
      </StaggeredList>

      {/* ── Row 3: Allocation chart + Top Movers (2-col) ─── */}
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

      {/* ── Row 4: 3 stat pills ─── */}
      <StaggeredList className="contents" staggerDelay={40}>
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
      </StaggeredList>

      <p className="lg:col-span-3 text-xs text-text-muted">
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
        <GlassCard className="p-5 flex flex-col justify-between gap-3">
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
        </GlassCard>

        {/* Tremor DonutChart for allocation */}
        <GlassCard className="p-5 flex flex-col items-center gap-4">
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
        </GlassCard>
      </div>

      {/* Per-category cards */}
      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          All Asset Classes
        </h4>
        <StaggeredList staggerDelay={30}>
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
        </StaggeredList>
      </div>
    </div>
  );
}

// ─── 4. SIP Calculator ────────────────────────────────────────────────────────

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
          <StaggeredList className="grid grid-cols-3 gap-px bg-border-default rounded-lg overflow-hidden" staggerDelay={60}>
            <GlassCard className="rounded-none p-4 gap-1">
              <span className="text-xxs text-text-muted uppercase tracking-wider">
                Total Invested
              </span>
              <div className="text-xl font-mono font-bold tabular-nums text-text-primary">
                {formatINRCompact(result.invested)}
              </div>
            </GlassCard>
            <GlassCard className="rounded-none p-4 gap-1">
              <span className="text-xxs text-text-muted uppercase tracking-wider">
                Est. Returns
              </span>
              <div className="text-xl font-mono font-bold tabular-nums text-profit">
                {formatINRCompact(result.returns)}
              </div>
            </GlassCard>
            <GlassCard className="rounded-none p-4 gap-1">
              <span className="text-xxs text-text-muted uppercase tracking-wider">
                Maturity Value
              </span>
              <div className="text-xl font-mono font-bold tabular-nums text-text-primary">
                {formatINRCompact(result.maturity)}
              </div>
            </GlassCard>
          </StaggeredList>

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
                className="h-full bg-profit transition-all duration-500"
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

// ─── 5. Sector Rotation ───────────────────────────────────────────────────────

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
          <AlertCircle className="size-4 text-warning mt-0.5 shrink-0" />
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
      <GlassCard className="p-5 gap-3">
        <div className="flex items-center gap-2">
          <RotateCcw className="size-4 text-accent" />
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Relative Rotation Graph (RRG) — v0.2.0
          </h4>
        </div>
        <p className="text-xs text-text-muted leading-relaxed">
          RRG plots each sector on Relative Strength vs. Momentum axes. Sectors cycle
          through four quadrants: <span className="text-profit">Leading</span> →{" "}
          <span className="text-warning">Weakening</span> →{" "}
          <span className="text-loss">Lagging</span> →{" "}
          <span className="text-blue-400">Improving</span>. Tail trails show momentum direction.
          Configurable look-back: 1D, 1W, 2W, 1M. Requires OHLCV history from OpenAlgo or
          jugaad-data.
        </p>
        <div className="flex items-center gap-2">
          <Badge className="bg-atm-bg text-warning border-atm-border text-xs">
            Coming in v0.2.0
          </Badge>
        </div>
      </GlassCard>

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
      <StaggeredList className="grid grid-cols-1 sm:grid-cols-2 gap-3" staggerDelay={30}>
        {POPULAR_ETFS.map((etf) => (
          <GlassCard key={etf.nseSymbol} className="p-4 gap-3">
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
          </GlassCard>
        ))}
      </StaggeredList>

      {/* ETF vs Index concept */}
      <GlassCard className="p-5 gap-3">
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
      </GlassCard>

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
            <GlassCard className="p-5 gap-4">
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
            </GlassCard>
          )}
        </>
      )}

      {/* Dividend tracking placeholder */}
      <GlassCard className="p-5 gap-3">
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
        <Badge className="bg-atm-bg text-warning border-atm-border text-xs gap-1">
          Auto-detect dividends from trade history — v0.2.0
        </Badge>
      </GlassCard>

      {/* Stock screener concept */}
      <GlassCard className="p-5 gap-3">
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
      </GlassCard>
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
  const [activeTab, setActiveTab] = useState<TabId>("dashboard");

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

  // Holdings-only tabs render their own scroll/overflow — wrap them differently
  const fullHeightTabs: TabId[] = ["holdings"];

  const tabContent: Record<TabId, React.ReactNode> = {
    dashboard: (
      <DashboardTab
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
    sip: <SipCalculatorTab />,
    networth: (
      <NetWorthTab
        currentValue={currentValue}
        availableCash={availableCash}
        totalPnl={totalPnl}
        totalPnlPercent={totalPnlPercent}
        isLoading={isLoading}
      />
    ),
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

  return (
    <div className="h-full bg-surface-base flex flex-col overflow-hidden">
      {/* Header with horizontal tab bar */}
      <div className="border-b border-border-default bg-surface-card shrink-0">
        {/* Title row */}
        <div className="flex items-center justify-between px-6 pt-4 pb-3">
          <div className="flex items-center gap-3">
            <TrendingUp className="w-5 h-5 text-profit" />
            <div>
              <h1 className="font-heading font-bold text-base text-text-primary">
                Investor Dashboard
              </h1>
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

        {/* Horizontal tab bar */}
        <nav
          aria-label="Section navigation"
          className="flex items-end gap-1 px-6 overflow-x-auto scrollbar-none"
        >
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                aria-current={isActive ? "true" : undefined}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-2 text-xs font-sans font-medium transition-colors border-b-2 whitespace-nowrap shrink-0",
                  isActive
                    ? "text-accent border-accent"
                    : "text-text-secondary hover:text-text-primary border-transparent hover:border-border-default",
                )}
              >
                <Icon className="w-3.5 h-3.5 shrink-0" />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Content */}
      {fullHeightTabs.includes(activeTab) ? (
        <TabTransition tabKey={activeTab} className="flex-1 flex flex-col overflow-hidden">
          {tabContent[activeTab]}
        </TabTransition>
      ) : (
        <ScrollArea className="flex-1">
          <TabTransition tabKey={activeTab}>
            <div className="p-6 max-w-5xl">{tabContent[activeTab]}</div>
          </TabTransition>
        </ScrollArea>
      )}
    </div>
  );
}
