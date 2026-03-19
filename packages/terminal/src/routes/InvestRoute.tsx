import { useState, useMemo } from "react";
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
import { useHoldings } from "@/hooks/useHoldings";
import { useFunds } from "@/hooks/useFunds";
import type { Holding } from "@/types/api";
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

function formatPercent(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
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
        <Icon className="w-8 h-8 text-accent-primary" />
      </div>

      <div className="space-y-2 max-w-md">
        <h2 className="text-base font-semibold text-text-primary">{title}</h2>
        <p className="text-sm text-text-secondary leading-relaxed">{description}</p>
      </div>

      <ul className="space-y-2 text-left max-w-sm w-full">
        {bullets.map((b) => (
          <li key={b} className="flex items-start gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-accent-primary mt-1.5 shrink-0" />
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

function AllocationBar({ bands }: { bands: AllocationBand[] }) {
  const total = bands.reduce((a, b) => a + b.value, 0);
  return (
    <div className="space-y-1.5">
      <div className="h-3 w-full flex rounded-full overflow-hidden gap-px bg-border-default">
        {bands.map((b) => (
          <div
            key={b.label}
            className={cn("h-full transition-all duration-500", b.bg)}
            style={{ width: total > 0 ? `${(b.value / total) * 100}%` : "0%" }}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-4">
        {bands.map((b) => (
          <div key={b.label} className="flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", b.bg)} />
            <span className={cn("text-[11px]", b.color)}>{b.label}</span>
            <span className="text-[11px] text-zinc-500 font-mono">
              {total > 0 ? `${((b.value / total) * 100).toFixed(1)}%` : "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
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
    { label: "Equity", value: equityValue, color: "text-blue-400", bg: "bg-blue-600" },
    { label: "Commodity", value: commodityValue, color: "text-amber-400", bg: "bg-amber-500" },
    { label: "Cash", value: availableCash, color: "text-emerald-400", bg: "bg-emerald-600" },
  ].filter((b) => b.value > 0);

  const metrics = [
    {
      label: "Total Portfolio",
      value: isLoading ? "—" : formatINR(currentValue + availableCash),
      sub: "Holdings + Cash",
      positive: null as boolean | null,
      icon: Wallet,
      iconColor: "text-blue-400",
      iconBg: "bg-blue-600/20",
    },
    {
      label: "Invested",
      value: isLoading ? "—" : formatINR(totalInvested),
      sub: "Cost basis",
      positive: null as boolean | null,
      icon: DollarSign,
      iconColor: "text-zinc-400",
      iconBg: "bg-zinc-700/40",
    },
    {
      label: "Current Value",
      value: isLoading ? "—" : formatINR(currentValue),
      sub: "Holdings MTM",
      positive: null as boolean | null,
      icon: TrendingUp,
      iconColor: "text-zinc-400",
      iconBg: "bg-zinc-700/40",
    },
    {
      label: "Total P&L",
      value: isLoading ? "—" : formatINR(totalPnl),
      sub: isLoading ? "" : formatPercent(totalPnlPercent),
      positive: totalPnl >= 0,
      icon: totalPnl >= 0 ? TrendingUp : TrendingDown,
      iconColor: totalPnl >= 0 ? "text-emerald-400" : "text-red-400",
      iconBg: totalPnl >= 0 ? "bg-emerald-600/20" : "bg-red-600/20",
    },
    {
      label: "Available Cash",
      value: isLoading ? "—" : formatINR(availableCash),
      sub: "Withdrawable",
      positive: null as boolean | null,
      icon: Wallet,
      iconColor: "text-emerald-400",
      iconBg: "bg-emerald-600/20",
    },
  ];

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-zinc-500">
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
                <span className="text-[11px] text-zinc-500 uppercase tracking-wide">{m.label}</span>
              </div>
              <div
                className={cn(
                  "font-mono text-sm font-semibold",
                  m.positive === true && "text-emerald-400",
                  m.positive === false && "text-red-400",
                  m.positive === null && "text-zinc-100",
                )}
              >
                {m.value}
              </div>
              {m.sub && (
                <div
                  className={cn(
                    "text-[11px]",
                    m.positive === true && "text-emerald-500",
                    m.positive === false && "text-red-500",
                    m.positive === null && "text-zinc-600",
                  )}
                >
                  {m.sub}
                </div>
              )}
            </Card>
          );
        })}
      </div>

      {/* Allocation breakdown */}
      <Card className="p-5 bg-surface-card border-border-default space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-200">Asset Allocation</h3>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            Derived from live holdings and available cash. Debt / MF requires NAV data source.
          </p>
        </div>

        {bands.length > 0 ? (
          <>
            <AllocationBar bands={bands} />
            <div className="grid grid-cols-1 gap-2">
              {[
                { label: "Equity", value: equityValue, color: "text-blue-400" },
                { label: "Commodity", value: commodityValue, color: "text-amber-400" },
                { label: "Cash", value: availableCash, color: "text-emerald-400" },
              ]
                .filter((r) => r.value > 0)
                .map((r) => (
                  <div
                    key={r.label}
                    className="flex justify-between items-center text-xs"
                  >
                    <span className={cn("font-medium", r.color)}>{r.label}</span>
                    <span className="font-mono text-zinc-300">{formatINR(r.value)}</span>
                  </div>
                ))}
            </div>
          </>
        ) : (
          <div className="text-center py-6 text-zinc-600 text-xs">
            No holdings or cash data available. Connect to OpenAlgo to see allocation.
          </div>
        )}
      </Card>

      <p className="text-[11px] text-zinc-600">
        Holdings refresh every 60s. Cash refreshes every 30s from OpenAlgo.
      </p>
    </div>
  );
}

// ─── 2. Holdings ──────────────────────────────────────────────────────────────

function PnLCell({ value, percent }: { value: number; percent: number }) {
  const pos = value >= 0;
  return (
    <div className={cn("text-right", pos ? "text-emerald-400" : "text-red-400")}>
      <div className="font-mono text-xs font-semibold">{formatINR(value)}</div>
      <div className="font-mono text-[10px] opacity-75">{formatPercent(percent)}</div>
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
            <div className="text-xs font-semibold text-zinc-100 font-mono">
              {row.original.symbol}
            </div>
            <div className="text-[10px] text-zinc-500">{row.original.exchange}</div>
          </div>
        ),
      },
      {
        accessorKey: "quantity",
        header: () => <span className="block text-right">Qty</span>,
        cell: ({ getValue }) => (
          <div className="text-right font-mono text-xs text-zinc-200">
            {(getValue() as number).toLocaleString("en-IN")}
          </div>
        ),
      },
      {
        accessorKey: "averagePrice",
        header: () => <span className="block text-right">Avg Price</span>,
        cell: ({ getValue }) => (
          <div className="text-right font-mono text-xs text-zinc-200">
            {formatINR(getValue() as number)}
          </div>
        ),
      },
      {
        accessorKey: "ltp",
        header: () => <span className="block text-right">LTP</span>,
        cell: ({ getValue }) => (
          <div className="text-right font-mono text-xs text-zinc-100 font-semibold">
            {formatINR(getValue() as number)}
          </div>
        ),
      },
      {
        id: "invested",
        header: () => <span className="block text-right">Invested</span>,
        accessorFn: (row) => row.averagePrice * row.quantity,
        cell: ({ getValue }) => (
          <div className="text-right font-mono text-xs text-zinc-400">
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
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-zinc-500">
        <RefreshCw className="size-5 animate-spin" />
        <span className="text-sm">Fetching holdings from OpenAlgo...</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-zinc-500">
        <AlertCircle className="size-5 text-red-500" />
        <span className="text-sm">Failed to load holdings.</span>
        <Button variant="outline" size="sm" onClick={refetch} className="text-xs">
          Retry
        </Button>
      </div>
    );
  }

  if (holdings.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-zinc-500">
        <BarChart3 className="size-8 text-zinc-700" />
        <span className="text-sm font-medium text-zinc-400">No holdings found</span>
        <span className="text-xs text-zinc-600 max-w-sm text-center">
          Buy equities via your broker (via OpenAlgo) and they will appear here after settlement.
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-2 py-2 border-b border-border-default">
        <span className="text-xs text-zinc-500">
          {holdings.length} stock{holdings.length !== 1 ? "s" : ""}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={refetch}
          className="text-xs text-zinc-500 h-6 px-2 gap-1"
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
                    className="h-8 text-[11px] font-medium text-zinc-500 uppercase tracking-wide cursor-pointer select-none"
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
      <div className="border-t border-border-default bg-surface-card px-4 py-2 grid grid-cols-6 gap-2 text-xs font-mono">
        <span className="text-zinc-400 font-semibold col-span-1">Total</span>
        <span className="text-right text-zinc-500" />
        <span className="text-right text-zinc-500" />
        <span className="text-right text-zinc-500" />
        <span className="text-right text-zinc-400">{formatINR(totalInvested)}</span>
        <div className={cn("text-right", totalPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
          <div className="font-semibold">{formatINR(totalPnl)}</div>
          <div className="text-[10px] opacity-75">
            {formatPercent(totalPnlPct)} on {formatINR(totalCurrent)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── 3. Net Worth ─────────────────────────────────────────────────────────────

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
  // Equity from live data, others are placeholders pending data sources
  const categories = [
    {
      label: "Equity Holdings",
      value: isLoading ? null : currentValue,
      note: "Live from OpenAlgo",
      color: "text-blue-400",
      bg: "bg-blue-600/20",
      icon: TrendingUp,
    },
    {
      label: "Available Cash",
      value: isLoading ? null : availableCash,
      note: "Live from OpenAlgo",
      color: "text-emerald-400",
      bg: "bg-emerald-600/20",
      icon: Wallet,
    },
    {
      label: "Mutual Funds",
      value: null,
      note: "Connect NAV source in Settings",
      color: "text-purple-400",
      bg: "bg-purple-600/20",
      icon: BarChart3,
    },
    {
      label: "Gold",
      value: null,
      note: "Manual entry — coming v0.2.0",
      color: "text-amber-400",
      bg: "bg-amber-600/20",
      icon: Globe,
    },
    {
      label: "Fixed Deposits",
      value: null,
      note: "Manual entry — coming v0.2.0",
      color: "text-cyan-400",
      bg: "bg-cyan-600/20",
      icon: DollarSign,
    },
  ];

  const knownTotal = (isLoading ? 0 : currentValue) + (isLoading ? 0 : availableCash);

  return (
    <div className="space-y-5 max-w-lg">
      <div>
        <h3 className="text-sm font-semibold text-zinc-200">Net Worth Breakdown</h3>
        <p className="text-xs text-zinc-500 mt-0.5">
          Live equity and cash from OpenAlgo. Other asset classes require additional data sources
          or manual entry.
        </p>
      </div>

      {/* Known total */}
      <Card className="p-5 bg-surface-card border-border-default">
        <div className="text-[11px] text-zinc-500 uppercase tracking-wide mb-1">
          Known Total (Equity + Cash)
        </div>
        <div
          className={cn(
            "font-mono text-xl font-bold",
            isLoading ? "text-zinc-500" : "text-zinc-100",
          )}
        >
          {isLoading ? "—" : formatINR(knownTotal)}
        </div>
        {!isLoading && (
          <div
            className={cn(
              "text-sm font-mono mt-1",
              totalPnl >= 0 ? "text-emerald-400" : "text-red-400",
            )}
          >
            {formatINR(totalPnl)}{" "}
            <span className="text-xs opacity-75">({formatPercent(totalPnlPercent)} unrealised)</span>
          </div>
        )}
      </Card>

      {/* Per-category cards */}
      <div className="space-y-3">
        {categories.map((cat) => {
          const Icon = cat.icon;
          return (
            <div
              key={cat.label}
              className="flex items-center gap-3 p-3 rounded-lg bg-surface-card border border-border-default"
            >
              <div
                className={cn(
                  "size-8 rounded-lg flex items-center justify-center shrink-0",
                  cat.bg,
                )}
              >
                <Icon className={cn("size-4", cat.color)} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold text-zinc-200">{cat.label}</div>
                <div className="text-[11px] text-zinc-500">{cat.note}</div>
              </div>
              <div className="text-right shrink-0">
                {cat.value !== null ? (
                  <span className="font-mono text-xs text-zinc-100">
                    {formatINR(cat.value)}
                  </span>
                ) : (
                  <Badge
                    variant="outline"
                    className="text-[10px] border-border-default text-zinc-600"
                  >
                    —
                  </Badge>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── 4. Mutual Funds ──────────────────────────────────────────────────────────

const MF_CATEGORIES = [
  {
    name: "Large Cap",
    risk: "Low",
    desc: "Top 100 companies by market cap. Stable, lower volatility. Suited for conservative investors.",
    color: "text-blue-400",
  },
  {
    name: "Mid Cap",
    risk: "Medium",
    desc: "101–250 by market cap. Higher growth potential with moderate risk over 5+ year horizon.",
    color: "text-amber-400",
  },
  {
    name: "Small Cap",
    risk: "High",
    desc: "251+ by market cap. Aggressive growth potential, higher drawdown risk. Long horizon only.",
    color: "text-red-400",
  },
  {
    name: "ELSS",
    risk: "Medium",
    desc: "Equity Linked Savings Scheme. 3-year lock-in, eligible for 80C tax deduction up to ₹1.5L.",
    color: "text-purple-400",
  },
  {
    name: "Debt / Liquid",
    risk: "Low",
    desc: "Government bonds, T-bills, corporate debt. Capital preservation, short investment horizon.",
    color: "text-emerald-400",
  },
  {
    name: "Hybrid / Balanced",
    risk: "Low–Med",
    desc: "Mix of equity and debt. Suited for moderate risk appetite, automatic rebalancing.",
    color: "text-cyan-400",
  },
];

const RISK_COLOR: Record<string, string> = {
  Low: "bg-emerald-900/40 text-emerald-400 border-emerald-800",
  Medium: "bg-amber-900/40 text-amber-400 border-amber-800",
  High: "bg-red-900/40 text-red-400 border-red-800",
  "Low–Med": "bg-cyan-900/40 text-cyan-400 border-cyan-800",
};

function MutualFundsTab() {
  return (
    <div className="space-y-5 max-w-2xl">
      <div className="flex items-start gap-3 bg-surface-card border border-border-default rounded-lg p-4">
        <AlertCircle className="size-4 text-amber-400 mt-0.5 shrink-0" />
        <div className="space-y-1">
          <p className="text-xs font-medium text-zinc-200">Live NAV not connected</p>
          <p className="text-xs text-zinc-500">
            Connect a NAV data source in{" "}
            <span className="text-amber-400 font-mono">Settings → Data Sources</span> to see
            portfolio NAV, returns, and folios. jugaad-data or mftool can be configured as the
            source in v0.2.0.
          </p>
        </div>
      </div>

      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-zinc-200">SEBI-Defined MF Categories</h3>
        <p className="text-xs text-zinc-500">
          Risk ratings are indicative based on SEBI&apos;s product labelling guidelines.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {MF_CATEGORIES.map((cat) => (
          <div
            key={cat.name}
            className="bg-surface-card border border-border-default rounded-lg p-4 space-y-2"
          >
            <div className="flex items-center justify-between">
              <span className={cn("text-sm font-semibold", cat.color)}>{cat.name}</span>
              <Badge
                variant="outline"
                className={cn("text-[10px] h-5", RISK_COLOR[cat.risk])}
              >
                {cat.risk} risk
              </Badge>
            </div>
            <p className="text-[11px] text-zinc-500 leading-relaxed">{cat.desc}</p>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-center pt-2">
        <Badge className="bg-amber-500/20 text-amber-400 border-amber-700/50 text-xs gap-1">
          <Bell className="w-3 h-3" />
          Full MF dashboard coming in v0.2.0
        </Badge>
      </div>
    </div>
  );
}

// ─── 5. SIP Calculator ────────────────────────────────────────────────────────

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
    return { invested, maturity, returns, progress };
  }, [monthly, rate, years]);

  return (
    <div className="max-w-xl space-y-6">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-zinc-200">SIP Calculator</h3>
        <p className="text-xs text-zinc-500">
          Estimate future corpus from regular monthly investments using compound interest.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label className="text-xs text-zinc-400">Monthly SIP (INR)</Label>
          <Input
            type="number"
            value={monthly}
            onChange={(e) => setMonthly(e.target.value)}
            min="100"
            step="500"
            className="bg-surface-card border-border-default text-zinc-100 font-mono text-sm h-9"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-zinc-400">Expected Return (%/yr)</Label>
          <Input
            type="number"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            min="1"
            max="30"
            step="0.5"
            className="bg-surface-card border-border-default text-zinc-100 font-mono text-sm h-9"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-zinc-400">Duration (years)</Label>
          <Input
            type="number"
            value={years}
            onChange={(e) => setYears(e.target.value)}
            min="1"
            max="40"
            step="1"
            className="bg-surface-card border-border-default text-zinc-100 font-mono text-sm h-9"
          />
        </div>
      </div>

      {result ? (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-px bg-border-default rounded-lg overflow-hidden">
            <div className="bg-surface-card p-4 space-y-1">
              <span className="text-[11px] text-zinc-500 uppercase tracking-wide">
                Total Invested
              </span>
              <div className="font-mono text-sm font-semibold text-zinc-100">
                {formatINR(result.invested)}
              </div>
            </div>
            <div className="bg-surface-card p-4 space-y-1">
              <span className="text-[11px] text-zinc-500 uppercase tracking-wide">
                Est. Returns
              </span>
              <div className="font-mono text-sm font-semibold text-emerald-400">
                {formatINR(result.returns)}
              </div>
            </div>
            <div className="bg-surface-card p-4 space-y-1">
              <span className="text-[11px] text-zinc-500 uppercase tracking-wide">
                Maturity Value
              </span>
              <div className="font-mono text-sm font-semibold text-zinc-100">
                {formatINR(result.maturity)}
              </div>
            </div>
          </div>

          {/* Stacked bar */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-[11px] text-zinc-500">
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
            <div className="flex justify-between text-[11px]">
              <span className="text-blue-400">
                {(100 - result.progress).toFixed(1)}% principal
              </span>
              <span className="text-emerald-400">{result.progress.toFixed(1)}% gains</span>
            </div>
          </div>

          <p className="text-[11px] text-zinc-600 leading-relaxed">
            Investing {formatINR(parseFloat(monthly) || 0)}/month for {years} years at {rate}%
            p.a. compounds to {formatINR(result.maturity)}. Actual MF returns vary; this is an
            illustrative projection only.
          </p>
        </div>
      ) : (
        <div className="text-center py-8 text-zinc-600 text-xs">
          Enter values above to calculate.
        </div>
      )}
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
  if (r >= 0) return "bg-zinc-700 text-zinc-200";
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
        <h3 className="text-sm font-semibold text-zinc-200">Asset Quilt — Annual Returns</h3>
        <p className="text-xs text-zinc-500">
          Calendar-year returns ranked from best (top) to worst (bottom). Illustrative data
          based on approximate index returns. Connect a data source for live NAV-based returns.
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
              className="text-center text-[11px] font-semibold text-zinc-400 pb-1 border-b border-border-default"
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
                  <div className="text-[10px] font-semibold leading-tight truncate">
                    {asset.name}
                  </div>
                  <div className="font-mono text-[11px] font-bold">
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

      <p className="text-[11px] text-zinc-600 leading-relaxed">
        Data is approximate and illustrative. NIFTY returns are index-only (no dividends).
        REIT data available from 2021 onwards. Connect jugaad-data or mftool in Settings for
        live NAV-based quilt.
      </p>

      {/* Legend */}
      <div className="flex flex-wrap gap-2">
        {[
          { label: "≥40%", cls: "bg-emerald-400" },
          { label: "20–40%", cls: "bg-emerald-600" },
          { label: "10–20%", cls: "bg-emerald-800" },
          { label: "0–10%", cls: "bg-zinc-700" },
          { label: "-10–0%", cls: "bg-red-900" },
          { label: "<-10%", cls: "bg-red-700" },
        ].map((l) => (
          <div key={l.label} className="flex items-center gap-1.5">
            <span className={cn("size-3 rounded", l.cls)} />
            <span className="text-[11px] text-zinc-500">{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 7–10. Placeholder tabs ───────────────────────────────────────────────────

function SectorRotationTab() {
  return (
    <PlaceholderTab
      icon={RotateCcw}
      title="Sector Rotation (RRG)"
      version="v0.2.0"
      description="Relative Rotation Graph (RRG) shows the momentum and strength of NIFTY sectors relative
      to the benchmark. Sectors cycle through Leading, Weakening, Lagging, and Improving quadrants
      — helping you identify rotation opportunities before they play out."
      bullets={[
        "RRG chart: all 13 NSE sectors plotted on momentum vs. relative strength axes",
        "Quadrant view: Leading / Weakening / Lagging / Improving with tail trails",
        "Configurable look-back: 1D, 1W, 2W, 1M relative strength window",
        "Top performing sectors ranked by absolute and relative returns",
        "Data source: OpenAlgo + jugaad-data OHLCV (no external API required)",
      ]}
    />
  );
}

function EtfScreenerTab() {
  return (
    <PlaceholderTab
      icon={Filter}
      title="ETF Screener"
      version="v0.2.0"
      description="Screen and compare Indian ETFs (NSE/BSE) across expense ratio, AUM, tracking error,
      1Y/3Y/5Y returns, and liquidity. Filter by category — equity, debt, gold, international,
      or thematic — to find the best ETF for your portfolio."
      bullets={[
        "Filterable table: category, AUM, expense ratio, volume, tracking error",
        "Returns comparison: 1M / 3M / 6M / 1Y / 3Y / 5Y vs. benchmark",
        "Holdings drill-down: top 10 holdings, sector weights for equity ETFs",
        "Liquidity gauge: average daily volume and bid-ask spread indicator",
        "Data from NSE/BSE instrument list + jugaad-data NAV pipeline",
      ]}
    />
  );
}

function StockScreenerTab() {
  return (
    <PlaceholderTab
      icon={Search}
      title="Stock Screener"
      version="v0.2.0"
      description="Screen NSE/BSE stocks by fundamental and technical filters. Build custom screens
      combining valuation (P/E, P/B, ROE), quality (debt/equity, promoter holding), and
      momentum (52W high/low, RSI, price vs. moving averages) criteria."
      bullets={[
        "200+ screening parameters across fundamentals, technicals, and ownership",
        "Pre-built screens: CANSLIM, Magic Formula, Piotroski, 52W breakouts",
        "Save and schedule screens — run daily and get Telegram alerts",
        "Export to CSV or open directly in Chart or Trade widget",
        "Data: OpenAlgo OHLCV + screener Python package (included in monorepo)",
      ]}
    />
  );
}

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
    stocks: <StockScreenerTab />,
    ipo: <IpoTrackerTab />,
  };

  // Holdings-only tabs render their own scroll/overflow — wrap them differently
  const fullHeightTabs: TabId[] = ["holdings"];

  return (
    <div className="min-h-screen bg-surface-base">
      {/* Header */}
      <div className="border-b border-border-default bg-surface-card px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <TrendingUp className="w-6 h-6 text-emerald-400" />
            <div>
              <h1 className="text-lg font-bold text-text-primary">Investor Dashboard</h1>
              <p className="text-xs text-text-muted">
                Portfolio, holdings, net worth, and investment tools
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isLoading && <RefreshCw className="size-3 text-zinc-500 animate-spin" />}
            {!isLoading && (
              <Badge
                variant="outline"
                className="text-[10px] h-5 border-border-default text-zinc-500"
              >
                {holdings.length} holdings
              </Badge>
            )}
          </div>
        </div>
      </div>

      {/* Body: sidebar + content */}
      <div className="flex h-[calc(100vh-73px)]">
        {/* Sidebar */}
        <div className="w-56 border-r border-border-default bg-surface-card shrink-0 py-2">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                  isActive
                    ? "bg-accent-primary/10 text-accent-primary border-r-2 border-accent-primary"
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
