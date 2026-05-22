import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  runBacktest,
  getStrategies,
  type BacktestConfig,
  type BacktestResult,
  type StrategyInfo,
} from "@/services/ftApi";
import { BacktestConfigPanel } from "./BacktestConfigPanel";
import { BacktestResultDisplay } from "./BacktestResultDisplay";

export interface BacktestSectionProps {
  onResult: (result: BacktestResult) => void;
  lastResult: BacktestResult | null;
}

export function BacktestSection({ onResult, lastResult }: BacktestSectionProps) {
  const [symbol, setSymbol] = useState("NIFTY");
  const [exchange, setExchange] = useState("NFO");
  const [interval, setInterval] = useState("5m");
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [initialCapital, setInitialCapital] = useState(100000);
  const [positionSizePct, setPositionSizePct] = useState(10);
  const [selectedStrategy, setSelectedStrategy] = useState("");

  const strategiesQuery = useQuery<StrategyInfo[], Error>({
    queryKey: ["strategies"],
    queryFn: getStrategies,
  });

  const backtestMutation = useMutation<BacktestResult, Error, BacktestConfig>({
    mutationFn: runBacktest,
    onSuccess: (data) => {
      onResult(data);
    },
  });

  function handleRun() {
    if (!selectedStrategy) return;
    backtestMutation.mutate({
      symbol,
      exchange,
      interval,
      start_date: startDate,
      end_date: endDate,
      strategy: selectedStrategy,
      initial_capital: initialCapital,
      position_size_pct: positionSizePct,
    });
  }

  const isRunning = backtestMutation.isPending;
  const runError = backtestMutation.error;

  return (
    <div
      data-testid="backtest-layout"
      className="mx-auto grid w-full max-w-4xl grid-cols-1 items-start justify-center gap-4 lg:grid-cols-[minmax(280px,340px)_minmax(320px,1fr)]"
    >
      <div className="min-w-0">
        <BacktestConfigPanel
          symbol={symbol}
          onSymbol={setSymbol}
          exchange={exchange}
          onExchange={setExchange}
          interval={interval}
          onInterval={setInterval}
          startDate={startDate}
          onStartDate={setStartDate}
          endDate={endDate}
          onEndDate={setEndDate}
          initialCapital={initialCapital}
          onInitialCapital={setInitialCapital}
          positionSizePct={positionSizePct}
          onPositionSizePct={setPositionSizePct}
          selectedStrategy={selectedStrategy}
          onStrategy={setSelectedStrategy}
          strategiesQuery={strategiesQuery}
          isRunning={isRunning}
          runError={runError}
          onRun={handleRun}
          isSuccess={backtestMutation.isSuccess}
          onRetry={handleRun}
        />
      </div>

      <div className="min-w-0">
        {isRunning ? (
          <GlassCard className="flex items-center justify-center gap-3 p-6 text-center">
            <Loader2 className="w-5 h-5 text-accent animate-spin" />
            <p className="text-sm text-text-secondary">
              Running backtest… this may take a few seconds.
            </p>
          </GlassCard>
        ) : lastResult ? (
          <BacktestResultDisplay result={lastResult} />
        ) : (
          <GlassCard className="min-h-40 justify-center gap-2 p-8 text-center">
            <FlaskConical className="w-8 h-8 text-text-muted mx-auto mb-2" />
            <p className="text-sm font-semibold text-text-secondary">
              No results yet
            </p>
            <p className="text-xs text-text-muted">
              Configure and run a backtest to see performance metrics, equity
              curve, and trade log.
            </p>
          </GlassCard>
        )}
      </div>
    </div>
  );
}
