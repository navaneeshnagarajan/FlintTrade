/**
 * TickerWidget — horizontal scrolling price tape for FlintTrade terminal.
 *
 * Features:
 *   - Continuously scrolling bar of instrument prices
 *   - Per-chip: symbol, LTP, change, change% — green/red coloring
 *   - Powered by Jotai tickAtomFamily for live WebSocket prices
 *   - CSS keyframe animation — pauses on hover
 *   - Default instruments: indices + top equities
 */

import { useAtomValue } from "jotai";
import { TrendingUp, TrendingDown } from "lucide-react";
import { tickAtomFamily } from "@/atoms/marketAtoms";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TickerInstrument {
  symbol: string;
  exchange: string;
  label: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_INSTRUMENTS: TickerInstrument[] = [
  { symbol: "NIFTY",     exchange: "NSE_INDEX", label: "NIFTY 50"  },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX", label: "BANK NIFTY" },
  { symbol: "SENSEX",    exchange: "BSE_INDEX", label: "SENSEX"    },
  { symbol: "RELIANCE",  exchange: "NSE",       label: "RELIANCE"  },
  { symbol: "HDFCBANK",  exchange: "NSE",       label: "HDFCBANK"  },
  { symbol: "INFY",      exchange: "NSE",       label: "INFY"      },
  { symbol: "TCS",       exchange: "NSE",       label: "TCS"       },
  { symbol: "ICICIBANK", exchange: "NSE",       label: "ICICIBANK" },
];

const FMT = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtPrice(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  return FMT.format(Number(v));
}

function fmtChange(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "";
  const n = Number(v);
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

// ---------------------------------------------------------------------------
// Single price chip
// ---------------------------------------------------------------------------

interface PriceChipProps {
  instrument: TickerInstrument;
}

function PriceChip({ instrument }: PriceChipProps) {
  const key = `${instrument.exchange}:${instrument.symbol}`;
  const tick = useAtomValue(tickAtomFamily(key));

  const ltp = tick?.ltp ?? null;
  const pct = tick?.pct ?? null;
  const isUp = pct == null ? null : pct >= 0;

  const priceColor =
    isUp === true
      ? "text-profit"
      : isUp === false
      ? "text-loss"
      : "text-text-secondary";

  return (
    <div className="flex items-center gap-1.5 px-3 py-0 shrink-0 border-r border-border-subtle last:border-r-0">
      {/* Label */}
      <span className="text-xs text-text-muted font-medium uppercase tracking-wide whitespace-nowrap">
        {instrument.label}
      </span>

      {/* LTP */}
      <span className={`text-xs font-mono tabular-nums font-semibold whitespace-nowrap ${priceColor}`}>
        {fmtPrice(ltp)}
      </span>

      {/* Change% with icon */}
      {pct != null && (
        <span className={`flex items-center gap-0.5 text-xxs font-mono tabular-nums whitespace-nowrap ${priceColor}`}>
          {isUp === true ? (
            <TrendingUp size={8} />
          ) : (
            <TrendingDown size={8} />
          )}
          {fmtChange(pct)}
        </span>
      )}

      {/* No data indicator */}
      {ltp == null && (
        <span className="text-xxs text-text-muted">–</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ticker track — doubled for seamless loop
// ---------------------------------------------------------------------------

function TickerTrack() {
  // Render instruments twice so the scroll loop is seamless
  const instruments = [...DEFAULT_INSTRUMENTS, ...DEFAULT_INSTRUMENTS];

  return (
    <div className="flex items-center h-full ticker-track">
      {instruments.map((inst, idx) => (
        <PriceChip key={`${inst.symbol}-${idx}`} instrument={inst} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface TickerWidgetProps {
  node?: unknown;
}

export default function TickerWidget({ node: _node }: TickerWidgetProps) {
  return (
    <>
      {/*
        Inline keyframes — Tailwind v4 does not support arbitrary @keyframes
        via className, so we inject a <style> tag once per mount.
      */}
      <style>{`
        @keyframes ticker-scroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .ticker-track {
          animation: ticker-scroll 40s linear infinite;
          will-change: transform;
        }
        .ticker-viewport:hover .ticker-track {
          animation-play-state: paused;
        }
      `}</style>

      <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">

        {/* HEADER */}
        <div className="flex items-center gap-2 px-2 py-0.5 border-b border-border-default bg-surface-card shrink-0">
          <span className="font-heading font-semibold text-xxs text-text-muted uppercase tracking-widest">
            Live Prices
          </span>
        </div>

        {/* SCROLLING TAPE */}
        <div className="ticker-viewport flex-1 overflow-hidden flex items-center cursor-default select-none">
          <TickerTrack />
        </div>
      </div>
    </>
  );
}
