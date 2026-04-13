import { useState, useEffect } from "react";
import {
  Loader2,
  AlertCircle,
  RefreshCw,
  PlayCircle,
  Square,
  Activity,
  Clock,
} from "lucide-react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  getStrategies,
  getRunningStrategies,
  getForwardTrades,
  startStrategy,
  stopStrategy,
  type StrategyInfo,
  type RunningStrategy,
  type ForwardTrade,
} from "@/services/ftApi";
import { fmtInr, fmtPct, fmtNum } from "./formatters";
import { AnimatedMetricCard, MetricCard } from "./MetricCards";

function useDuration(startedAt: string | null): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAt) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  if (!startedAt) return "00:00";
  const diff = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const m = String(Math.floor(diff / 60)).padStart(2, "0");
  const s = String(diff % 60).padStart(2, "0");
  return `${m}:${s}`;
}

interface ForwardTradesTableProps {
  trades: ForwardTrade[];
}

function ForwardTradesTable({ trades }: ForwardTradesTableProps) {
  if (trades.length === 0) {
    return (
      <p className="text-xs text-text-muted text-center py-6">
        No virtual trades yet. Signals will generate trades as ticks arrive.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="border-border-default">
            <TableHead className="text-text-muted text-xs">Entry</TableHead>
            <TableHead className="text-text-muted text-xs">Exit</TableHead>
            <TableHead className="text-text-muted text-xs">Symbol</TableHead>
            <TableHead className="text-text-muted text-xs">Side</TableHead>
            <TableHead className="text-text-muted text-xs text-right">Qty</TableHead>
            <TableHead className="text-text-muted text-xs text-right">Entry ₹</TableHead>
            <TableHead className="text-text-muted text-xs text-right">Exit ₹</TableHead>
            <TableHead className="text-text-muted text-xs text-right">P&L</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((trade, i) => (
            <TableRow key={i} className="border-border-default">
              <TableCell className="text-xxs text-text-secondary font-mono">
                {trade.entry_timestamp.slice(0, 16).replace("T", " ")}
              </TableCell>
              <TableCell className="text-xxs text-text-secondary font-mono">
                {trade.exit_timestamp ? (
                  trade.exit_timestamp.slice(0, 16).replace("T", " ")
                ) : (
                  <span className="text-warning">Open</span>
                )}
              </TableCell>
              <TableCell className="text-xs font-mono text-text-primary">
                {trade.symbol}
              </TableCell>
              <TableCell>
                <Badge
                  className={`text-xxs ${
                    trade.side === "BUY"
                      ? "bg-bullish-bg text-profit"
                      : "bg-bearish-bg text-loss"
                  }`}
                >
                  {trade.side}
                </Badge>
              </TableCell>
              <TableCell className="text-xxs font-mono text-text-secondary text-right">
                {trade.quantity}
              </TableCell>
              <TableCell className="text-xxs font-mono text-text-secondary text-right">
                {trade.entry_price.toLocaleString("en-IN")}
              </TableCell>
              <TableCell className="text-xxs font-mono text-text-secondary text-right">
                {trade.exit_price > 0
                  ? trade.exit_price.toLocaleString("en-IN")
                  : "—"}
              </TableCell>
              <TableCell
                className={`text-xs font-mono font-semibold text-right ${
                  trade.pnl >= 0 ? "text-profit" : "text-loss"
                }`}
              >
                {trade.exit_price > 0 ? fmtInr(trade.pnl) : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

interface ForwardMonitorProps {
  running: RunningStrategy;
  onStop: () => void;
  isStopping: boolean;
}

function ForwardMonitor({ running, onStop, isStopping }: ForwardMonitorProps) {
  const duration = useDuration(running.started_at);

  const tradesQuery = useQuery<ForwardTrade[], Error>({
    queryKey: ["forwardTrades", running.name],
    queryFn: () => getForwardTrades(running.name),
    refetchInterval: 5000,
  });

  const trades = tradesQuery.data ?? [];
  const closedTrades = trades.filter((t) => t.exit_price > 0);

  const totalPnl =
    running.virtual_pnl ?? closedTrades.reduce((sum, t) => sum + t.pnl, 0);
  const wins = closedTrades.filter((t) => t.pnl > 0).length;
  const winRate = closedTrades.length > 0 ? wins / closedTrades.length : 0;
  const grossWin = closedTrades
    .filter((t) => t.pnl > 0)
    .reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(
    closedTrades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0),
  );
  const profitFactor =
    grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0;

  return (
    <div className="space-y-4">
      <GlassCard className="p-4 gap-0">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-profit" />
              <span className="text-sm font-semibold text-text-primary font-mono">
                {running.name}
              </span>
            </div>
            <Badge className="bg-bullish-bg text-profit text-xs border-0">
              {running.status}
            </Badge>
            <span className="text-xs text-text-muted font-mono">
              {running.symbol} / {running.exchange}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5 text-xs text-text-muted">
              <Clock className="w-3 h-3" />
              <span className="font-mono">{duration}</span>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={onStop}
              disabled={isStopping}
              className="text-xs h-7 px-3"
            >
              {isStopping ? (
                <>
                  <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />
                  Stopping…
                </>
              ) : (
                <>
                  <Square className="w-3 h-3 mr-1.5" />
                  Stop
                </>
              )}
            </Button>
          </div>
        </div>
      </GlassCard>

      <GlassCard className="p-5 gap-3">
        <h4 className="font-heading font-semibold text-sm text-text-primary">
          Live Performance
          {tradesQuery.isFetching && (
            <Loader2 className="inline-block w-3 h-3 ml-2 animate-spin text-text-muted" />
          )}
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <AnimatedMetricCard
            label="Win Rate"
            numericValue={winRate * 100}
            displayValue={
              closedTrades.length > 0 ? fmtPct(winRate) : "—"
            }
            animate={closedTrades.length > 0}
            positive={winRate >= 0.5}
            formatter={(v) => v.toFixed(2) + "%"}
          />
          <AnimatedMetricCard
            label="Profit Factor"
            numericValue={isFinite(profitFactor) ? profitFactor : 0}
            displayValue={
              profitFactor === Infinity
                ? "∞"
                : closedTrades.length > 0
                  ? fmtNum(profitFactor)
                  : "—"
            }
            animate={closedTrades.length > 0 && isFinite(profitFactor)}
            positive={
              profitFactor > 1 ? true : profitFactor === 0 ? null : false
            }
            formatter={(v) => v.toFixed(2)}
          />
          <MetricCard
            label="Virtual P&L"
            value={fmtInr(totalPnl)}
            positive={totalPnl >= 0}
          />
          <MetricCard
            label="Ticks Processed"
            value={String(running.tick_count)}
            positive={null}
          />
          <MetricCard
            label="Closed Trades"
            value={String(closedTrades.length)}
            positive={null}
          />
          <MetricCard
            label="Gross Win"
            value={grossWin > 0 ? fmtInr(grossWin) : "—"}
            positive={grossWin > 0 ? true : null}
          />
          <MetricCard
            label="Gross Loss"
            value={grossLoss > 0 ? fmtInr(grossLoss) : "—"}
            positive={false}
          />
          <MetricCard
            label="Open Trades"
            value={String(trades.length - closedTrades.length)}
            positive={null}
          />
        </div>
      </GlassCard>

      <GlassCard className="p-5 gap-3">
        <h4 className="font-heading font-semibold text-sm text-text-primary">
          Virtual Trade Log
          <span className="ml-2 text-xs text-text-muted font-normal">
            ({trades.length} trade{trades.length !== 1 ? "s" : ""})
          </span>
        </h4>
        <ForwardTradesTable trades={trades} />
      </GlassCard>
    </div>
  );
}

type ForwardTestState = "idle" | "running" | "stopped";

export function ForwardTestSection() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [exchange, setExchange] = useState("NFO");
  const [virtualCapital, setVirtualCapital] = useState(100000);
  const [positionSizePct, setPositionSizePct] = useState(10);
  const [selectedStrategy, setSelectedStrategy] = useState("");
  const [ftState, setFtState] = useState<ForwardTestState>("idle");
  const [activeStrategyName, setActiveStrategyName] = useState<string | null>(
    null,
  );
  const [stoppedSummary, setStoppedSummary] = useState<{
    trades: ForwardTrade[];
    pnl: number;
  } | null>(null);

  const strategiesQuery = useQuery<StrategyInfo[], Error>({
    queryKey: ["strategies"],
    queryFn: getStrategies,
  });

  const runningQuery = useQuery<RunningStrategy[], Error>({
    queryKey: ["runningStrategies"],
    queryFn: getRunningStrategies,
    refetchInterval: ftState === "running" ? 5000 : false,
    enabled: ftState === "running",
  });

  const activeRunning =
    runningQuery.data?.find((s) => s.name === activeStrategyName) ?? null;

  useEffect(() => {
    if (ftState === "running" && activeStrategyName && runningQuery.data) {
      const found = runningQuery.data.find(
        (s) => s.name === activeStrategyName,
      );
      if (!found) {
        setFtState("stopped");
      }
    }
  }, [ftState, activeStrategyName, runningQuery.data]);

  const strategiesByCategory = (strategiesQuery.data ?? []).reduce<
    Record<string, StrategyInfo[]>
  >((acc, s) => {
    const cat = s.category || "Other";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(s);
    return acc;
  }, {});

  const startMutation = useMutation<{ status: string }, Error, void>({
    mutationFn: () =>
      startStrategy(selectedStrategy, {
        symbol,
        exchange,
        initial_capital: virtualCapital,
        position_size_pct: positionSizePct,
        paper_mode: true,
      }),
    onSuccess: () => {
      setActiveStrategyName(selectedStrategy);
      setFtState("running");
      setStoppedSummary(null);
    },
  });

  const stopMutation = useMutation<{ status: string }, Error, void>({
    mutationFn: () => stopStrategy(activeStrategyName!),
    onSuccess: async () => {
      const pnl = activeRunning?.virtual_pnl ?? 0;
      let lastTrades: ForwardTrade[] = [];
      try {
        lastTrades = await getForwardTrades(activeStrategyName!);
      } catch {
        // ignore — summary will show partial data
      }
      setStoppedSummary({ trades: lastTrades, pnl });
      setFtState("stopped");
      setActiveStrategyName(null);
    },
  });

  if (ftState === "idle" || ftState === "stopped") {
    const closedTrades =
      stoppedSummary?.trades.filter((t) => t.exit_price > 0) ?? [];
    const wins = closedTrades.filter((t) => t.pnl > 0).length;
    const winRate =
      closedTrades.length > 0 ? wins / closedTrades.length : 0;
    const grossWin = closedTrades
      .filter((t) => t.pnl > 0)
      .reduce((s, t) => s + t.pnl, 0);
    const grossLoss = Math.abs(
      closedTrades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0),
    );
    const profitFactor =
      grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0;

    return (
      <div className="space-y-4">
        {ftState === "stopped" && stoppedSummary && (
          <GlassCard className="p-5 gap-3">
            <div className="flex items-center justify-between">
              <h4 className="font-heading font-semibold text-sm text-text-primary">
                Session Summary
              </h4>
              <Badge className="bg-text-muted/10 text-text-muted text-xs border-0">
                Stopped
              </Badge>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <MetricCard
                label="Final P&L"
                value={fmtInr(stoppedSummary.pnl)}
                positive={stoppedSummary.pnl >= 0}
              />
              <MetricCard
                label="Closed Trades"
                value={String(closedTrades.length)}
                positive={null}
              />
              <MetricCard
                label="Win Rate"
                value={closedTrades.length > 0 ? fmtPct(winRate) : "—"}
                positive={winRate >= 0.5}
              />
              <MetricCard
                label="Profit Factor"
                value={
                  profitFactor === Infinity
                    ? "∞"
                    : closedTrades.length > 0
                      ? fmtNum(profitFactor)
                      : "—"
                }
                positive={
                  profitFactor > 1 ? true : profitFactor === 0 ? null : false
                }
              />
            </div>
            {stoppedSummary.trades.length > 0 && (
              <>
                <h5 className="text-xs font-semibold text-text-secondary">
                  Trade Log
                  <span className="ml-2 text-text-muted font-normal">
                    (
                    {stoppedSummary.trades.length} trade
                    {stoppedSummary.trades.length !== 1 ? "s" : ""})
                  </span>
                </h5>
                <ForwardTradesTable trades={stoppedSummary.trades} />
              </>
            )}
          </GlassCard>
        )}

        <GlassCard className="p-6 gap-4">
          <h3 className="font-heading font-semibold text-lg text-text-primary">
            Forward Test Configuration
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="sm:col-span-2 space-y-1.5">
              <Label className="text-xs text-text-secondary">Strategy</Label>
              {strategiesQuery.isLoading ? (
                <div className="flex items-center gap-2 text-xs text-text-muted h-9">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Loading strategies…
                </div>
              ) : strategiesQuery.isError ? (
                <div className="flex items-center gap-2 text-xs text-loss h-9">
                  <AlertCircle className="w-3 h-3" />
                  Failed to load strategies
                  <button
                    onClick={() => strategiesQuery.refetch()}
                    className="underline hover:no-underline"
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <Select
                  value={selectedStrategy}
                  onValueChange={setSelectedStrategy}
                >
                  <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                    <SelectValue placeholder="Select a strategy…" />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default">
                    {Object.entries(strategiesByCategory).map(
                      ([category, strategies]) => (
                        <div key={category}>
                          <div className="px-2 py-1 text-xxs text-text-muted font-semibold uppercase tracking-wider">
                            {category}
                          </div>
                          {strategies.map((s) => (
                            <SelectItem
                              key={s.name}
                              value={s.name}
                              className="text-text-primary text-sm"
                            >
                              <span className="font-mono">{s.name}</span>
                              {s.description && (
                                <span className="ml-2 text-text-muted text-xs">
                                  — {s.description}
                                </span>
                              )}
                            </SelectItem>
                          ))}
                        </div>
                      ),
                    )}
                  </SelectContent>
                </Select>
              )}
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs text-text-secondary">Symbol</Label>
              <Input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="NIFTY"
                className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs text-text-secondary">Exchange</Label>
              <Select value={exchange} onValueChange={setExchange}>
                <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-surface-card border-border-default">
                  {["NFO", "NSE", "BSE", "MCX", "CDS"].map((ex) => (
                    <SelectItem
                      key={ex}
                      value={ex}
                      className="text-text-primary text-sm font-mono"
                    >
                      {ex}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs text-text-secondary">
                Virtual Capital (₹)
              </Label>
              <Input
                type="number"
                min={1000}
                step={10000}
                value={virtualCapital}
                onChange={(e) => setVirtualCapital(Number(e.target.value))}
                className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs text-text-secondary">
                Position Size (%)
              </Label>
              <Input
                type="number"
                min={1}
                max={100}
                step={1}
                value={positionSizePct}
                onChange={(e) => setPositionSizePct(Number(e.target.value))}
                className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending || !selectedStrategy}
              className="bg-accent text-white hover:bg-accent/90 font-sans text-sm px-5"
            >
              {startMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Starting…
                </>
              ) : (
                <>
                  <PlayCircle className="w-4 h-4 mr-2" />
                  Start Forward Test
                </>
              )}
            </Button>

            {startMutation.isError && (
              <div className="flex items-center gap-2 text-xs text-loss">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                <span>{startMutation.error.message}</span>
                <button
                  onClick={() => startMutation.mutate()}
                  className="flex items-center gap-1 underline hover:no-underline"
                >
                  <RefreshCw className="w-3 h-3" />
                  Retry
                </button>
              </div>
            )}
          </div>
        </GlassCard>
      </div>
    );
  }

  if (ftState === "running" && activeRunning) {
    return (
      <ForwardMonitor
        running={activeRunning}
        onStop={() => stopMutation.mutate()}
        isStopping={stopMutation.isPending}
      />
    );
  }

  return (
    <GlassCard className="p-6 flex items-center gap-3">
      <Loader2 className="w-5 h-5 text-accent animate-spin" />
      <p className="text-sm text-text-secondary">
        Starting forward test… waiting for strategy engine.
      </p>
    </GlassCard>
  );
}
