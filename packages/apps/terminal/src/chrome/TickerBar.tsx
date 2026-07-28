import { useAtomValue } from "jotai";
import { useRef, useEffect, useState, memo } from "react";
import { useNavigate } from "react-router";
import { indicesSummaryAtom } from "@/atoms/marketAtoms";
import { GlossaryTooltip } from "@/components/ui/GlossaryTooltip";
import { isMarketHours } from "@/lib/market";
import type { WsTick } from "@/types/api";

// MCX commodity instruments — these stay visible even when NSE/BSE is closed
// because MCX trades until 23:30 IST on weekdays.
const MCX_NAMES = new Set(["GOLD", "SILVER", "CRUDEOIL", "NATGAS"]);

/** True when the MCX session is currently active (weekdays 09:00–23:30 IST). */
function isMcxOpen(): boolean {
  return isMarketHours("MCX");
}

interface IndexChipProps {
  name: string;
  data: WsTick | null;
}

type FlashDirection = "up" | "down" | null;

function hasAnyLiveData(indices: { data: WsTick | null }[]): boolean {
  return indices.some((idx) => idx.data !== null && (idx.data.ltp ?? 0) !== 0);
}

const IndexChip = memo(function IndexChip({ name, data }: IndexChipProps) {
  const ltp = data?.ltp ?? null;
  // Prefer prevClose (fetched from REST by usePrevClose hook) for accurate change%.
  // LTP-mode WebSocket does not send close/change/pct — those fields are always
  // undefined in real-time mode. Fall back to data.change/pct only if prevClose
  // is not yet available (e.g. first render before REST resolves).
  const prevClose = data?.prevClose ?? data?.close ?? null;
  const change =
    prevClose !== null && prevClose > 0 && ltp !== null && ltp > 0
      ? ltp - prevClose
      : (data?.change ?? null);
  const pct =
    prevClose !== null && prevClose > 0 && ltp !== null && ltp > 0
      ? ((ltp - prevClose) / prevClose) * 100
      : (data?.pct ?? null);
  const isUp = (change ?? 0) >= 0;

  // Track previous LTP to detect price direction changes
  const prevLtpRef = useRef<number | null>(null);
  const flashTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [flash, setFlash] = useState<FlashDirection>(null);

  useEffect(() => {
    if (ltp === null) return;

    const prev = prevLtpRef.current;
    if (prev !== null && prev !== ltp) {
      const direction: FlashDirection = ltp > prev ? "up" : "down";
      setFlash(direction);

      // Clear any pending reset before scheduling a new one
      if (flashTimeoutRef.current !== null) {
        clearTimeout(flashTimeoutRef.current);
      }
      flashTimeoutRef.current = setTimeout(() => {
        setFlash(null);
        flashTimeoutRef.current = null;
      }, 200);
    }

    prevLtpRef.current = ltp;
  }, [ltp]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (flashTimeoutRef.current !== null) {
        clearTimeout(flashTimeoutRef.current);
      }
    };
  }, []);

  const ltpColorClass =
    flash === "up"
      ? "text-profit"
      : flash === "down"
        ? "text-loss"
        : "text-text-primary";

  return (
    <div className="flex items-center gap-2 px-3 shrink-0 border-r border-border-default last:border-r-0 h-full">
      <span className="text-xs text-text-muted">
        {name === "VIX" ? <GlossaryTooltip term="VIX">{name}</GlossaryTooltip> : name}
      </span>
      <span
        aria-live="off"
        className={`text-xs font-mono tabular-nums transition-colors duration-200 ${ltpColorClass}`}
      >
        {ltp !== null && ltp > 0
          ? ltp.toLocaleString("en-IN", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })
          : "\u2014"}
      </span>
      {ltp !== null && ltp > 0 && pct !== null ? (
        <span
          className={`text-xs font-mono tabular-nums rounded px-1 ${
            isUp ? "bg-bullish-bg text-bullish-text" : "bg-bearish-bg text-bearish-text"
          }`}
        >
          {isUp ? "\u25b2" : "\u25bc"}{Math.abs(pct).toFixed(2)}%
        </span>
      ) : ltp !== null && ltp > 0 ? (
        <span className="text-xs text-text-disabled">{"\u2014"}</span>
      ) : null}
    </div>
  );
});

/**
 * TickerBar -- always-visible bar at h-7 showing live index prices.
 * Reads from Jotai indicesSummaryAtom (populated by useWsBridge).
 * LTP numbers flash green on price increase and red on decrease (200ms).
 *
 * NSE/BSE indices are shown first, followed by a visual separator and
 * MCX commodity instruments (GOLD, SILVER, CRUDEOIL, NATGAS).
 * MCX instruments remain visible even when NSE/BSE is closed because
 * MCX trades until 23:30 IST on weekdays.
 */
export default function TickerBar() {
  const indices = useAtomValue(indicesSummaryAtom);
  const hasData = hasAnyLiveData(indices);
  const navigate = useNavigate();
  const mcxOpen = isMcxOpen();

  // Split indices into NSE/BSE section and MCX section
  const nseIndices = indices.filter((idx) => !MCX_NAMES.has(idx.name));
  const mcxIndices = indices.filter((idx) => MCX_NAMES.has(idx.name));

  return (
    <div
      className="h-7 bg-surface-base border-b border-border-default flex items-center overflow-x-auto shrink-0"
      role="region"
      aria-label="Market indices"
    >
      {/* NSE/BSE index section */}
      {nseIndices.map((idx) => (
        <IndexChip key={idx.name} name={idx.name} data={idx.data} />
      ))}

      {/* MCX separator + session badge */}
      {mcxIndices.length > 0 && (
        <div
          className="flex items-center gap-1.5 px-2 shrink-0 border-l border-r border-border-default h-full"
          aria-label="MCX commodities section"
        >
          <span
            className={`text-xxs font-mono uppercase tracking-wider px-1 py-0.5 rounded border ${
              mcxOpen
                ? "text-amber-400 border-amber-500/40 bg-amber-500/10"
                : "text-text-disabled border-border-default"
            }`}
            title={mcxOpen ? "MCX session is open (09:00–23:30 IST)" : "MCX session is closed"}
            aria-label={mcxOpen ? "MCX open" : "MCX closed"}
          >
            MCX
          </span>
        </div>
      )}

      {/* MCX commodity chips */}
      {mcxIndices.map((idx) => (
        <IndexChip key={idx.name} name={idx.name} data={idx.data} />
      ))}

      {!hasData && (
        <button
          onClick={() => navigate("/settings#brokers")}
          className="text-xxs text-text-muted hover:text-accent px-3 select-none transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none rounded"
        >
          Connect broker for live prices →
        </button>
      )}

      {/* Accessibility: one polite live region summarises all index prices for
          screen readers (Issue #50). Individual IndexChip spans stay aria-live="off"
          to prevent per-tick noise. aria-atomic ensures the whole summary is
          re-read together when any price updates. */}
      <span
        className="sr-only"
        aria-live="polite"
        aria-atomic="true"
      >
        {indices
          .filter((i) => i.data?.ltp != null && (i.data.ltp ?? 0) > 0)
          .map((i) => `${i.name} ${i.data!.ltp}`)
          .join(", ")}
      </span>
    </div>
  );
}
