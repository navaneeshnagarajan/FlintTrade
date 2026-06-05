/**
 * TickSpeedWidget — WebSocket tick delivery speed and feed-health monitor.
 *
 * When the live WS feed is up the metrics are MEASURED, not simulated:
 *   - Ticks per second — counted directly from the shared WS service tick
 *     stream over a rolling 1-second window.
 *   - Last tick — real age of the most recent tick (WS diagnostics.tickAgeMs),
 *     the honest signal for a stale/frozen feed.
 *   - Reconnections — real cumulative reconnect count from WS diagnostics.
 *   - Connection quality — derived from the measured tick rate.
 *
 * Mini spark chart: measured tick-rate trend over the last 5 minutes.
 *
 * When the feed is DOWN, a clearly-badged "Sample" preview is shown (the
 * isConnected guard + visible badge required by the no-fabricated-data rule).
 * Round-trip latency and dropped-tick % are intentionally NOT shown — neither
 * is measurable from the browser without server sequence numbers, so we do not
 * invent them.
 */

import { useState, useEffect, useRef, memo } from "react";
import { Gauge, Wifi, WifiOff } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useConnectionStore } from "@/stores/connectionStore";
import { getWsService } from "@/services/websocket";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Quality = "excellent" | "good" | "fair" | "poor";

interface TickMetrics {
  ticksPerSec: number;
  /** Milliseconds since the last tick; -1 when no tick has ever arrived. */
  lastTickAgeMs: number;
  reconnectCount: number;
  quality: Quality;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SPARK_SAMPLES = 300; // 5 minutes at 1/s
const UPDATE_INTERVAL_MS = 1000;

const QUALITY_THRESHOLDS: { min: number; quality: Quality }[] = [
  { min: 50,  quality: "excellent" },
  { min: 20,  quality: "good" },
  { min: 5,   quality: "fair" },
  { min: 0,   quality: "poor" },
];

const QUALITY_COLOURS: Record<Quality, string> = {
  excellent: "text-profit",
  good:      "text-accent",
  fair:      "text-warning",
  poor:      "text-loss",
};

const QUALITY_DOT: Record<Quality, string> = {
  excellent: "bg-profit",
  good:      "bg-accent",
  fair:      "bg-warning",
  poor:      "bg-loss",
};

// ---------------------------------------------------------------------------
// Sample preview shown only behind the "Sample" badge (feed down)
// ---------------------------------------------------------------------------

const SAMPLE_METRICS: TickMetrics = {
  ticksPerSec:   84,
  lastTickAgeMs: 120,
  reconnectCount: 0,
  quality: "excellent",
};

function simulateSpark(): number[] {
  const arr: number[] = [];
  let v = 80;
  for (let i = 0; i < SPARK_SAMPLES; i++) {
    v = Math.max(0, v + (Math.random() - 0.48) * 12);
    arr.push(v);
  }
  return arr;
}

function emptySpark(): number[] {
  return new Array(SPARK_SAMPLES).fill(0);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function deriveQuality(ticksPerSec: number): Quality {
  for (const { min, quality } of QUALITY_THRESHOLDS) {
    if (ticksPerSec >= min) return quality;
  }
  return "poor";
}

/** Human-readable age of the most recent tick. */
export function formatTickAge(ageMs: number): string {
  if (ageMs < 0) return "—";
  if (ageMs < 1000) return `${ageMs} ms`;
  return `${(ageMs / 1000).toFixed(1)} s`;
}

// ---------------------------------------------------------------------------
// Spark chart
// ---------------------------------------------------------------------------

function SparkChart({ data }: { data: number[] }) {
  if (data.length < 2) return null;

  return (
    <FlintMiniSparkline
      points={data}
      positive
      ariaLabel="Tick rate over last 5 minutes"
      className="h-full w-full text-accent"
    />
  );
}

// ---------------------------------------------------------------------------
// Metric row
// ---------------------------------------------------------------------------

function MetricRow({ label, value, unit, valueClass }: {
  label: string;
  value: string | number;
  unit?: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xxs text-text-muted">{label}</span>
      <span className={cn("text-xs font-mono tabular-nums font-semibold", valueClass ?? "text-text-primary")}>
        {value}{unit && <span className="text-xxs text-text-muted ml-0.5">{unit}</span>}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function TickSpeedWidget() {
  const track = useTrackBehavior();
  // The tick feed rides the WebSocket, so wsConnected — not the REST ping
  // status — is the honest "is the feed live?" signal for this widget.
  const wsConnected = useConnectionStore((s) => s.wsConnected);

  const [metrics, setMetrics] = useState<TickMetrics>(SAMPLE_METRICS);
  const [spark, setSpark] = useState<number[]>(() => simulateSpark());

  // Mutable per-second tick counter incremented in the onTick callback.
  const tickCounter = useRef(0);

  useEffect(() => {
    track("trade", "widget_view_tick_speed");
  }, [track]);

  useEffect(() => {
    if (!wsConnected) {
      // Feed down — show the clearly-badged sample preview.
      setSpark(simulateSpark());
      setMetrics(SAMPLE_METRICS);
      return;
    }

    const ws = getWsService();
    if (!ws) {
      // Store says connected but the WS singleton is absent — show an honest
      // empty state rather than fabricated numbers.
      setSpark(emptySpark());
      setMetrics({ ticksPerSec: 0, lastTickAgeMs: -1, reconnectCount: 0, quality: "poor" });
      return;
    }

    setSpark(emptySpark());
    tickCounter.current = 0;
    const offTick = ws.onTick(() => {
      tickCounter.current += 1;
    });

    const id = setInterval(() => {
      const tps = tickCounter.current;
      tickCounter.current = 0;
      const diag = ws.diagnostics;
      setMetrics({
        ticksPerSec: tps,
        lastTickAgeMs: diag.tickAgeMs,
        reconnectCount: diag.reconnectCount,
        quality: deriveQuality(tps),
      });
      setSpark((prev) => [...prev.slice(1), tps]);
    }, UPDATE_INTERVAL_MS);

    return () => {
      offTick();
      clearInterval(id);
    };
  }, [wsConnected]);

  const quality = metrics.quality;
  // When the feed is down the quality is not meaningful — show a neutral "Idle"
  // rather than a green "Excellent" next to the disconnected/Sample badges.
  const qualityLabel = wsConnected
    ? quality.charAt(0).toUpperCase() + quality.slice(1)
    : "Idle";
  const qualityColour = wsConnected ? QUALITY_COLOURS[quality] : "text-text-muted";
  const qualityDot = wsConnected ? QUALITY_DOT[quality] : "bg-text-muted/50";

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Tick Speed widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2.5 py-1.5 bg-surface-card border-b border-border-default">
        <Gauge size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Tick Speed</span>
        <div className="flex-1" />
        {/* Connection quality badge */}
        <span
          className={cn("flex items-center gap-1 text-xxs font-medium", qualityColour)}
          aria-label={`Connection quality: ${qualityLabel}`}
        >
          <span className={cn("inline-block w-1.5 h-1.5 rounded-full", qualityDot)} aria-hidden="true" />
          {qualityLabel}
        </span>
        {wsConnected
          ? <Wifi size={12} className="text-profit" aria-label="Connected" />
          : <WifiOff size={12} className="text-text-muted" aria-label="Disconnected" />
        }
        {!wsConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
      </div>

      {/* Metrics */}
      <div className="flex-none px-2.5 py-2 space-y-1.5 border-b border-border-subtle">
        <MetricRow
          label="Ticks / second"
          value={metrics.ticksPerSec}
          unit="t/s"
          valueClass={cn("font-semibold", QUALITY_COLOURS[quality])}
        />
        <MetricRow
          label="Last tick"
          value={formatTickAge(metrics.lastTickAgeMs)}
          valueClass={
            metrics.lastTickAgeMs < 0
              ? "text-text-muted"
              : metrics.lastTickAgeMs < 2000
                ? "text-profit"
                : "text-warning"
          }
        />
        <MetricRow
          label="Reconnections"
          value={metrics.reconnectCount}
          valueClass={metrics.reconnectCount > 0 ? "text-warning" : "text-text-primary"}
        />
      </div>

      {/* Spark chart */}
      <div className="flex-1 min-h-0 px-2.5 py-2 flex flex-col gap-1">
        <div className="text-xxs text-text-muted uppercase tracking-wide">
          Tick rate — last 5 min
        </div>
        <div className="flex-1 min-h-0">
          <SparkChart data={spark} />
        </div>
        <div className="flex justify-between text-xxs text-text-muted font-mono">
          <span>5m ago</span>
          <span>now</span>
        </div>
      </div>
    </div>
  );
}

export default memo(TickSpeedWidget);
