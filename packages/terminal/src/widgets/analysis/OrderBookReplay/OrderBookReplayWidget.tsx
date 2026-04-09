/**
 * OrderBookReplayWidget — Order book snapshot replay for FlintTrade.
 *
 * Replays a sequence of historical bid/ask depth snapshots.
 * Shows bid/ask ladder with quantity bars, spread, and imbalance ratio.
 * Play/pause/speed controls and time scrubber.
 */

import { useState, useEffect, useRef, useCallback, memo } from "react";
import {
  Play,
  Pause,
  RotateCcw,
  BarChart3,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { SAMPLE_SNAPSHOTS } from "./sampleData";
import type { OrderBookSnapshot, DepthLevel } from "./sampleData";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

type Speed = 1 | 2 | 4 | 8;
const SPEEDS: Speed[] = [1, 2, 4, 8];
const TICK_MS: Record<Speed, number> = { 1: 800, 2: 400, 4: 200, 8: 100 };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(v: number): string {
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(v);
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

function calcImbalance(snap: OrderBookSnapshot): number {
  const totalBid = snap.buy.reduce((s, l) => s + l.quantity, 0);
  const totalAsk = snap.sell.reduce((s, l) => s + l.quantity, 0);
  const sum = totalBid + totalAsk;
  return sum > 0 ? (totalBid - totalAsk) / sum : 0;
}

// ---------------------------------------------------------------------------
// Depth ladder row
// ---------------------------------------------------------------------------

interface LadderRowProps {
  level: DepthLevel;
  maxQty: number;
  side: "bid" | "ask";
}

function LadderRow({ level, maxQty, side }: LadderRowProps) {
  const barPct = maxQty > 0 ? (level.quantity / maxQty) * 100 : 0;
  const isBid = side === "bid";

  return (
    <tr className="relative h-6">
      {/* Bid side: qty | bar | price */}
      {isBid ? (
        <>
          <td className="w-20 text-right pr-1 text-xxs font-mono tabular-nums text-profit z-10 relative">
            {level.quantity.toLocaleString("en-IN")}
          </td>
          <td className="w-24 relative overflow-hidden">
            <div
              className="absolute inset-y-0.5 right-0 bg-profit/20 rounded-l transition-all duration-150"
              style={{ width: `${barPct}%` }}
              aria-hidden="true"
            />
            <span className="relative z-10 text-xxs text-text-muted font-mono px-1 tabular-nums">
              {level.orders}
            </span>
          </td>
          <td className="w-20 text-right pr-2 text-xs font-mono tabular-nums font-semibold text-profit">
            {fmt(level.price)}
          </td>
        </>
      ) : (
        <>
          <td className="w-20 pl-2 text-left text-xs font-mono tabular-nums font-semibold text-loss">
            {fmt(level.price)}
          </td>
          <td className="w-24 relative overflow-hidden">
            <div
              className="absolute inset-y-0.5 left-0 bg-loss/20 rounded-r transition-all duration-150"
              style={{ width: `${barPct}%` }}
              aria-hidden="true"
            />
            <span className="relative z-10 text-xxs text-text-muted font-mono px-1 tabular-nums">
              {level.orders}
            </span>
          </td>
          <td className="w-20 text-left pl-1 text-xxs font-mono tabular-nums text-loss">
            {level.quantity.toLocaleString("en-IN")}
          </td>
        </>
      )}
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Scrubber
// ---------------------------------------------------------------------------

interface ScrubberProps {
  index: number;
  total: number;
  onSeek: (i: number) => void;
}

function Scrubber({ index, total, onSeek }: ScrubberProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const pct = total > 1 ? (index / (total - 1)) * 100 : 0;

  const seekFrom = useCallback(
    (clientX: number) => {
      const rect = trackRef.current?.getBoundingClientRect();
      if (!rect || total <= 1) return;
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      onSeek(Math.round(ratio * (total - 1)));
    },
    [total, onSeek],
  );

  return (
    <div
      ref={trackRef}
      role="slider"
      aria-valuemin={0}
      aria-valuemax={total - 1}
      aria-valuenow={index}
      aria-label="Replay position"
      tabIndex={0}
      className="relative flex-1 h-1.5 bg-border-default rounded-full cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); seekFrom(e.clientX); }}
      onPointerMove={(e) => { if (e.buttons === 1) seekFrom(e.clientX); }}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") { e.preventDefault(); onSeek(Math.max(0, index - 1)); }
        else if (e.key === "ArrowRight") { e.preventDefault(); onSeek(Math.min(total - 1, index + 1)); }
      }}
    >
      <div className="absolute inset-y-0 left-0 bg-accent rounded-full pointer-events-none" style={{ width: `${pct}%` }} />
      <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-accent shadow-sm pointer-events-none" style={{ left: `${pct}%` }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function OrderBookReplayWidget() {
  const track = useTrackBehavior();

  const [snapshots] = useState<OrderBookSnapshot[]>(SAMPLE_SNAPSHOTS);
  const [index, setIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(1);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    track("trade", "widget_view_order_book_replay");
  }, [track]);

  const stopTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }, []);

  const startTimer = useCallback(() => {
    stopTimer();
    timerRef.current = setInterval(() => {
      setIndex((i) => {
        if (i >= snapshots.length - 1) {
          setIsPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, TICK_MS[speed]);
  }, [speed, snapshots.length, stopTimer]);

  useEffect(() => {
    if (isPlaying) startTimer(); else stopTimer();
    return stopTimer;
  }, [isPlaying, startTimer, stopTimer]);

  // Keyboard shortcuts
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === " " || e.key === "k") { e.preventDefault(); setIsPlaying((p) => !p); }
      else if (e.key === "ArrowLeft" && !e.shiftKey) { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)); }
      else if (e.key === "ArrowRight" && !e.shiftKey) { e.preventDefault(); setIndex((i) => Math.min(snapshots.length - 1, i + 1)); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [snapshots.length]);

  const snap = snapshots[index];
  if (!snap) return null;

  const spread = snap.sell[0] && snap.buy[0]
    ? Math.abs(snap.sell[0].price - snap.buy[0].price)
    : 0;
  const imbalance = calcImbalance(snap);
  const maxBidQty = Math.max(...snap.buy.map((l) => l.quantity));
  const maxAskQty = Math.max(...snap.sell.map((l) => l.quantity));
  const maxQty = Math.max(maxBidQty, maxAskQty);

  // Cumulative depth
  let cumBid = 0, cumAsk = 0;
  snap.buy.forEach((l) => { cumBid += l.quantity; });
  snap.sell.forEach((l) => { cumAsk += l.quantity; });

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <BarChart3 size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Order Book Replay</span>
        <span className="text-xxs text-text-muted border border-border-subtle rounded px-1.5 py-0.5 ml-1">sample</span>
        <div className="flex-1" />
        <span className="text-xxs font-mono tabular-nums text-text-muted">
          {fmtTime(snap.timestamp)} IST
        </span>
      </div>

      {/* Stats bar */}
      <div className="flex-none flex items-center gap-4 px-3 py-1.5 bg-surface-elevated border-b border-border-subtle text-xxs">
        <div className="flex items-center gap-1">
          <span className="text-text-muted">Spread</span>
          <span className="font-mono tabular-nums text-warning">{fmt(spread)}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-text-muted">Imbalance</span>
          <span className={cn("font-mono tabular-nums font-semibold", imbalance > 0.1 ? "text-profit" : imbalance < -0.1 ? "text-loss" : "text-text-secondary")}>
            {imbalance > 0 ? "+" : ""}{(imbalance * 100).toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-profit font-mono tabular-nums">{cumBid.toLocaleString("en-IN")}</span>
          <span className="text-text-muted">/</span>
          <span className="text-loss font-mono tabular-nums">{cumAsk.toLocaleString("en-IN")}</span>
        </div>
      </div>

      {/* Order book ladder */}
      <div className="flex-1 overflow-auto flex flex-col" role="region" aria-label="Order book ladder">
        {/* Column headers */}
        <div className="flex-none grid grid-cols-2 px-2 py-1 border-b border-border-subtle text-xxs text-text-muted">
          <div className="flex items-center gap-1 justify-end pr-1">
            <span>Qty</span>
            <span className="px-4">Ords</span>
            <span className="pr-1">Bid</span>
          </div>
          <div className="flex items-center gap-1 pl-1">
            <span>Ask</span>
            <span className="px-4">Ords</span>
            <span>Qty</span>
          </div>
        </div>

        {/* Bid/Ask rows side by side */}
        <div className="flex-1 overflow-auto">
          <table className="w-full border-separate border-spacing-0" aria-label="Bid and ask price levels">
            <tbody>
              {Array.from({ length: Math.max(snap.buy.length, snap.sell.length) }, (_, i) => (
                <tr key={i} className="hover:bg-surface-hover transition-colors">
                  {/* Bid */}
                  <td className="w-1/2 p-0">
                    {snap.buy[i] ? (
                      <table className="w-full">
                        <tbody>
                          <LadderRow level={snap.buy[i]} maxQty={maxQty} side="bid" />
                        </tbody>
                      </table>
                    ) : <div className="h-6" />}
                  </td>
                  {/* Divider */}
                  <td className="w-px bg-border-default" />
                  {/* Ask */}
                  <td className="w-1/2 p-0">
                    {snap.sell[i] ? (
                      <table className="w-full">
                        <tbody>
                          <LadderRow level={snap.sell[i]} maxQty={maxQty} side="ask" />
                        </tbody>
                      </table>
                    ) : <div className="h-6" />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Controls */}
      <div
        role="toolbar"
        aria-label="Order book replay controls"
        className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-t border-border-default"
      >
        {/* Play/Pause */}
        <button
          onClick={() => setIsPlaying((p) => !p)}
          aria-label={isPlaying ? "Pause replay" : "Play replay"}
          title={`${isPlaying ? "Pause" : "Play"} (Space/k)`}
          className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
        >
          {isPlaying ? <Pause size={13} /> : <Play size={13} />}
        </button>

        {/* Reset */}
        <button
          onClick={() => { setIsPlaying(false); setIndex(0); }}
          aria-label="Reset to start"
          className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
        >
          <RotateCcw size={12} />
        </button>

        {/* Step back */}
        <button
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
          aria-label="Step back one snapshot"
          className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
          disabled={index === 0}
        >
          <ChevronLeft size={13} />
        </button>

        {/* Step forward */}
        <button
          onClick={() => setIndex((i) => Math.min(snapshots.length - 1, i + 1))}
          aria-label="Step forward one snapshot"
          className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
          disabled={index === snapshots.length - 1}
        >
          <ChevronRight size={13} />
        </button>

        {/* Divider */}
        <div className="w-px h-4 bg-border-default" aria-hidden="true" />

        {/* Speed */}
        <div className="flex items-center gap-0.5" role="group" aria-label="Replay speed">
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              aria-pressed={speed === s}
              aria-label={`${s}x speed`}
              className={cn(
                "px-2 py-0.5 text-xxs font-mono rounded transition-colors",
                speed === s
                  ? "bg-accent/20 text-accent border border-accent/50"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
            >
              {s}x
            </button>
          ))}
        </div>

        {/* Divider */}
        <div className="w-px h-4 bg-border-default" aria-hidden="true" />

        {/* Scrubber */}
        <span className="text-xxs font-mono text-text-muted tabular-nums w-6 text-right shrink-0">
          {index + 1}
        </span>
        <Scrubber index={index} total={snapshots.length} onSeek={setIndex} />
        <span className="text-xxs font-mono text-text-muted tabular-nums w-6 shrink-0">
          {snapshots.length}
        </span>
      </div>
    </div>
  );
}

export default memo(OrderBookReplayWidget);
