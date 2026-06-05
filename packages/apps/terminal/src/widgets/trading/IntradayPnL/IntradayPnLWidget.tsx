/**
 * IntradayPnLWidget
 *
 * Displays the current day's running P&L with a mini equity curve,
 * realised/unrealised breakdown, peak P&L, max intraday drawdown,
 * and per-strategy breakdown.
 *
 * Data source:
 *   - Polls getPositionbook() every 5 seconds during market hours (60s off-hours)
 *   - Tracks P&L snapshots for the equity curve using local state + setInterval
 *   - Shared Flint baseline sparkline for the compact curve
 *
 * Architecture:
 *   - Local state for the equity curve snapshot history (no global atom needed)
 *   - Jotai is used only when inter-widget communication is required;
 *     intraday snapshots are ephemeral and widget-local.
 */

import {
  useEffect,
  useRef,
  useState,
  useCallback,
  useMemo,
  memo,
} from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { FlintBaselineSparkline } from "@flinttrade/design-system";
import { getPositionbook } from "@/services/api";
import { isMarketHours } from "@/lib/market";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import type { Position } from "@/types/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PnLSnapshot {
  time:  number; // Unix timestamp (seconds)
  value: number; // cumulative P&L at that moment
}

interface StrategyPnL {
  strategy: string;
  pnl:      number;
}

interface IntradayState {
  netPnL:       number;
  realisedPnL:  number;
  unrealisedPnL: number;
  peakPnL:      number;
  maxDrawdown:  number;
  byStrategy:   StrategyPnL[];
  snapshots:    PnLSnapshot[];
  loading:      boolean;
  error:        string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_SNAPSHOTS = 300; // ~25 minutes at 5s interval

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const INR = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

function fmtINR(n: number): string {
  return `\u20B9${INR.format(Math.abs(n))}`;
}

function fmtSigned(n: number): string {
  const sign = n >= 0 ? "+" : "-";
  return `${sign}${fmtINR(n)}`;
}

function pnlColor(n: number): string {
  if (n > 0) return "text-profit";
  if (n < 0) return "text-loss";
  return "text-text-muted";
}

/** Extract strategy tag from OpenAlgo position — falls back to "default" */
function strategyOf(pos: Position): string {
  // OpenAlgo positions don't carry a strategy field in the base type.
  // Cast to extended type for brokers that do provide it; otherwise "default".
  return (pos as Position & { strategy?: string }).strategy ?? "default";
}

/**
 * OpenAlgo returns a single pnl field per position.
 * For closed positions (qty === 0) we treat the full pnl as realised;
 * for open positions the full pnl is unrealised.
 */
function splitPnL(pos: Position): { realised: number; unrealised: number } {
  const pnl = pos.pnl ?? 0;
  if (pos.quantity === 0) return { realised: pnl, unrealised: 0 };
  return { realised: 0, unrealised: pnl };
}

/** Build per-strategy P&L map from positions */
function buildStrategyPnL(positions: Position[]): StrategyPnL[] {
  const map = new Map<string, number>();
  for (const pos of positions) {
    const s = strategyOf(pos);
    map.set(s, (map.get(s) ?? 0) + (pos.pnl ?? 0));
  }
  return Array.from(map.entries())
    .map(([strategy, pnl]) => ({ strategy, pnl }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
}

// ---------------------------------------------------------------------------
// Mini equity curve
// ---------------------------------------------------------------------------

interface EquityCurveProps {
  snapshots: PnLSnapshot[];
}

function EquityCurve({ snapshots }: EquityCurveProps) {
  if (snapshots.length < 2) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-disabled text-xs">
        Collecting data…
      </div>
    );
  }

  const values = snapshots.map((s) => s.value);
  const lastVal = values[values.length - 1] ?? 0;

  return (
    <FlintBaselineSparkline
      points={values}
      baseline={0}
      positive={lastVal >= 0}
      ariaLabel="Intraday P&L equity curve"
      className="h-full flex-1"
    />
  );
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

interface StatCardProps {
  label:     string;
  value:     string;
  colorCls?: string;
}

function StatCard({ label, value, colorCls = "text-text-primary" }: StatCardProps) {
  return (
    <div className="flex flex-col items-center gap-0.5 bg-surface-card border border-border-default rounded px-2 py-1 min-w-0 flex-1">
      <span className="text-xxs text-text-muted uppercase tracking-wider whitespace-nowrap">{label}</span>
      <span className={`text-xs font-mono tabular-nums font-semibold ${colorCls}`}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function IntradayPnLWidget() {
  const isConnected = useBrokerConnected();
  const [state, setState] = useState<IntradayState>({
    netPnL:        0,
    realisedPnL:   0,
    unrealisedPnL: 0,
    peakPnL:       0,
    maxDrawdown:   0,
    byStrategy:    [],
    snapshots:     [],
    loading:       true,
    error:         null,
  });

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Stable refs to avoid closing over stale state in the async callback
  const peakRef      = useRef<number>(0);
  const drawdownRef  = useRef<number>(0);

  const fetchAndUpdate = useCallback(async () => {
    try {
      const positions: Position[] = await getPositionbook();

      let realisedPnL   = 0;
      let unrealisedPnL = 0;
      for (const pos of positions) {
        const { realised, unrealised } = splitPnL(pos);
        realisedPnL   += realised;
        unrealisedPnL += unrealised;
      }
      const netPnL = realisedPnL + unrealisedPnL;

      // Peak and max drawdown tracking (ref-stable)
      if (netPnL > peakRef.current) {
        peakRef.current = netPnL;
      }
      const dd = peakRef.current - netPnL;
      if (dd > drawdownRef.current) {
        drawdownRef.current = dd;
      }

      const byStrategy = buildStrategyPnL(positions);
      const now = Math.floor(Date.now() / 1000);

      setState((prev) => ({
        netPnL,
        realisedPnL,
        unrealisedPnL,
        peakPnL:     peakRef.current,
        maxDrawdown: drawdownRef.current,
        byStrategy,
        snapshots: [
          ...prev.snapshots.slice(-(MAX_SNAPSHOTS - 1)),
          { time: now, value: netPnL },
        ],
        loading: false,
        error:   null,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        loading: false,
        error:   err instanceof Error ? err.message : "Fetch failed",
      }));
    }
  }, []);

  useEffect(() => {
    void fetchAndUpdate();

    function schedule() {
      const delay = isMarketHours() ? 5000 : 60000;
      pollRef.current = setTimeout(() => {
        void fetchAndUpdate();
        schedule();
      }, delay);
    }

    schedule();
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [fetchAndUpdate]);

  const { netPnL, realisedPnL, unrealisedPnL, peakPnL, maxDrawdown, byStrategy, snapshots } = state;

  const netColor = pnlColor(netPnL);
  const NetIcon  = netPnL > 0 ? TrendingUp : netPnL < 0 ? TrendingDown : Minus;

  // Show strategy breakdown only when there is more than one strategy
  const showStrategies = useMemo(
    () => byStrategy.length > 1 || (byStrategy.length === 1 && byStrategy[0].strategy !== "default"),
    [byStrategy],
  );

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <TrendingUp size={11} className="text-text-muted" />
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
          Intraday P&amp;L
        </span>
        {/* Honest disclosure — when no broker is connected (explore mode) the
            P&L is computed from SAMPLE positions, not a real account. */}
        {!isConnected && (
          <span
            className="ml-auto inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample positions; not connected to a live broker"
            title="Not connected — Intraday P&L is computed from sample positions, not your real account."
          >
            Sample data
          </span>
        )}
        {state.error && (
          <span title={state.error} className={`${isConnected ? "ml-auto" : ""} w-1.5 h-1.5 rounded-full bg-loss shrink-0`} />
        )}
        {!state.error && !state.loading && (
          <span className="ml-auto w-1.5 h-1.5 rounded-full bg-profit/60 shrink-0" />
        )}
      </div>

      {/* Big P&L number */}
      <div className="flex items-center justify-center gap-2 py-3 shrink-0">
        <NetIcon size={18} className={netColor} />
        <span
          data-testid="net-pnl"
          className={`font-mono tabular-nums font-bold text-2xl ${netColor}`}
        >
          {fmtSigned(netPnL)}
        </span>
      </div>

      {/* Equity curve */}
      <div className="shrink-0 px-2 h-16 flex">
        <EquityCurve snapshots={snapshots} />
      </div>

      {/* Stats row */}
      <div className="flex gap-1.5 px-2 py-2 shrink-0">
        <StatCard
          label="Realised"
          value={fmtSigned(realisedPnL)}
          colorCls={pnlColor(realisedPnL)}
        />
        <StatCard
          label="Unrealised"
          value={fmtSigned(unrealisedPnL)}
          colorCls={pnlColor(unrealisedPnL)}
        />
        <StatCard
          label="Peak P&L"
          value={fmtSigned(peakPnL)}
          colorCls={peakPnL > 0 ? "text-profit" : "text-text-muted"}
        />
        <StatCard
          label="Max DD"
          value={maxDrawdown > 0 ? `-${fmtINR(maxDrawdown)}` : "—"}
          colorCls={maxDrawdown > 0 ? "text-loss" : "text-text-muted"}
        />
      </div>

      {/* Per-strategy breakdown */}
      {showStrategies && (
        <div className="flex-1 overflow-auto px-2 pb-2">
          <p className="text-xxs text-text-muted uppercase tracking-wider mb-1">By Strategy</p>
          <div className="space-y-0.5">
            {byStrategy.map(({ strategy, pnl }) => (
              <div
                key={strategy}
                className="flex items-center justify-between px-2 py-0.5 rounded bg-surface-card border border-border-subtle"
              >
                <span className="text-xs text-text-secondary font-mono truncate max-w-32">{strategy}</span>
                <span className={`text-xs font-mono tabular-nums font-medium ${pnlColor(pnl)}`}>
                  {fmtSigned(pnl)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Loading state */}
      {state.loading && snapshots.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-text-muted text-xs">
          Loading positions…
        </div>
      )}
    </div>
  );
}

export default memo(IntradayPnLWidget);
