import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  BarChart3,
  Calculator,
  PieChart,
  RefreshCw,
  AlertCircle,
} from "lucide-react";

// ─── Formatters ──────────────────────────────────────────────────────────────

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

// ─── Net Worth Summary Bar ────────────────────────────────────────────────────

interface SummaryMetric {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean | null;
}

function NetWorthBar({
  totalInvested,
  currentValue,
  totalPnl,
  totalPnlPercent,
  dayChange,
  availableCash,
  isLoading,
}: {
  totalInvested: number;
  currentValue: number;
  totalPnl: number;
  totalPnlPercent: number;
  dayChange: number;
  availableCash: number;
  isLoading: boolean;
}) {
  const metrics: SummaryMetric[] = [
    {
      label: "Net Worth",
      value: isLoading ? "—" : formatINR(currentValue + availableCash),
      sub: "Holdings + Cash",
      positive: null,
    },
    {
      label: "Invested",
      value: isLoading ? "—" : formatINR(totalInvested),
      sub: "Cost basis",
      positive: null,
    },
    {
      label: "Current Value",
      value: isLoading ? "—" : formatINR(currentValue),
      sub: "Holdings MTM",
      positive: null,
    },
    {
      label: "Total P&L",
      value: isLoading ? "—" : formatINR(totalPnl),
      sub: isLoading ? "" : formatPercent(totalPnlPercent),
      positive: totalPnl >= 0,
    },
    {
      label: "Day Change",
      value: isLoading ? "—" : formatINR(dayChange),
      sub: "Today",
      positive: dayChange >= 0,
    },
    {
      label: "Available Cash",
      value: isLoading ? "—" : formatINR(availableCash),
      sub: "Withdrawable",
      positive: null,
    },
  ];

  return (
    <div className="grid grid-cols-3 lg:grid-cols-6 gap-px bg-border-default border-b border-border-default">
      {metrics.map((m) => (
        <div
          key={m.label}
          className="bg-surface-base px-4 py-3 flex flex-col gap-0.5"
        >
          <span className="text-[11px] font-medium text-zinc-500 uppercase tracking-wide">
            {m.label}
          </span>
          <span
            className={cn(
              "font-mono text-sm font-semibold",
              m.positive === true && "text-emerald-400",
              m.positive === false && "text-red-400",
              m.positive === null && "text-zinc-100",
            )}
          >
            {m.value}
          </span>
          {m.sub && (
            <span
              className={cn(
                "text-[11px]",
                m.positive === true && "text-emerald-500",
                m.positive === false && "text-red-500",
                m.positive === null && "text-zinc-600",
              )}
            >
              {m.sub}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Holdings Tab ─────────────────────────────────────────────────────────────

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

  // Totals row
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
          Buy equities via your broker (via OpenAlgo) and they will appear here after
          settlement.
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border-default">
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
        <span className="text-right text-zinc-500"></span>
        <span className="text-right text-zinc-500"></span>
        <span className="text-right text-zinc-500"></span>
        <span className="text-right text-zinc-400">{formatINR(totalInvested)}</span>
        <div className={cn("text-right", totalPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
          <div className="font-semibold">{formatINR(totalPnl)}</div>
          <div className="text-[10px] opacity-75">
            {formatPercent(totalPnlPct)}
            {" "}on {formatINR(totalCurrent)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── SIP Calculator Tab ───────────────────────────────────────────────────────

function SipCalculator() {
  const [monthly, setMonthly] = useState<string>("5000");
  const [rate, setRate] = useState<string>("12");
  const [years, setYears] = useState<string>("10");

  const result = useMemo(() => {
    const P = parseFloat(monthly) || 0;
    const r = (parseFloat(rate) || 0) / 100 / 12;
    const n = (parseFloat(years) || 0) * 12;
    if (P <= 0 || n <= 0) return null;
    const invested = P * n;
    // Standard SIP FV formula: P * ((1+r)^n - 1) / r * (1+r)
    const maturity =
      r > 0 ? P * ((Math.pow(1 + r, n) - 1) / r) * (1 + r) : invested;
    const returns = maturity - invested;
    const progress = invested > 0 ? Math.min((returns / maturity) * 100, 100) : 0;
    return { invested, maturity, returns, progress };
  }, [monthly, rate, years]);

  return (
    <div className="p-6 max-w-xl mx-auto space-y-6">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-zinc-200">SIP Calculator</h3>
        <p className="text-xs text-zinc-500">
          Estimate corpus from regular monthly investments using compound interest.
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

          {/* Progress bar: invested vs returns */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-[11px] text-zinc-500">
              <span>Invested</span>
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
              <span className="text-emerald-400">
                {result.progress.toFixed(1)}% gains
              </span>
            </div>
          </div>

          <p className="text-[11px] text-zinc-600 leading-relaxed">
            Investing {formatINR(parseFloat(monthly) || 0)}/month for {years} years at{" "}
            {rate}% p.a. compounds to {formatINR(result.maturity)}. Returns are
            illustrative; actual MF returns vary.
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

// ─── Mutual Funds Tab (placeholder) ──────────────────────────────────────────

const MF_CATEGORIES = [
  {
    name: "Large Cap",
    risk: "Low",
    desc: "Top 100 companies by market cap. Stable, lower volatility.",
    color: "text-blue-400",
  },
  {
    name: "Mid Cap",
    risk: "Medium",
    desc: "101–250 by market cap. Higher growth potential, moderate risk.",
    color: "text-amber-400",
  },
  {
    name: "Small Cap",
    risk: "High",
    desc: "251+ by market cap. Aggressive growth, higher drawdown risk.",
    color: "text-red-400",
  },
  {
    name: "ELSS",
    risk: "Medium",
    desc: "Equity Linked Savings Scheme. 3-yr lock-in, 80C tax benefit.",
    color: "text-purple-400",
  },
  {
    name: "Debt / Liquid",
    risk: "Low",
    desc: "Government bonds, T-bills. Capital preservation, short horizon.",
    color: "text-emerald-400",
  },
  {
    name: "Hybrid / Balanced",
    risk: "Low–Med",
    desc: "Mix of equity and debt. Suited for moderate risk appetite.",
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
    <div className="p-6 space-y-4 max-w-2xl">
      {/* Connect notice */}
      <div className="flex items-start gap-3 bg-surface-card border border-border-default rounded-lg p-4">
        <AlertCircle className="size-4 text-amber-400 mt-0.5 shrink-0" />
        <div className="space-y-1">
          <p className="text-xs font-medium text-zinc-200">Live NAV not connected</p>
          <p className="text-xs text-zinc-500">
            Connect a NAV data source in{" "}
            <span className="text-amber-400 font-mono">Settings → Data Sources</span> to
            see portfolio NAV, returns, and folios. jugaad-data or mftool can be
            configured.
          </p>
        </div>
      </div>

      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-zinc-200">Indian MF Categories</h3>
        <p className="text-xs text-zinc-500">
          SEBI-defined equity mutual fund categories. Risk ratings are indicative.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
    </div>
  );
}

// ─── Asset Allocation Tab ─────────────────────────────────────────────────────

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
      <div className="flex flex-wrap gap-3">
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

function AssetAllocationTab({
  holdings,
  availableCash,
  isLoading,
}: {
  holdings: Holding[];
  availableCash: number;
  isLoading: boolean;
}) {
  const equityValue = useMemo(
    () => holdings.reduce((acc, h) => acc + h.ltp * h.quantity, 0),
    [holdings],
  );

  // Rough heuristic: NSE/BSE holdings = equity, MCX prefix = commodity
  const commodityValue = useMemo(
    () =>
      holdings
        .filter((h) => h.exchange.startsWith("MCX"))
        .reduce((acc, h) => acc + h.ltp * h.quantity, 0),
    [holdings],
  );
  const pureEquity = equityValue - commodityValue;
  const cash = availableCash;
  const total = pureEquity + commodityValue + cash;

  const bands: AllocationBand[] = [
    {
      label: "Equity",
      value: pureEquity,
      color: "text-blue-400",
      bg: "bg-blue-600",
    },
    {
      label: "Commodity",
      value: commodityValue,
      color: "text-amber-400",
      bg: "bg-amber-500",
    },
    {
      label: "Cash",
      value: cash,
      color: "text-emerald-400",
      bg: "bg-emerald-600",
    },
  ].filter((b) => b.value > 0);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-zinc-500">
        <RefreshCw className="size-5 animate-spin" />
        <span className="text-sm">Loading allocation data...</span>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-xl">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-zinc-200">Asset Allocation</h3>
        <p className="text-xs text-zinc-500">
          Derived from live holdings and available cash. Debt funds require NAV data
          source.
        </p>
      </div>

      {total > 0 ? (
        <>
          <AllocationBar bands={bands} />

          <div className="grid grid-cols-1 gap-3">
            {[
              {
                label: "Equity",
                value: pureEquity,
                icon: TrendingUp,
                color: "text-blue-400",
                bg: "bg-blue-600",
              },
              {
                label: "Commodity",
                value: commodityValue,
                icon: BarChart3,
                color: "text-amber-400",
                bg: "bg-amber-500",
              },
              {
                label: "Cash",
                value: cash,
                icon: Wallet,
                color: "text-emerald-400",
                bg: "bg-emerald-600",
              },
            ]
              .filter((row) => row.value > 0)
              .map((row) => {
                const pct = total > 0 ? (row.value / total) * 100 : 0;
                const Icon = row.icon;
                return (
                  <div
                    key={row.label}
                    className="bg-surface-card border border-border-default rounded-lg p-4 flex items-center gap-4"
                  >
                    <div
                      className={cn(
                        "size-8 rounded-lg flex items-center justify-center",
                        row.bg,
                        "bg-opacity-20",
                      )}
                    >
                      <Icon className={cn("size-4", row.color)} />
                    </div>
                    <div className="flex-1 space-y-1">
                      <div className="flex justify-between items-baseline">
                        <span className={cn("text-xs font-semibold", row.color)}>
                          {row.label}
                        </span>
                        <span className="font-mono text-xs text-zinc-100 font-semibold">
                          {formatINR(row.value)}
                        </span>
                      </div>
                      <div className="h-1.5 w-full bg-border-default rounded-full overflow-hidden">
                        <div
                          className={cn("h-full rounded-full transition-all", row.bg)}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="text-[11px] text-zinc-500">
                        {pct.toFixed(1)}% of portfolio
                      </span>
                    </div>
                  </div>
                );
              })}
          </div>

          <div className="text-[11px] text-zinc-600 leading-relaxed">
            Debt allocation requires a connected NAV data source. Configure in Settings
            to see full allocation including mutual funds and bonds.
          </div>
        </>
      ) : (
        <div className="flex flex-col items-center justify-center h-48 gap-3 text-zinc-600">
          <PieChart className="size-8 text-zinc-700" />
          <span className="text-sm font-medium text-zinc-500">No allocation data</span>
          <span className="text-xs text-center max-w-xs">
            Holdings and funds data will appear here once connected to OpenAlgo.
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function InvestRoute() {
  const {
    data: holdings = [],
    isLoading: holdingsLoading,
    isError: holdingsError,
    refetch: refetchHoldings,
  } = useHoldings();

  const { data: funds, isLoading: fundsLoading } = useFunds();

  const isLoading = holdingsLoading || fundsLoading;
  const availableCash = funds?.availableCash ?? 0;

  // Aggregate net worth metrics
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

  // Day change: LTP vs previous close — OpenAlgo holdings don't carry prev close,
  // so we approximate as sum of pnl (which reflects unrealised since avg price).
  // Real day change would need a quote call; leave as 0 if no data.
  const dayChange = 0;

  return (
    <div className="h-screen flex flex-col bg-surface-base text-zinc-100 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default shrink-0">
        <div className="flex items-center gap-2">
          <TrendingUp className="size-4 text-emerald-400" />
          <span className="text-sm font-semibold text-zinc-100">Investor Dashboard</span>
        </div>
        <div className="flex items-center gap-2">
          {isLoading && (
            <RefreshCw className="size-3 text-zinc-500 animate-spin" />
          )}
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

      {/* Net Worth Summary Bar */}
      <NetWorthBar
        totalInvested={totalInvested}
        currentValue={currentValue}
        totalPnl={totalPnl}
        totalPnlPercent={totalPnlPercent}
        dayChange={dayChange}
        availableCash={availableCash}
        isLoading={isLoading}
      />

      {/* Tab Body */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <Tabs defaultValue="holdings" className="flex flex-col h-full">
          <div className="px-4 pt-3 pb-0 border-b border-border-default shrink-0">
            <TabsList className="bg-transparent h-8 p-0 gap-0" variant="line">
              <TabsTrigger value="holdings" className="gap-1.5 text-xs px-3">
                <BarChart3 className="size-3" />
                Holdings
              </TabsTrigger>
              <TabsTrigger value="sip" className="gap-1.5 text-xs px-3">
                <Calculator className="size-3" />
                SIP Calculator
              </TabsTrigger>
              <TabsTrigger value="mf" className="gap-1.5 text-xs px-3">
                <TrendingDown className="size-3" />
                Mutual Funds
              </TabsTrigger>
              <TabsTrigger value="allocation" className="gap-1.5 text-xs px-3">
                <PieChart className="size-3" />
                Allocation
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="holdings" className="flex-1 overflow-hidden mt-0">
            <HoldingsTab
              holdings={holdings}
              isLoading={holdingsLoading}
              isError={holdingsError}
              refetch={refetchHoldings}
            />
          </TabsContent>

          <TabsContent value="sip" className="flex-1 overflow-auto mt-0">
            <SipCalculator />
          </TabsContent>

          <TabsContent value="mf" className="flex-1 overflow-auto mt-0">
            <MutualFundsTab />
          </TabsContent>

          <TabsContent value="allocation" className="flex-1 overflow-auto mt-0">
            <AssetAllocationTab
              holdings={holdings}
              availableCash={availableCash}
              isLoading={isLoading}
            />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
