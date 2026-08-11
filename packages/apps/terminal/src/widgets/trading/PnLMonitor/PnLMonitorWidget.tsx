/**
 * PnLMonitorWidget — the canonical P&L surface (dedup merge 2.10).
 *
 * Union of three retired surfaces:
 *   - IntradayPnL   — realised/unrealised split, tradebook partial-close
 *     booking, peak/trough/max-drawdown tracking, per-strategy breakdown.
 *   - MTM Monitor   — the Lightweight Charts curve with target/stop-loss price
 *     lines (settingsStore.riskLimits — the SAME setting the Risk widget
 *     renders as bars; referenced, never duplicated), staleness chip and
 *     error banner + retry.
 *   - P&L Dashboard — its Summary and Drawdown tabs (Calendar moved to Trade
 *     Review in merge 2.12, not here).
 *
 * ONE P&L definition: netPnL = realised (closed rows' broker pnl + tradebook
 * FIFO partial closes) + unrealised (lib/pnl positionMtm per open row). The
 * chart, the headline, the status badge and the Summary card all read this
 * same figure. Before the merge the MTM chart plotted totalPositionMtm, which
 * omits booked partial-close realised, so two P&L widgets docked side by side
 * disagreed on the same book.
 *
 * Data entry paths (one per shape, U10):
 *   - positions/tradebook/funds — the SHARED usePositions()/useTradebook()/
 *     useFunds() TanStack caches; no widget-owned poll that could drift from
 *     what every other widget shows.
 *   - risk limits / UI state — Zustand (settingsStore / panel params).
 *   - Equity-curve snapshots accumulate in widget-local state on each
 *     positions refresh; they are ephemeral, so no Jotai atom is needed.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  memo,
} from "react";
import { AlertTriangle, Clock, TrendingUp } from "lucide-react";
import type { UTCTimestamp } from "lightweight-charts";
import { useShallow } from "zustand/react/shallow";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { useFunds } from "@/hooks/useFunds";
import { usePositions } from "@/hooks/usePositions";
import { useTradebook } from "@/hooks/useTradebook";
import { positionMtm, realisedBySymbol } from "@/lib/pnl";
import { useModeStore } from "@/stores/modeStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { SAMPLE_POSITION_BOOK } from "@/widgets/trading/Positions/sampleBook";
import { getDemoFunds } from "@/hooks/useModeData";
import type { Trade } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";
import { DrawdownView } from "./DrawdownView";
import { LiveView } from "./LiveView";
import { SummaryView } from "./SummaryView";
import {
  buildStrategyPnL,
  formatINRWhole,
  formatUpdatedAt,
  istTickFormatter,
  quantityOf,
  resolvePnLMonitorView,
  staleThresholdMs,
  symbolOf,
  type MtmPoint,
  type PnLMonitorPanelParams,
  type PnLMonitorView,
  type StrategyPnL,
} from "./pnlMonitorShared";

// ---------------------------------------------------------------------------
// Session accumulator state
// ---------------------------------------------------------------------------

interface MonitorState {
  netPnL: number;
  realisedPnL: number;
  unrealisedPnL: number;
  peakPnL: number;
  peakTime: string;
  minPnL: number;
  minTime: string;
  maxDrawdown: number;
  byStrategy: StrategyPnL[];
  series: MtmPoint[];
  loading: boolean;
  error: string | null;
}

const INITIAL_STATE: MonitorState = {
  netPnL: 0,
  realisedPnL: 0,
  unrealisedPnL: 0,
  peakPnL: 0,
  peakTime: "--:--",
  minPnL: 0,
  minTime: "--:--",
  maxDrawdown: 0,
  byStrategy: [],
  series: [],
  loading: true,
  error: null,
};

/** Full session at the 5s market-hours cadence, with headroom. */
const MAX_SERIES_POINTS = 6000;
const EMPTY_TRADES: Trade[] = [];

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function PnLMonitorWidget(props: WidgetProps) {
  const panelParams = props.params as PnLMonitorPanelParams | undefined;
  const [view, setView] = useState<PnLMonitorView>(() => resolvePnLMonitorView(panelParams?.view));

  const mode = useModeStore((s) => s.mode);
  const accountReadsEnabled = useAccountReadsEnabled();
  const riskLimits = useSettingsStore(useShallow((s) => s.riskLimits));
  const isExplore = mode === "explore";

  // Gated account-scoped reads per truthful provenance contract.
  // Explore uses deterministic local sample pack (no network, no prohibited API calls).
  const positionsQuery = usePositions({ enabled: accountReadsEnabled });
  const fundsQuery = useFunds({ enabled: accountReadsEnabled });
  const tradebookQuery = useTradebook({ enabled: accountReadsEnabled });

  // Effective data selection per contract — Explore uses deterministic local sample pack.
  const samplePositions = SAMPLE_POSITION_BOOK;
  const sampleFunds = getDemoFunds();

  const positions = isExplore ? samplePositions : positionsQuery.data;
  const funds = isExplore ? sampleFunds : fundsQuery.data;
  // Drawdown is empty in Explore until a deterministic sample trade pack exists.
  const trades = isExplore ? EMPTY_TRADES : (tradebookQuery.data ?? EMPTY_TRADES);

  // Stable refs to avoid closing over stale state in the update effect
  const peakRef = useRef<number>(0);
  const peakTimeRef = useRef<string>("--:--");
  const minRef = useRef<number>(0);
  const minTimeRef = useRef<string>("--:--");
  const drawdownRef = useRef<number>(0);

  const [state, setState] = useState<MonitorState>(INITIAL_STATE);

  useEffect(() => {
    if (positionsQuery.isError && !isExplore) {
      setState((prev) => ({
        ...prev,
        loading: false,
        error:
          positionsQuery.error instanceof Error
            ? positionsQuery.error.message
            : "Fetch failed",
      }));
      return;
    }
    if (!accountReadsEnabled && !isExplore) {
      // Disconnected Live: honest empty state, no sample, no loading loop, no numeric claim
      setState((prev) => ({
        ...prev,
        loading: false,
        error: null,
        netPnL: 0,
        realisedPnL: 0,
        unrealisedPnL: 0,
        peakPnL: 0,
        peakTime: "--:--",
        minPnL: 0,
        minTime: "--:--",
        maxDrawdown: 0,
        byStrategy: [],
        series: [],
      }));
      return;
    }
    // For Explore sample, positions is always the bound pack (no early return, no loading)
    if (!isExplore && !positions) return;
    const effectivePositions = positions ?? [];

    // Booked realised P&L per symbol from today's tradebook (partial + full
    // closes). If the tradebook is unavailable the map is empty and realised
    // falls back to the closed-position pnl below — the prior behaviour.
    const realisedForSymbol = realisedBySymbol(tradebookQuery.data ?? []);

    let realisedPnL = 0;
    let unrealisedPnL = 0;
    for (const pos of effectivePositions) {
      if (quantityOf(pos) === 0) {
        // Fully closed: the broker/computed pnl is the accurate realised,
        // including a position carried over from a prior day (which the
        // tradebook alone would miss).
        realisedPnL += positionMtm(pos);
      } else {
        // Open: unrealised MTM on the remaining qty, plus any realised already
        // booked by partial closes earlier in the session (from the tradebook).
        unrealisedPnL += positionMtm(pos);
        realisedPnL += realisedForSymbol.get(symbolOf(pos)) ?? 0;
      }
    }
    const netPnL = realisedPnL + unrealisedPnL;

    // Peak / trough / max drawdown tracking (ref-stable). The peak seeds at 0:
    // the session starts flat, so falling from ₹0 straight into loss IS
    // drawdown (the retired MTM Monitor's `peak > 0` guard reported zero
    // drawdown for exactly that case).
    const nowSec = Math.floor(Date.now() / 1000);
    if (netPnL > peakRef.current) {
      peakRef.current = netPnL;
      peakTimeRef.current = istTickFormatter(nowSec);
    }
    if (netPnL < minRef.current) {
      minRef.current = netPnL;
      minTimeRef.current = istTickFormatter(nowSec);
    }
    const dd = peakRef.current - netPnL;
    if (dd > drawdownRef.current) {
      drawdownRef.current = dd;
    }

    const byStrategy = buildStrategyPnL(effectivePositions);
    const point: MtmPoint = { time: nowSec as UTCTimestamp, value: netPnL };

    setState((prev) => {
      // Deduplicate by second — two refreshes within one second update the
      // same chart point instead of stacking.
      const series = prev.series.slice(-(MAX_SERIES_POINTS - 1));
      const last = series[series.length - 1];
      if (last && last.time === point.time) {
        series[series.length - 1] = point;
      } else {
        series.push(point);
      }
      return {
        netPnL,
        realisedPnL,
        unrealisedPnL,
        peakPnL: peakRef.current,
        peakTime: peakTimeRef.current,
        minPnL: minRef.current,
        minTime: minTimeRef.current,
        maxDrawdown: drawdownRef.current,
        byStrategy,
        series,
        loading: false,
        error: null,
      };
    });
    // dataUpdatedAt keys one snapshot per positions REFRESH — reacting to
    // object identity alone would also fire on unrelated re-renders.
  }, [
    positionsQuery.dataUpdatedAt,
    positionsQuery.isError,
    positionsQuery.error,
    positionsQuery.data,
    tradebookQuery.data,
    isExplore,
    accountReadsEnabled,
    positions,
  ]);

  // Ticks every 10s so the last-updated chip can flag staleness between polls.
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 10_000);
    return () => clearInterval(timer);
  }, []);

  const { dataUpdatedAt } = positionsQuery;
  const hasUpdate = typeof dataUpdatedAt === "number" && dataUpdatedAt > 0;
  const isStale = hasUpdate && nowMs - dataUpdatedAt > staleThresholdMs();

  // Persist the chosen view into the panel params so a saved layout reopens in
  // the same tab (this is also how the retired ids select their original look).
  const handleViewChange = useCallback((next: string) => {
    const resolved = resolvePnLMonitorView(next);
    setView((current) => {
      if (current === resolved) return current;
      props.api.updateParameters({ view: resolved });
      return resolved;
    });
  }, [props.api]);

  // Truthful provenance derived from active data path (not mode alone).
  const provenanceKind =
    mode === "practice" && accountReadsEnabled ? "practice"
    : isExplore ? "sample"
    : mode === "live" && !accountReadsEnabled ? "unavailable"
    : null;

  const provenance =
    provenanceKind === "practice" ? "Practice data"
    : provenanceKind === "sample" ? "Sample data"
    : null;

  // Target / SL status badge (from the retired MTM Monitor), on the corrected
  // net P&L rather than a raw position sum.
  const status = useMemo(() => {
    if (state.netPnL >= riskLimits.mtmTarget) return { label: "Target Hit", color: "bg-bullish-bg text-profit border-bullish-border" };
    if (state.netPnL <= -Math.abs(riskLimits.mtmStoploss)) return { label: "SL Hit", color: "bg-bearish-bg text-loss border-bearish-border" };
    if (state.netPnL < 0 && Math.abs(state.netPnL) >= Math.abs(riskLimits.mtmStoploss) * 0.8)
      return { label: "Near SL", color: "bg-atm-bg text-warning border-atm-border" };
    return { label: "Active", color: "bg-surface-hover text-text-muted border-border-default" };
  }, [state.netPnL, riskLimits]);

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <TrendingUp size={11} className="text-text-muted" />
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider whitespace-nowrap">
          P&amp;L Monitor
        </span>
        <span className="text-xxs text-text-muted font-mono tabular-nums whitespace-nowrap">
          Target {formatINRWhole(riskLimits.mtmTarget)} / SL {formatINRWhole(riskLimits.mtmStoploss)}
        </span>
        <div className="ml-auto flex items-center gap-1.5 min-w-0">
          {provenance !== null && (
            <span
              className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400 whitespace-nowrap"
              role="status"
              aria-label={
                provenance === "Practice data"
                  ? "Showing practice-account data from your Practice account"
                  : "Showing sample positions; not connected to a live broker"
              }
              title={
                provenance === "Practice data"
                  ? "Practice mode — P&L is computed from your Practice account."
                  : "Not connected — P&L is computed from sample positions, not your real account."
              }
            >
              {provenance}
            </span>
          )}
          {/* Staleness chip — only when account reads have a real source; a
              sample feed's refresh time is not a trading signal. */}
          {accountReadsEnabled && hasUpdate && (
            <span
              className={`text-xxs font-mono tabular-nums flex items-center gap-0.5 whitespace-nowrap ${
                isStale ? "text-warning" : "text-text-muted"
              }`}
              role="status"
              aria-label={`P&L last updated ${formatUpdatedAt(dataUpdatedAt)}${isStale ? " — stale" : ""}`}
              title={
                isStale
                  ? "Position data has not refreshed recently — the P&L may be stale."
                  : "Time of the last successful position refresh."
              }
            >
              <Clock size={8} aria-hidden="true" />
              {isStale ? "Stale since " : "Updated "}
              {formatUpdatedAt(dataUpdatedAt)}
            </span>
          )}
          <Badge className={`text-xxs px-1.5 py-0 border whitespace-nowrap ${status.color}`}>
            {status.label}
          </Badge>
          {/* Health dot — quiet honesty in every mode (the loud banner below
              only appears when account reads are live). */}
          {state.error ? (
            <span title={state.error} className="w-1.5 h-1.5 rounded-full bg-loss shrink-0" />
          ) : !state.loading ? (
            <span className="w-1.5 h-1.5 rounded-full bg-profit/60 shrink-0" />
          ) : null}
        </div>
      </div>

      {/* Position-feed failure banner — the chart freezes on the last good
          tick, so say so instead of silently showing a frozen P&L. */}
      {accountReadsEnabled && positionsQuery.isError && (
        <div
          role="alert"
          className="flex items-center gap-2 px-3 py-1.5 border-b border-loss/20 bg-loss/10 shrink-0"
        >
          <AlertTriangle size={12} className="text-loss shrink-0" aria-hidden="true" />
          <span className="flex-1 text-xs text-loss leading-tight">
            Position feed failed — P&amp;L figures are frozen
            {hasUpdate ? ` at ${formatUpdatedAt(dataUpdatedAt)}` : ""}
            {positionsQuery.error instanceof Error && positionsQuery.error.message
              ? `: ${positionsQuery.error.message}`
              : "."}
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void positionsQuery.refetch()}
            disabled={positionsQuery.isFetching}
            className="h-5 px-2 text-xxs border-loss/30 text-loss hover:bg-loss/10 hover:text-loss shrink-0"
            aria-label="Retry position fetch"
          >
            {positionsQuery.isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {/* Views */}
      <Tabs value={view} onValueChange={handleViewChange} className="flex-1 flex flex-col min-h-0 gap-0">
        <TabsList className="shrink-0 rounded-none bg-surface-base border-b border-border-default justify-start px-2 h-7 gap-1 w-full">
          <TabsTrigger value="live" className="text-xs font-medium h-5 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            Live
          </TabsTrigger>
          <TabsTrigger value="summary" className="text-xs font-medium h-5 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            Summary
          </TabsTrigger>
          <TabsTrigger value="drawdown" className="text-xs font-medium h-5 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            Drawdown
          </TabsTrigger>
        </TabsList>

        <TabsContent value="live" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <LiveView
            netPnL={state.netPnL}
            realisedPnL={state.realisedPnL}
            unrealisedPnL={state.unrealisedPnL}
            peakPnL={state.peakPnL}
            peakTime={state.peakTime}
            minPnL={state.minPnL}
            minTime={state.minTime}
            maxDrawdown={state.maxDrawdown}
            byStrategy={state.byStrategy}
            series={state.series}
            loading={state.loading}
            riskLimits={riskLimits}
            accountReadsEnabled={accountReadsEnabled}
          />
        </TabsContent>

        <TabsContent value="summary" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <SummaryView
            positions={positions ?? []}
            funds={funds}
            netPnL={state.netPnL}
          />
        </TabsContent>

        <TabsContent value="drawdown" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <DrawdownView trades={trades} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default memo(PnLMonitorWidget);
