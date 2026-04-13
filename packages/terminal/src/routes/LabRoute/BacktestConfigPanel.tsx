import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Loader2,
  AlertCircle,
  RefreshCw,
  Play,
  ChevronDown,
  ChevronUp,
  Settings2,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
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
import { GlassCard } from "@/components/ui/GlassCard";
import { motionConfig } from "@/lib/motion";
import { type StrategyInfo } from "@/services/ftApi";

export interface BacktestConfigPanelProps {
  symbol: string;
  onSymbol: (v: string) => void;
  exchange: string;
  onExchange: (v: string) => void;
  interval: string;
  onInterval: (v: string) => void;
  startDate: string;
  onStartDate: (v: string) => void;
  endDate: string;
  onEndDate: (v: string) => void;
  initialCapital: number;
  onInitialCapital: (v: number) => void;
  positionSizePct: number;
  onPositionSizePct: (v: number) => void;
  selectedStrategy: string;
  onStrategy: (v: string) => void;
  strategiesQuery: ReturnType<typeof useQuery<StrategyInfo[], Error>>;
  isRunning: boolean;
  runError: Error | null;
  onRun: () => void;
  isSuccess: boolean;
  onRetry: () => void;
}

export function BacktestConfigPanel({
  symbol,
  onSymbol,
  exchange,
  onExchange,
  interval,
  onInterval,
  startDate,
  onStartDate,
  endDate,
  onEndDate,
  initialCapital,
  onInitialCapital,
  positionSizePct,
  onPositionSizePct,
  selectedStrategy,
  onStrategy,
  strategiesQuery,
  isRunning,
  runError,
  onRun,
  isSuccess,
  onRetry,
}: BacktestConfigPanelProps) {
  const [collapsed, setCollapsed] = useState(false);

  const strategiesByCategory = (strategiesQuery.data ?? []).reduce<
    Record<string, StrategyInfo[]>
  >((acc, s) => {
    const cat = s.category || "Other";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(s);
    return acc;
  }, {});

  return (
    <GlassCard className="flex flex-col gap-0 p-0 overflow-hidden">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center justify-between px-4 py-3 border-b border-border-default hover:bg-surface-base/50 transition-colors w-full text-left"
        aria-expanded={!collapsed}
        aria-controls="backtest-config-body"
      >
        <div className="flex items-center gap-2">
          <Settings2 className="w-3.5 h-3.5 text-text-muted" />
          <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Configuration
          </span>
        </div>
        {collapsed ? (
          <ChevronDown className="w-3.5 h-3.5 text-text-muted" />
        ) : (
          <ChevronUp className="w-3.5 h-3.5 text-text-muted" />
        )}
      </button>

      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            id="backtest-config-body"
            key="config-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{
              height: { duration: motionConfig.duration.slow, ease: motionConfig.ease.enter },
              opacity: { duration: motionConfig.duration.normal },
            }}
            style={{ overflow: "hidden" }}
          >
            <div className="p-4 space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">Strategy</Label>
                {strategiesQuery.isLoading ? (
                  <div className="flex items-center gap-2 text-xs text-text-muted h-9">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Loading…
                  </div>
                ) : strategiesQuery.isError ? (
                  <div className="flex items-center gap-2 text-xs text-loss h-9">
                    <AlertCircle className="w-3 h-3" />
                    Failed
                    <button
                      onClick={() => strategiesQuery.refetch()}
                      className="underline hover:no-underline"
                    >
                      Retry
                    </button>
                  </div>
                ) : (
                  <Select value={selectedStrategy} onValueChange={onStrategy}>
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
                  onChange={(e) => onSymbol(e.target.value.toUpperCase())}
                  placeholder="NIFTY"
                  className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">Exchange</Label>
                <Select value={exchange} onValueChange={onExchange}>
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
                <Label className="text-xs text-text-secondary">Interval</Label>
                <Select value={interval} onValueChange={onInterval}>
                  <SelectTrigger className="bg-surface-base border-border-default text-text-primary text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default">
                    {["1m", "3m", "5m", "10m", "15m", "30m", "1h", "D", "W"].map(
                      (iv) => (
                        <SelectItem
                          key={iv}
                          value={iv}
                          className="text-text-primary text-sm font-mono"
                        >
                          {iv}
                        </SelectItem>
                      ),
                    )}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">Start Date</Label>
                <Input
                  type="date"
                  value={startDate}
                  onChange={(e) => onStartDate(e.target.value)}
                  className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">End Date</Label>
                <Input
                  type="date"
                  value={endDate}
                  onChange={(e) => onEndDate(e.target.value)}
                  className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs text-text-secondary">
                  Capital (₹)
                </Label>
                <Input
                  type="number"
                  min={1000}
                  step={10000}
                  value={initialCapital}
                  onChange={(e) => onInitialCapital(Number(e.target.value))}
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
                  onChange={(e) => onPositionSizePct(Number(e.target.value))}
                  className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
                />
              </div>

              <Button
                onClick={onRun}
                disabled={isRunning || !selectedStrategy}
                className="w-full bg-accent text-white hover:bg-accent/90 font-sans text-sm"
              >
                {isRunning ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Running…
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 mr-2" />
                    Run Backtest
                  </>
                )}
              </Button>

              {isSuccess && (
                <p className="text-xs text-profit text-center">
                  Backtest complete.
                </p>
              )}

              {runError && (
                <div className="flex items-center gap-2 text-xs text-loss">
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                  <span className="flex-1 truncate">{runError.message}</span>
                  <button
                    onClick={onRetry}
                    className="flex items-center gap-1 underline hover:no-underline shrink-0"
                  >
                    <RefreshCw className="w-3 h-3" />
                    Retry
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </GlassCard>
  );
}
