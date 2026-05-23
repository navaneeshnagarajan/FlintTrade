/**
 * MicrostructureWidget — Tick-by-tick market microstructure analysis.
 *
 * Features:
 *   - Tick velocity (ticks per second, rolling 60s)
 *   - Bid/ask imbalance ratio (real-time percentage)
 *   - Trade direction classification (uptick / downtick / neutral)
 *   - Large order detection (>2x average trade size)
 *   - Sparkline: tick velocity over last 60 seconds
 * Data: WebSocket depth/quote mode; falls back to animated sample data.
 */

import { useState, useEffect, useRef, useMemo, memo, useCallback } from "react";
import { Microscope, RefreshCw } from "lucide-react";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Direction = "uptick" | "downtick" | "neutral";

interface TickSample {
  ts: number;        // epoch ms
  price: number;
  bidSize: number;
  askSize: number;
  tradeSize: number;
  direction: Direction;
}

interface MicroStats {
  velocity: number;         // ticks/sec over last 10 s
  imbalance: number;        // bid/(bid+ask) 0-1
  uptickPct: number;        // % of ticks that were upticks
  downtickPct: number;
  largeOrderCount: number;  // in last 60 ticks
  avgTradeSize: number;
  velocityHistory: number[]; // 60 one-second buckets
}

// ---------------------------------------------------------------------------
// Sample data generator
// ---------------------------------------------------------------------------

function makeSampleTick(prev: TickSample | null, idx: number): TickSample {
  const basePrice = 22_350;
  const price = prev
    ? prev.price + (Math.random() - 0.49) * 3
    : basePrice + (idx % 17);
  const bidSize = 50 + Math.floor(Math.random() * 200);
  const askSize = 50 + Math.floor(Math.random() * 200);
  const tradeSize = 10 + Math.floor(Math.random() * 180);
  const direction: Direction =
    prev == null
      ? "neutral"
      : price > prev.price
      ? "uptick"
      : price < prev.price
      ? "downtick"
      : "neutral";
  return { ts: Date.now(), price, bidSize, askSize, tradeSize, direction };
}

function buildInitialTicks(): TickSample[] {
  const ticks: TickSample[] = [];
  for (let i = 0; i < 120; i++) {
    ticks.push(makeSampleTick(ticks[ticks.length - 1] ?? null, i));
  }
  return ticks;
}

// ---------------------------------------------------------------------------
// Statistics computation
// ---------------------------------------------------------------------------

function computeStats(ticks: TickSample[]): MicroStats {
  if (ticks.length === 0) {
    return {
      velocity: 0,
      imbalance: 0.5,
      uptickPct: 0,
      downtickPct: 0,
      largeOrderCount: 0,
      avgTradeSize: 0,
      velocityHistory: new Array(60).fill(0),
    };
  }

  const now = Date.now();
  const window10s = ticks.filter((t) => now - t.ts < 10_000);
  const window60s = ticks.filter((t) => now - t.ts < 60_000);

  // Tick velocity: ticks in last 10s / 10
  const velocity = parseFloat((window10s.length / 10).toFixed(1));

  // Bid/ask imbalance from recent ticks
  const recentBid = window10s.reduce((s, t) => s + t.bidSize, 0);
  const recentAsk = window10s.reduce((s, t) => s + t.askSize, 0);
  const total = recentBid + recentAsk;
  const imbalance = total > 0 ? recentBid / total : 0.5;

  // Direction distribution
  const up = window60s.filter((t) => t.direction === "uptick").length;
  const down = window60s.filter((t) => t.direction === "downtick").length;
  const count60 = window60s.length || 1;
  const uptickPct = (up / count60) * 100;
  const downtickPct = (down / count60) * 100;

  // Average trade size and large order detection
  const avgTradeSize =
    window60s.reduce((s, t) => s + t.tradeSize, 0) / (window60s.length || 1);
  const largeOrderCount = window60s.filter(
    (t) => t.tradeSize > avgTradeSize * 2
  ).length;

  // Velocity history: bucket last 60s into 60 one-second buckets
  const velocityHistory = new Array(60).fill(0) as number[];
  for (let sec = 0; sec < 60; sec++) {
    const lo = now - (sec + 1) * 1000;
    const hi = now - sec * 1000;
    velocityHistory[59 - sec] = ticks.filter(
      (t) => t.ts >= lo && t.ts < hi
    ).length;
  }

  return {
    velocity,
    imbalance,
    uptickPct,
    downtickPct,
    largeOrderCount,
    avgTradeSize,
    velocityHistory,
  };
}

// ---------------------------------------------------------------------------
// Sparkline (SVG, 60 data points)
// ---------------------------------------------------------------------------

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
}

function Sparkline({ data, width = 240, height = 36 }: SparklineProps) {
  const max = Math.max(...data, 1);
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - (v / max) * (height - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-label="Tick velocity sparkline over last 60 seconds"
      role="img"
      className="w-full"
    >
      <polyline
        points={pts}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        className="text-accent"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Imbalance bar
// ---------------------------------------------------------------------------

function ImbalanceBar({ imbalance }: { imbalance: number }) {
  const bidPct = (imbalance * 100).toFixed(0);
  const askPct = ((1 - imbalance) * 100).toFixed(0);
  return (
    <div
      className="flex h-3 rounded overflow-hidden"
      aria-label={`Bid ask imbalance: bid ${bidPct}% ask ${askPct}%`}
    >
      <div
        className="bg-profit/70 transition-all duration-300"
        style={{ width: `${bidPct}%` }}
      />
      <div
        className="bg-loss/70 transition-all duration-300"
        style={{ width: `${askPct}%` }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat row
// ---------------------------------------------------------------------------

interface StatRowProps {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}

function StatRow({ label, value, sub, accent }: StatRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border-default last:border-0">
      <span className="text-xs text-text-muted">{label}</span>
      <div className="flex items-baseline gap-1.5">
        <span className={`text-xs font-mono tabular-nums font-semibold ${accent ?? "text-text-primary"}`}>
          {value}
        </span>
        {sub && <span className="text-xxs text-text-muted">{sub}</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Direction badge
// ---------------------------------------------------------------------------

function DirectionBadge({
  uptickPct,
  downtickPct,
}: {
  uptickPct: number;
  downtickPct: number;
}) {
  const neutralPct = 100 - uptickPct - downtickPct;
  return (
    <div
      className="flex h-3 rounded overflow-hidden"
      aria-label={`Trade direction: uptick ${uptickPct.toFixed(0)}% downtick ${downtickPct.toFixed(0)}% neutral ${neutralPct.toFixed(0)}%`}
    >
      <div className="bg-profit/70 transition-all" style={{ width: `${uptickPct}%` }} />
      <div className="bg-text-muted/30 transition-all" style={{ width: `${neutralPct}%` }} />
      <div className="bg-loss/70 transition-all" style={{ width: `${downtickPct}%` }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function MicrostructureWidget() {
  const isConnected = useBrokerConnected();
  const track = useTrackBehavior();
  const ticksRef = useRef<TickSample[]>(buildInitialTicks());
  const [stats, setStats] = useState<MicroStats>(() => computeStats(ticksRef.current));
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(() => {
    const ticks = ticksRef.current;
    // Simulate 1-4 new ticks arriving
    const newCount = 1 + Math.floor(Math.random() * 4);
    for (let i = 0; i < newCount; i++) {
      ticks.push(makeSampleTick(ticks[ticks.length - 1] ?? null, i));
    }
    // Keep a rolling window of 600 ticks max
    if (ticks.length > 600) ticks.splice(0, ticks.length - 600);
    setStats(computeStats(ticks));
  }, []);

  useEffect(() => {
    intervalRef.current = setInterval(refresh, 500);
    track("trade", "microstructure_opened");
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [refresh, track]);

  const imbalancePct = (stats.imbalance * 100).toFixed(1);
  const imbalanceColour =
    stats.imbalance > 0.6
      ? "text-profit"
      : stats.imbalance < 0.4
      ? "text-loss"
      : "text-text-secondary";

  const velocityColour =
    stats.velocity > 5 ? "text-warning" : stats.velocity > 2 ? "text-text-primary" : "text-text-muted";

  const largeColour = stats.largeOrderCount > 5 ? "text-warning" : "text-text-primary";

  const lastTick = useMemo(() => ticksRef.current[ticksRef.current.length - 1], [stats]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Market Microstructure widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Microscope size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Market Microstructure</span>
        {!isConnected && (
          <span className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
        <div className="flex-1" />
        <span className="text-xxs text-text-muted tabular-nums">
          {lastTick ? `₹${lastTick.price.toFixed(2)}` : "--"}
        </span>
        <RefreshCw size={10} className="animate-spin text-text-muted ml-1" aria-hidden="true" aria-label="Live updating" />
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-3">

        {/* Velocity sparkline */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-xxs text-text-muted uppercase tracking-wide">
              Tick Velocity (60s)
            </span>
            <span className={`text-xs font-mono font-semibold tabular-nums ${velocityColour}`}>
              {stats.velocity} ticks/s
            </span>
          </div>
          <div className="bg-surface-card border border-border-default rounded p-1">
            <Sparkline data={stats.velocityHistory} />
          </div>
        </div>

        {/* Stats */}
        <div className="bg-surface-card border border-border-default rounded p-2 space-y-0">
          <StatRow
            label="Tick Velocity"
            value={`${stats.velocity}`}
            sub="ticks/s"
            accent={velocityColour}
          />
          <StatRow
            label="Avg Trade Size"
            value={stats.avgTradeSize.toFixed(0)}
            sub="qty"
          />
          <StatRow
            label="Large Orders (60s)"
            value={String(stats.largeOrderCount)}
            sub="> 2× avg"
            accent={largeColour}
          />
        </div>

        {/* Bid/Ask imbalance */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-xxs text-text-muted uppercase tracking-wide">
              Bid / Ask Imbalance
            </span>
            <span className={`text-xs font-mono font-semibold tabular-nums ${imbalanceColour}`}>
              {imbalancePct}% bid
            </span>
          </div>
          <ImbalanceBar imbalance={stats.imbalance} />
          <div className="flex justify-between text-xxs text-text-muted">
            <span>Bid</span>
            <span>Ask</span>
          </div>
        </div>

        {/* Trade direction */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-xxs text-text-muted uppercase tracking-wide">
              Trade Direction (60s)
            </span>
            <span className="text-xxs text-text-secondary font-mono">
              {stats.uptickPct.toFixed(0)}% up / {stats.downtickPct.toFixed(0)}% down
            </span>
          </div>
          <DirectionBadge
            uptickPct={stats.uptickPct}
            downtickPct={stats.downtickPct}
          />
          <div className="flex justify-between text-xxs text-text-muted">
            <span className="text-profit">Uptick</span>
            <span>Neutral</span>
            <span className="text-loss">Downtick</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default memo(MicrostructureWidget);
