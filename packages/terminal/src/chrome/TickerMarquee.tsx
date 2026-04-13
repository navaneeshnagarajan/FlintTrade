/**
 * TickerMarquee — seamless auto-scrolling ticker for the TopBarV2 chrome.
 *
 * Modes:
 *   "off"     — hidden
 *   "pinned"  — static chips, no scroll
 *   "scroll"  — manual horizontal overflow scroll (touch/mouse)
 *   "marquee" — CSS animation seamless loop (default)
 *
 * Architecture:
 *   - Reads live prices from Jotai market atoms (indicesSummaryAtom)
 *   - Each chip: name (muted) · price · change% (green/red/amber)
 *   - Hover pauses animation (marquee mode)
 *   - Edge fade via mask-image for polish (marquee/scroll modes)
 *   - Content duplicated for seamless loop wrap-around (marquee mode)
 */

import { useAtomValue } from "jotai";
import { memo, useRef, useEffect, useState } from "react";
import { indicesSummaryAtom } from "@/atoms/marketAtoms";
import type { WsTick } from "@/types/api";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type TickerMode = "off" | "pinned" | "scroll" | "marquee";

export interface TickerSymbol {
  name: string;
  data: WsTick | null;
}

export interface TickerMarqueeProps {
  /** Display mode. Default: "marquee". */
  mode?: TickerMode;
  /**
   * Symbols to display. When omitted, component reads from indicesSummaryAtom
   * so callers don't need to thread Jotai through.
   */
  symbols?: TickerSymbol[];
  /** Pixels per second for marquee scroll. Default: 48. */
  speed?: number;
  className?: string;
}

// ---------------------------------------------------------------------------
// TickerChip — single instrument chip
// ---------------------------------------------------------------------------

type FlashDir = "up" | "down" | null;

interface TickerChipProps {
  name: string;
  data: WsTick | null;
}

const TickerChip = memo(function TickerChip({ name, data }: TickerChipProps) {
  const ltp = data?.ltp ?? null;
  const prevClose = data?.prevClose ?? data?.close ?? null;

  const pct =
    prevClose !== null && prevClose > 0 && ltp !== null && ltp > 0
      ? ((ltp - prevClose) / prevClose) * 100
      : (data?.pct ?? null);

  const hasLivePrice = ltp !== null && ltp > 0;

  // Flash on price tick
  const prevLtpRef = useRef<number | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [flash, setFlash] = useState<FlashDir>(null);

  useEffect(() => {
    if (ltp === null) return;
    const prev = prevLtpRef.current;
    if (prev !== null && prev !== ltp) {
      const dir: FlashDir = ltp > prev ? "up" : "down";
      setFlash(dir);
      if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current);
      flashTimerRef.current = setTimeout(() => {
        setFlash(null);
        flashTimerRef.current = null;
      }, 250);
    }
    prevLtpRef.current = ltp;
  }, [ltp]);

  useEffect(() => {
    return () => {
      if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current);
    };
  }, []);

  // Price colour: flash overrides the directional colour
  const priceColour =
    flash === "up"
      ? "text-profit"
      : flash === "down"
        ? "text-loss"
        : "text-text-primary";

  // Percentage badge colour
  const pctColour = pct === null
    ? "text-text-muted"
    : pct >= 0.1
      ? "text-profit"
      : pct <= -0.1
        ? "text-loss"
        : "text-amber-400";

  return (
    <span
      className="flex items-center gap-1.5 px-3 shrink-0 select-none"
      aria-label={
        hasLivePrice
          ? `${name}: ${ltp!.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${pct !== null ? `, ${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%` : ""}`
          : `${name}: no data`
      }
    >
      {/* Symbol name */}
      <span className="text-xs text-text-muted font-mono whitespace-nowrap">
        {name}
      </span>

      {/* Price */}
      <span
        aria-live="off"
        className={`text-xs font-mono tabular-nums transition-colors duration-200 whitespace-nowrap ${priceColour}`}
      >
        {hasLivePrice
          ? ltp!.toLocaleString("en-IN", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })
          : "\u2014"}
      </span>

      {/* Change % */}
      {hasLivePrice && pct !== null ? (
        <span className={`text-xs font-mono tabular-nums whitespace-nowrap ${pctColour}`}>
          {pct >= 0 ? "\u25b2" : "\u25bc"}
          {Math.abs(pct).toFixed(2)}%
        </span>
      ) : null}

      {/* Divider dot */}
      <span className="text-border-default/60 text-xs" aria-hidden="true">·</span>
    </span>
  );
});

// ---------------------------------------------------------------------------
// Inner strip (shared between duplicated sets for marquee)
// ---------------------------------------------------------------------------

function TickerStrip({ symbols }: { symbols: TickerSymbol[] }) {
  return (
    <>
      {symbols.map((sym, i) => (
        <TickerChip key={`${sym.name}-${i}`} name={sym.name} data={sym.data} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// TickerMarquee
// ---------------------------------------------------------------------------

export default function TickerMarquee({
  mode = "marquee",
  symbols: propSymbols,
  speed = 48,
  className = "",
}: TickerMarqueeProps) {
  // Fall back to Jotai atom when no symbols prop provided
  const atomSymbols = useAtomValue(indicesSummaryAtom);
  const symbols: TickerSymbol[] = propSymbols ?? atomSymbols;

  if (mode === "off" || symbols.length === 0) return null;

  // ── Pinned mode: static row, no scroll ──────────────────────────────────
  if (mode === "pinned") {
    return (
      <div
        className={`flex items-center overflow-hidden ${className}`}
        role="region"
        aria-label="Ticker prices"
      >
        {symbols.map((sym) => (
          <TickerChip key={sym.name} name={sym.name} data={sym.data} />
        ))}
      </div>
    );
  }

  // ── Scroll mode: manual horizontal overflow ──────────────────────────────
  if (mode === "scroll") {
    return (
      <div
        className={`flex items-center overflow-x-auto scrollbar-none ${className}`}
        style={{
          maskImage:
            "linear-gradient(90deg, transparent 0%, black 4%, black 96%, transparent 100%)",
          WebkitMaskImage:
            "linear-gradient(90deg, transparent 0%, black 4%, black 96%, transparent 100%)",
        }}
        role="region"
        aria-label="Ticker prices"
      >
        {symbols.map((sym) => (
          <TickerChip key={sym.name} name={sym.name} data={sym.data} />
        ))}
      </div>
    );
  }

  // ── Marquee mode: CSS keyframe, seamless loop ────────────────────────────
  // We duplicate the content so when the first copy has scrolled fully left,
  // the second copy is already in view — creating a seamless loop.
  //
  // Animation duration is computed from the symbol count × per-chip width
  // approximation (80px average) divided by speed (px/s).
  const estimatedWidth = symbols.length * 120; // ~120px average chip width
  const durationSec = estimatedWidth / speed;

  return (
    <div
      className={`relative overflow-hidden flex items-center ${className}`}
      style={{
        maskImage:
          "linear-gradient(90deg, transparent 0%, black 4%, black 96%, transparent 100%)",
        WebkitMaskImage:
          "linear-gradient(90deg, transparent 0%, black 4%, black 96%, transparent 100%)",
      }}
      role="region"
      aria-label="Ticker prices"
      data-testid="ticker-marquee"
    >
      {/*
       * Inline keyframe injection via a <style> tag keeps this self-contained
       * without requiring Tailwind JIT to know the exact duration at compile time.
       */}
      <style>{`
        @keyframes ticker-scroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .ticker-track {
          animation: ticker-scroll ${durationSec}s linear infinite;
          will-change: transform;
        }
        .ticker-track:hover,
        .ticker-track:focus-within {
          animation-play-state: paused;
        }
      `}</style>

      {/* Track: contains two identical copies for seamless wrap */}
      <div
        className="ticker-track flex items-center whitespace-nowrap"
        aria-hidden="true"
      >
        <TickerStrip symbols={symbols} />
        {/* Duplicate for seamless loop */}
        <TickerStrip symbols={symbols} />
      </div>

      {/* Screen-reader accessible summary (one polite region, not per-tick) */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {symbols
          .filter((s) => s.data?.ltp != null && (s.data.ltp ?? 0) > 0)
          .map((s) => `${s.name} ${s.data!.ltp}`)
          .join(", ")}
      </span>
    </div>
  );
}
