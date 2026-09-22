/**
 * SocialTab.tsx
 *
 * Local strategy library foundation — profile rankings + reusable templates.
 * Fetches data from /ft-api/v1/strategy-library/* endpoints.
 *
 * Two sections:
 *   1. Profile rankings: TanStack Table of sample strategy profiles ranked by return %
 *   2. Library: GlassCard grid of reusable strategy templates with Add button
 */

import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getBase, buildHeaders } from "@/services/ftApi.helpers";
import {
  Trophy,
  Users,
  Copy,
  TrendingUp,
  Shield,
  BarChart3,
  RefreshCw,
  Star,
  Filter,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import { StaggeredList } from "@/components/motion/StaggeredList";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

interface TraderRow {
  rank: number;
  user_id: string;
  display_name: string;
  strategy_count: number;
  win_rate: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  follower_count: number;
  trades_count: number;
  active_since: string;
  risk_score: number;
}

interface StrategyCard {
  strategy_id: string;
  creator_id: string;
  name: string;
  description: string;
  category: string;
  instruments: string[];
  backtest_sharpe: number;
  backtest_return_pct: number;
  backtest_max_dd_pct: number;
  live_return_pct: number;
  follower_count: number;
  created_at: string;
}

interface LeaderboardResponse {
  status: string;
  data: { traders: TraderRow[] };
}

interface StrategiesResponse {
  status: string;
  data: { strategies: StrategyCard[] };
}

// ── Demo data (seeded from local strategy-library sample data) ───────────────

const DEMO_TRADERS: TraderRow[] = [
  { rank: 1, user_id: "demo_1", display_name: "NiftyScalper", strategy_count: 3, win_rate: 68.5, total_return_pct: 42.3, max_drawdown_pct: 8.2, sharpe_ratio: 2.15, follower_count: 1240, trades_count: 2850, active_since: "2023-04-15", risk_score: 3 },
  { rank: 2, user_id: "demo_2", display_name: "OptionsMaster", strategy_count: 5, win_rate: 72.1, total_return_pct: 38.7, max_drawdown_pct: 12.5, sharpe_ratio: 1.89, follower_count: 980, trades_count: 1920, active_since: "2022-11-01", risk_score: 4 },
  { rank: 3, user_id: "demo_3", display_name: "SwingTraderPro", strategy_count: 2, win_rate: 61.3, total_return_pct: 31.2, max_drawdown_pct: 6.8, sharpe_ratio: 1.72, follower_count: 756, trades_count: 890, active_since: "2023-08-20", risk_score: 2 },
  { rank: 4, user_id: "demo_4", display_name: "BankNiftyKing", strategy_count: 4, win_rate: 65.8, total_return_pct: 28.9, max_drawdown_pct: 15.3, sharpe_ratio: 1.45, follower_count: 620, trades_count: 3100, active_since: "2024-01-10", risk_score: 5 },
  { rank: 5, user_id: "demo_5", display_name: "ValueInvestor", strategy_count: 1, win_rate: 78.2, total_return_pct: 24.5, max_drawdown_pct: 4.1, sharpe_ratio: 2.35, follower_count: 1580, trades_count: 145, active_since: "2022-06-15", risk_score: 1 },
];

const DEMO_STRATEGIES: StrategyCard[] = [
  { strategy_id: "demo_s1", creator_id: "demo_1", name: "Nifty ORB Scalper", description: "Opening range breakout strategy on Nifty futures with tight stop-losses. Best for first 90 mins of trading.", category: "intraday", instruments: ["NIFTY", "BANKNIFTY"], backtest_sharpe: 1.95, backtest_return_pct: 34.2, backtest_max_dd_pct: 7.5, live_return_pct: 28.1, follower_count: 890, created_at: "2024-06-15" },
  { strategy_id: "demo_s2", creator_id: "demo_2", name: "Iron Condor Weekly", description: "Weekly iron condor on Nifty index with delta-neutral adjustments. Targets theta decay.", category: "options", instruments: ["NIFTY"], backtest_sharpe: 1.62, backtest_return_pct: 22.8, backtest_max_dd_pct: 11.2, live_return_pct: 18.5, follower_count: 650, created_at: "2024-03-20" },
  { strategy_id: "demo_s3", creator_id: "demo_3", name: "Momentum Swing", description: "RSI + MACD crossover on top 50 stocks. Holds 3-10 days with trailing SL.", category: "swing", instruments: ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"], backtest_sharpe: 1.48, backtest_return_pct: 26.5, backtest_max_dd_pct: 9.8, live_return_pct: 21.3, follower_count: 420, created_at: "2024-08-10" },
  { strategy_id: "demo_s4", creator_id: "demo_5", name: "Quality Value Pick", description: "Quarterly rebalanced portfolio of high-ROCE, low-debt stocks with margin of safety.", category: "investment", instruments: ["RELIANCE", "TCS", "BHARTIARTL", "ITC", "LT", "SBIN"], backtest_sharpe: 2.10, backtest_return_pct: 19.8, backtest_max_dd_pct: 5.2, live_return_pct: 16.7, follower_count: 1120, created_at: "2023-12-01" },
  { strategy_id: "demo_s5", creator_id: "demo_4", name: "BankNifty Straddle", description: "Short straddle on BankNifty expiry day with adjustment rules. High win rate, requires active management.", category: "options", instruments: ["BANKNIFTY"], backtest_sharpe: 1.35, backtest_return_pct: 41.5, backtest_max_dd_pct: 18.2, live_return_pct: 32.8, follower_count: 340, created_at: "2024-09-05" },
  { strategy_id: "demo_s6", creator_id: "demo_1", name: "Gap & Go", description: "Catches gap-up/gap-down moves in liquid stocks during market open. 15-min timeframe.", category: "intraday", instruments: ["NIFTY", "RELIANCE", "HDFCBANK"], backtest_sharpe: 1.78, backtest_return_pct: 29.3, backtest_max_dd_pct: 10.1, live_return_pct: 23.6, follower_count: 560, created_at: "2024-07-22" },
];

// ── API helpers ──────────────────────────────────────────────────────────────

// Resolve the backend base through the canonical helper so library calls behave
// identically in dev (Vite proxy) and the packaged desktop app (same origin),
// and carry the standard auth headers (X-API-Key + JWT) like every other
// FT-API caller.
const FT_API_BASE = `${getBase()}/v1`;

async function fetchProfileRankings(metric: string): Promise<TraderRow[]> {
  const res = await fetch(
    `${FT_API_BASE}/strategy-library/profile-rankings?metric=${metric}&limit=20`,
    { headers: buildHeaders(false) },
  );
  if (!res.ok) throw new Error("Failed to fetch profile rankings");
  const json: LeaderboardResponse = await res.json();
  return json.data.traders;
}

async function fetchStrategies(category: string | null): Promise<StrategyCard[]> {
  const params = new URLSearchParams({ limit: "50" });
  if (category) params.set("category", category);
  const res = await fetch(`${FT_API_BASE}/strategy-library/templates?${params.toString()}`, {
    headers: buildHeaders(false),
  });
  if (!res.ok) throw new Error("Failed to fetch strategies");
  const json: StrategiesResponse = await res.json();
  return json.data.strategies;
}

async function addStrategyTemplate(
  strategyId: string,
  userId: string,
): Promise<{ status: string; message: string }> {
  const res = await fetch(`${FT_API_BASE}/strategy-library/templates/add`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify({ strategy_id: strategyId, user_id: userId }),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.message ?? "Add failed");
  return json.data;
}

// ── Risk badge helper ────────────────────────────────────────────────────────

function RiskBadge({ score }: { score: number }) {
  const config: Record<number, { label: string; className: string }> = {
    1: { label: "Low", className: "bg-profit/15 text-profit border-profit/30" },
    2: { label: "Low-Med", className: "bg-profit/10 text-profit border-profit/20" },
    3: { label: "Medium", className: "bg-accent/15 text-accent border-accent/30" },
    4: { label: "Med-High", className: "bg-warning/15 text-warning border-warning/30" },
    5: { label: "High", className: "bg-loss/15 text-loss border-loss/30" },
  };
  const c = config[score] ?? config[3];
  return (
    <Badge variant="outline" className={cn("text-xxs h-5", c.className)}>
      {c.label}
    </Badge>
  );
}

// ── Category badge helper ────────────────────────────────────────────────────

function CategoryBadge({ category }: { category: string }) {
  const colors: Record<string, string> = {
    intraday: "bg-accent/15 text-accent border-accent/30",
    swing: "bg-profit/15 text-profit border-profit/30",
    options: "bg-warning/15 text-warning border-warning/30",
    investment: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  };
  return (
    <Badge variant="outline" className={cn("text-xxs h-5 capitalize", colors[category] ?? "")}>
      {category}
    </Badge>
  );
}

// ── Profile-ranking columns ──────────────────────────────────────────────────

function buildLeaderboardColumns(): ColumnDef<TraderRow>[] {
  return [
    {
      accessorKey: "rank",
      header: "#",
      cell: ({ getValue }) => (
        <span className="font-mono tabular-nums text-xs text-text-muted">
          {getValue() as number}
        </span>
      ),
      size: 40,
    },
    {
      accessorKey: "display_name",
      header: "Trader",
      cell: ({ row }) => (
        <div>
          <div className="text-xs font-semibold text-text-primary">
            {row.original.display_name}
          </div>
          <div className="text-xxs text-text-muted">
            {row.original.trades_count.toLocaleString("en-IN")} trades
          </div>
        </div>
      ),
    },
    {
      accessorKey: "total_return_pct",
      header: () => <span className="block text-right">Return %</span>,
      cell: ({ getValue }) => {
        const val = getValue() as number;
        return (
          <div
            className={cn(
              "text-right font-mono tabular-nums text-xs font-semibold",
              val >= 0 ? "text-profit" : "text-loss",
            )}
          >
            {val >= 0 ? "+" : ""}
            {val.toFixed(1)}%
          </div>
        );
      },
    },
    {
      accessorKey: "win_rate",
      header: () => <span className="block text-right">Win Rate</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {(getValue() as number).toFixed(1)}%
        </div>
      ),
    },
    {
      accessorKey: "sharpe_ratio",
      header: () => <span className="block text-right">Sharpe</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {(getValue() as number).toFixed(2)}
        </div>
      ),
    },
    {
      accessorKey: "max_drawdown_pct",
      header: () => <span className="block text-right">Max DD</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-loss">
          -{(getValue() as number).toFixed(1)}%
        </div>
      ),
    },
    {
      accessorKey: "follower_count",
      header: () => <span className="block text-right">Followers</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {(getValue() as number).toLocaleString("en-IN")}
        </div>
      ),
    },
    {
      accessorKey: "risk_score",
      header: () => <span className="block text-right">Risk</span>,
      cell: ({ getValue }) => (
        <div className="flex justify-end">
          <RiskBadge score={getValue() as number} />
        </div>
      ),
    },
  ];
}

// ── Profile ranking section ──────────────────────────────────────────────────

function LeaderboardSection() {
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo(() => buildLeaderboardColumns(), []);

  const { data: liveTraders = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["strategy-library", "profile-rankings"],
    queryFn: () => fetchProfileRankings("total_return_pct"),
    staleTime: 60_000,
  });

  // Fall back to demo data when API fails or returns empty
  const isDemo = isError || (!isLoading && liveTraders.length === 0);
  const traders = isDemo ? DEMO_TRADERS : liveTraders;

  const table = useReactTable({
    data: traders,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <GlassCard className="overflow-hidden p-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-default">
        <div className="flex items-center gap-2">
          <Trophy className="size-4 text-warning" />
          <h2 className="text-sm font-heading font-bold text-text-primary">
            Strategy Profiles
          </h2>
          <Badge variant="outline" className="text-xxs h-5 border-border-default text-text-muted">
            {traders.length} ranked
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          className="text-xs text-text-muted h-6 px-2 gap-1"
        >
          <RefreshCw className={cn("size-3", isLoading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Demo banner */}
      {isDemo && !isLoading && (
        <div className="px-4 pt-3">
          <DemoBanner />
        </div>
      )}

      {/* Content */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center h-48 gap-3 text-text-muted">
          <RefreshCw className="size-5 animate-spin" />
          <span className="text-sm">Loading profile rankings...</span>
        </div>
      )}

      {!isLoading && traders.length > 0 && (
        <div className="overflow-auto max-h-[420px]">
          <Table aria-label="Strategy profile rankings">
            <TableHeader>
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id} className="border-border-default hover:bg-transparent">
                  {hg.headers.map((header) => {
                    const sorted = header.column.getIsSorted();
                    return (
                      <TableHead
                        key={header.id}
                        className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider cursor-pointer select-none"
                        onClick={header.column.getToggleSortingHandler()}
                        aria-sort={
                          sorted === "asc"
                            ? "ascending"
                            : sorted === "desc"
                              ? "descending"
                              : "none"
                        }
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sorted === "asc" && " \u2191"}
                        {sorted === "desc" && " \u2193"}
                      </TableHead>
                    );
                  })}
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
      )}
    </GlassCard>
  );
}

// ── Strategy card ────────────────────────────────────────────────────────────

const CATEGORY_FILTERS = [
  { value: null, label: "All" },
  { value: "intraday", label: "Intraday" },
  { value: "swing", label: "Swing" },
  { value: "options", label: "Options" },
  { value: "investment", label: "Investment" },
] as const;

function StrategyCardItem({
  strategy,
  onAdd,
  isAdding,
}: {
  strategy: StrategyCard;
  onAdd: (id: string) => void;
  isAdding: boolean;
}) {
  return (
    <GlassCard className="flex flex-col gap-3">
      {/* Title row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-heading font-bold text-text-primary truncate">
            {strategy.name}
          </h3>
          <p className="text-xxs text-text-muted mt-0.5 line-clamp-2">
            {strategy.description}
          </p>
        </div>
        <CategoryBadge category={strategy.category} />
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        <div className="flex items-center gap-1.5">
          <TrendingUp className="size-3 text-profit shrink-0" />
          <span className="text-xxs text-text-muted">Backtest</span>
          <span className="text-xs font-mono tabular-nums text-profit ml-auto">
            +{strategy.backtest_return_pct.toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <BarChart3 className="size-3 text-accent shrink-0" />
          <span className="text-xxs text-text-muted">Live</span>
          <span
            className={cn(
              "text-xs font-mono tabular-nums ml-auto",
              strategy.live_return_pct >= 0 ? "text-profit" : "text-loss",
            )}
          >
            {strategy.live_return_pct >= 0 ? "+" : ""}
            {strategy.live_return_pct.toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Star className="size-3 text-warning shrink-0" />
          <span className="text-xxs text-text-muted">Sharpe</span>
          <span className="text-xs font-mono tabular-nums text-text-secondary ml-auto">
            {strategy.backtest_sharpe.toFixed(2)}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Shield className="size-3 text-loss shrink-0" />
          <span className="text-xxs text-text-muted">Max DD</span>
          <span className="text-xs font-mono tabular-nums text-loss ml-auto">
            -{strategy.backtest_max_dd_pct.toFixed(1)}%
          </span>
        </div>
      </div>

      {/* Instruments */}
      {strategy.instruments.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {strategy.instruments.slice(0, 4).map((inst) => (
            <Badge
              key={inst}
              variant="outline"
              className="text-xxs h-4 px-1.5 border-border-default text-text-muted"
            >
              {inst}
            </Badge>
          ))}
          {strategy.instruments.length > 4 && (
            <Badge
              variant="outline"
              className="text-xxs h-4 px-1.5 border-border-default text-text-muted"
            >
              +{strategy.instruments.length - 4}
            </Badge>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-1 border-t border-border-default">
        <div className="flex items-center gap-1.5 text-xxs text-text-muted">
          <Users className="size-3" />
          <span>{strategy.follower_count.toLocaleString("en-IN")} saved views</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="text-xs h-7 gap-1.5"
          onClick={() => onAdd(strategy.strategy_id)}
          disabled={isAdding}
        >
          <Copy className="size-3" />
          Add
        </Button>
      </div>
    </GlassCard>
  );
}

// ── Marketplace section ──────────────────────────────────────────────────────

function MarketplaceSection() {
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [addingId, setAddingId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: liveStrategies = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["strategy-library", "templates", categoryFilter],
    queryFn: () => fetchStrategies(categoryFilter),
    staleTime: 60_000,
  });

  // Fall back to demo data when API fails or returns empty
  const isDemo = isError || (!isLoading && liveStrategies.length === 0);
  const strategies = isDemo
    ? (categoryFilter
        ? DEMO_STRATEGIES.filter((s) => s.category === categoryFilter)
        : DEMO_STRATEGIES)
    : liveStrategies;

  const addMutation = useMutation({
    mutationFn: ({ strategyId }: { strategyId: string }) =>
      addStrategyTemplate(strategyId, "current_user"),
    onMutate: ({ strategyId }) => setAddingId(strategyId),
    onSettled: () => setAddingId(null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategy-library", "templates"] });
    },
  });

  const handleAdd = (strategyId: string) => {
    if (isDemo) return; // Don't add templates in demo mode
    addMutation.mutate({ strategyId });
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="size-4 text-accent" />
          <h2 className="text-sm font-heading font-bold text-text-primary">
            Strategy Library
          </h2>
          <Badge variant="outline" className="text-xxs h-5 border-border-default text-text-muted">
            {strategies.length} strategies
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          className="text-xs text-text-muted h-6 px-2 gap-1"
        >
          <RefreshCw className={cn("size-3", isLoading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Demo banner */}
      {isDemo && !isLoading && <DemoBanner />}

      {/* Category filter pills */}
      <div className="flex items-center gap-1.5">
        <Filter className="size-3 text-text-muted shrink-0" />
        {CATEGORY_FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => setCategoryFilter(f.value)}
            className={cn(
              "px-2.5 py-1 text-xxs font-medium rounded-full transition-colors border",
              categoryFilter === f.value
                ? "bg-accent/15 text-accent border-accent/30"
                : "text-text-muted border-border-default hover:text-text-secondary hover:border-border-hover",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center h-48 gap-3 text-text-muted">
          <RefreshCw className="size-5 animate-spin" />
          <span className="text-sm">Loading strategies...</span>
        </div>
      )}

      {!isLoading && strategies.length > 0 && (
        <StaggeredList>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {strategies.map((s) => (
              <StrategyCardItem
                key={s.strategy_id}
                strategy={s}
                onAdd={handleAdd}
                isAdding={addingId === s.strategy_id}
              />
            ))}
          </div>
        </StaggeredList>
      )}
    </div>
  );
}

// ── Main export ──────────────────────────────────────────────────────────────

export function SocialTab() {
  return (
    <div className="space-y-8">
      <LeaderboardSection />
      <MarketplaceSection />
    </div>
  );
}
