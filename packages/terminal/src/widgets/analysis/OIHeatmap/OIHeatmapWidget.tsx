/**
 * OIHeatmapWidget — Open Interest heatmap across strike prices.
 *
 * Visual layout:
 *   Row 1 (CE): strike cells coloured by CE OI intensity (accent palette)
 *   Row 2 (PE): strike cells coloured by PE OI intensity (loss palette)
 *
 * Features:
 *   - 20 strikes around ATM (STRIKES_AROUND_ATM = 10 each side)
 *   - Colour intensity: low OI → dim, high OI → saturated
 *   - OI change arrows: up/down overlay on each cell
 *   - ATM strike highlighted with accent border
 *   - Max OI strikes marked (support / resistance)
 *   - Symbol + expiry selectors in header
 *   - Hover tooltip: exact OI, volume, OI change, PCR for that strike
 *   - Colour legend at bottom
 *   - Auto-refresh: 3 s market hours, 30 s otherwise
 *   - FeatureTeaser with sample data when broker is disconnected
 *
 * Data source: getOptionChain() + getExpiry() from @/services/api
 */

import { useState, useEffect, useCallback, useMemo, useRef, memo } from "react";
import { RefreshCw, AlertCircle, Loader2, TrendingUp, TrendingDown } from "lucide-react";
import { getOptionChain, getExpiry } from "@/services/api";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { FeatureTeaser } from "@/components/teasers";
import { isMarketHours } from "@/lib/market";
import type {
  RawOptionChain,
  RawOptionRow,
  ChainEntry,
} from "@/widgets/analysis/OptionChain/types";
import { SYMBOLS } from "@/widgets/analysis/OptionChain/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STRIKES_EACH_SIDE = 10; // 10 left + 10 right = 20 strikes total

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtOI(v: number): string {
  if (v >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(1)}Cr`;
  if (v >= 1_00_000) return `${(v / 1_00_000).toFixed(1)}L`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

/** Map a 0–1 intensity to an RGBA string for CE (indigo/accent) cells. */
function ceColour(intensity: number): string {
  // From surface-hover (dim) to accent-blue
  const r = Math.round(22 + (99 - 22) * intensity);   // 22 → 99
  const g = Math.round(22 + (102 - 22) * intensity);   // 22 → 102
  const b = Math.round(31 + (241 - 31) * intensity);   // 31 → 241
  const a = 0.15 + 0.8 * intensity;
  return `rgba(${r},${g},${b},${a})`;
}

/** Map a 0–1 intensity to an RGBA string for PE (red/loss) cells. */
function peColour(intensity: number): string {
  const r = Math.round(22 + (239 - 22) * intensity);   // 22 → 239
  const g = Math.round(22 + (68  - 22) * intensity);   // 22 → 68
  const b = Math.round(31 + (68  - 31) * intensity);   // 31 → 68
  const a = 0.15 + 0.8 * intensity;
  return `rgba(${r},${g},${b},${a})`;
}

// ---------------------------------------------------------------------------
// Sample data (used when broker is disconnected)
// ---------------------------------------------------------------------------

function buildSampleChain(baseStrike: number, step: number, count: number): SampleStrike[] {
  return Array.from({ length: count }, (_, i) => {
    const strike = baseStrike - Math.floor(count / 2) * step + i * step;
    const distFromATM = Math.abs(i - Math.floor(count / 2));
    const ceOi = Math.round((500_000 - distFromATM * 30_000) * (0.8 + Math.random() * 0.4));
    const peOi = Math.round((480_000 - distFromATM * 25_000) * (0.8 + Math.random() * 0.4));
    return {
      strike,
      ceOi: Math.max(10_000, ceOi),
      peOi: Math.max(10_000, peOi),
      ceOiChange: Math.round((Math.random() - 0.5) * 40_000),
      peOiChange: Math.round((Math.random() - 0.5) * 35_000),
      ceVolume: Math.round(ceOi * 0.3 * Math.random()),
      peVolume: Math.round(peOi * 0.3 * Math.random()),
    };
  });
}

interface SampleStrike {
  strike: number;
  ceOi: number;
  peOi: number;
  ceOiChange: number;
  peOiChange: number;
  ceVolume: number;
  peVolume: number;
}

const SAMPLE_ATM = 24_750;
const SAMPLE_STRIKES: SampleStrike[] = buildSampleChain(SAMPLE_ATM, 50, 21);

// ---------------------------------------------------------------------------
// Strike cell data shape (normalised from raw chain)
// ---------------------------------------------------------------------------

interface StrikeCell {
  strike: number;
  ceOi: number;
  peOi: number;
  ceOiChange: number;
  peOiChange: number;
  ceVolume: number;
  peVolume: number;
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  strike: number;
  optionType: "CE" | "PE";
  oi: number;
  oiChange: number;
  volume: number;
  pcr: number | null;
}

// ---------------------------------------------------------------------------
// Single heatmap cell
// ---------------------------------------------------------------------------

interface CellProps {
  colour: string;
  oi: number;
  oiChange: number;
  isATM: boolean;
  isMaxOI: boolean;
  onMouseEnter: (e: React.MouseEvent<HTMLDivElement>) => void;
  onMouseLeave: () => void;
}

function HeatmapCell({
  colour,
  oi,
  oiChange,
  isATM,
  isMaxOI,
  onMouseEnter,
  onMouseLeave,
}: CellProps) {
  return (
    <div
      className={`relative flex flex-col items-center justify-center h-full cursor-default select-none transition-opacity hover:opacity-90 ${
        isATM ? "ring-1 ring-inset ring-accent/70" : ""
      } ${isMaxOI ? "ring-1 ring-inset ring-warning/60" : ""}`}
      style={{ backgroundColor: colour }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <span className="text-xxs font-mono text-text-primary/90 leading-none tabular-nums">
        {fmtOI(oi)}
      </span>
      {oiChange !== 0 && (
        <span className={`mt-0.5 ${oiChange > 0 ? "text-profit" : "text-loss"}`}>
          {oiChange > 0 ? <TrendingUp size={8} /> : <TrendingDown size={8} />}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Colour legend strip
// ---------------------------------------------------------------------------

function ColourLegend() {
  const ceStops = Array.from({ length: 5 }, (_, i) => i / 4);
  const peStops = Array.from({ length: 5 }, (_, i) => i / 4);

  return (
    <div className="flex items-center gap-4 px-3 py-1.5 border-t border-border-default text-xs text-text-muted flex-wrap">
      <div className="flex items-center gap-1.5">
        <span className="uppercase tracking-wide text-xxs">CE</span>
        <div className="flex h-3 rounded overflow-hidden" style={{ width: 80 }}>
          {ceStops.map((v, i) => (
            <div key={i} className="flex-1" style={{ backgroundColor: ceColour(v) }} />
          ))}
        </div>
        <span className="text-xxs">Low → High</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="uppercase tracking-wide text-xxs">PE</span>
        <div className="flex h-3 rounded overflow-hidden" style={{ width: 80 }}>
          {peStops.map((v, i) => (
            <div key={i} className="flex-1" style={{ backgroundColor: peColour(v) }} />
          ))}
        </div>
        <span className="text-xxs">Low → High</span>
      </div>
      <div className="flex items-center gap-2 ml-auto text-xxs">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 ring-1 ring-accent/70 rounded-sm" />
          ATM
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 ring-1 ring-warning/60 rounded-sm" />
          Max OI
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function OIHeatmapWidget() {
  const [symbolIdx, setSymbolIdx] = useState(0);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rawChain, setRawChain] = useState<RawOptionChain | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false, x: 0, y: 0, strike: 0, optionType: "CE",
    oi: 0, oiChange: 0, volume: 0, pcr: null,
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const isConnected = useBrokerConnected();
  const symDef = SYMBOLS[symbolIdx];

  // ---------------------------------------------------------------------------
  // Fetch expiries when symbol changes
  // ---------------------------------------------------------------------------

  useEffect(() => {
    setExpiries([]);
    setSelectedExpiry("");
    setRawChain(null);
    setError(null);
    if (!isConnected) return;

    let cancelled = false;
    (async () => {
      try {
        const result = await getExpiry(symDef.label, symDef.exchange);
        if (cancelled) return;
        const list = Array.isArray(result)
          ? (result as string[])
          : ((result as { expiry?: string[] })?.expiry ?? []);
        setExpiries(list);
        if (list.length > 0) setSelectedExpiry(list[0]);
      } catch (e) {
        if (!cancelled) setError(`Expiry fetch failed: ${(e as Error).message}`);
      }
    })();
    return () => { cancelled = true; };
  }, [symDef.label, symDef.exchange, isConnected]);

  // ---------------------------------------------------------------------------
  // Fetch chain data
  // ---------------------------------------------------------------------------

  const fetchChain = useCallback(async () => {
    if (!isConnected || !selectedExpiry) return;
    setFetching(true);
    setError(null);
    try {
      const chain = await getOptionChain(symDef.label, symDef.exchange, selectedExpiry);
      setRawChain(chain as unknown as RawOptionChain);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setFetching(false);
      setLoading(false);
    }
  }, [isConnected, selectedExpiry, symDef.label, symDef.exchange]);

  // Auto-refresh
  useEffect(() => {
    if (!isConnected || !selectedExpiry) return;
    setLoading(true);
    void fetchChain();
    const interval = isMarketHours() ? 3_000 : 30_000;
    const id = setInterval(() => void fetchChain(), interval);
    return () => clearInterval(id);
  }, [fetchChain, isConnected, selectedExpiry]);

  // ---------------------------------------------------------------------------
  // Normalise raw chain → StrikeCell[] with ATM slicing
  // ---------------------------------------------------------------------------

  const { strikes, atmStrike, maxCeOI, maxPeOI, pcr } = useMemo<{
    strikes: StrikeCell[];
    atmStrike: number | null;
    maxCeOI: number;
    maxPeOI: number;
    pcr: number | null;
  }>(() => {
    if (!rawChain) {
      return { strikes: [], atmStrike: null, maxCeOI: 0, maxPeOI: 0, pcr: null };
    }

    const callMap: Record<number, RawOptionRow> = {};
    const putMap:  Record<number, RawOptionRow> = {};

    if (rawChain.chain && rawChain.chain.length > 0) {
      for (const entry of rawChain.chain as ChainEntry[]) {
        if (entry.ce) callMap[entry.strike] = entry.ce;
        if (entry.pe) putMap[entry.strike]  = entry.pe;
      }
    } else {
      (rawChain.calls ?? []).forEach((c) => {
        const k = c.strike_price ?? c.strike ?? 0;
        callMap[k] = c;
      });
      (rawChain.puts ?? []).forEach((p) => {
        const k = p.strike_price ?? p.strike ?? 0;
        putMap[k] = p;
      });
    }

    const allStrikes = Array.from(
      new Set([...Object.keys(callMap), ...Object.keys(putMap)].map(Number))
    ).sort((a, b) => a - b);

    if (allStrikes.length === 0) {
      return { strikes: [], atmStrike: null, maxCeOI: 0, maxPeOI: 0, pcr: null };
    }

    const atm = rawChain.atm_strike ?? allStrikes[Math.floor(allStrikes.length / 2)];
    const atmIdx = allStrikes.indexOf(atm);
    const lo = Math.max(0, atmIdx - STRIKES_EACH_SIDE);
    const hi = Math.min(allStrikes.length - 1, atmIdx + STRIKES_EACH_SIDE);
    const visible = allStrikes.slice(lo, hi + 1);

    const cells: StrikeCell[] = visible.map((s) => {
      const ce = callMap[s];
      const pe = putMap[s];
      return {
        strike: s,
        ceOi:       Number(ce?.oi ?? ce?.open_interest ?? 0),
        ceOiChange: Number(ce?.oi_change ?? 0),
        ceVolume:   0, // OpenAlgo OI chain may not always carry volume per strike
        peOi:       Number(pe?.oi ?? pe?.open_interest ?? 0),
        peOiChange: Number(pe?.oi_change ?? 0),
        peVolume:   0,
      };
    });

    const maxCeOI = Math.max(1, ...cells.map((c) => c.ceOi));
    const maxPeOI = Math.max(1, ...cells.map((c) => c.peOi));

    const totalCe = cells.reduce((s, c) => s + c.ceOi, 0);
    const totalPe = cells.reduce((s, c) => s + c.peOi, 0);
    const pcr = totalCe > 0 ? totalPe / totalCe : null;

    return { strikes: cells, atmStrike: atm, maxCeOI, maxPeOI, pcr };
  }, [rawChain]);

  // ---------------------------------------------------------------------------
  // Sample data (disconnected mode)
  // ---------------------------------------------------------------------------

  const { sampleStrikes, sampleMaxCe, sampleMaxPe, sampleATM } = useMemo(() => {
    const maxCe = Math.max(1, ...SAMPLE_STRIKES.map((s) => s.ceOi));
    const maxPe = Math.max(1, ...SAMPLE_STRIKES.map((s) => s.peOi));
    return { sampleStrikes: SAMPLE_STRIKES, sampleMaxCe: maxCe, sampleMaxPe: maxPe, sampleATM: SAMPLE_ATM };
  }, []);

  // Active data set (live or sample)
  const activeStrikes = isConnected ? strikes : sampleStrikes.map((s) => ({
    strike: s.strike, ceOi: s.ceOi, peOi: s.peOi,
    ceOiChange: s.ceOiChange, peOiChange: s.peOiChange,
    ceVolume: s.ceVolume, peVolume: s.peVolume,
  } satisfies StrikeCell));
  const activeMaxCe  = isConnected ? maxCeOI  : sampleMaxCe;
  const activeMaxPe  = isConnected ? maxPeOI  : sampleMaxPe;
  const activeATM    = isConnected ? atmStrike : sampleATM;

  // Max OI strikes
  const maxCeStrike = activeStrikes.reduce(
    (best, s) => (s.ceOi > best.ceOi ? s : best),
    activeStrikes[0] ?? { strike: 0, ceOi: 0 } as StrikeCell,
  ).strike;
  const maxPeStrike = activeStrikes.reduce(
    (best, s) => (s.peOi > best.peOi ? s : best),
    activeStrikes[0] ?? { strike: 0, peOi: 0 } as StrikeCell,
  ).strike;

  // ---------------------------------------------------------------------------
  // Tooltip handlers
  // ---------------------------------------------------------------------------

  const handleCellEnter = useCallback(
    (e: React.MouseEvent<HTMLDivElement>, cell: StrikeCell, type: "CE" | "PE") => {
      const rect = containerRef.current?.getBoundingClientRect();
      const oi = type === "CE" ? cell.ceOi : cell.peOi;
      const oiChange = type === "CE" ? cell.ceOiChange : cell.peOiChange;
      const volume = type === "CE" ? cell.ceVolume : cell.peVolume;
      const totalCe = activeStrikes.reduce((s, c) => s + c.ceOi, 0);
      const totalPe = activeStrikes.reduce((s, c) => s + c.peOi, 0);
      const strikePcr = cell.ceOi > 0 ? cell.peOi / cell.ceOi : null;
      setTooltip({
        visible: true,
        x: rect ? e.clientX - rect.left : e.clientX,
        y: rect ? e.clientY - rect.top : e.clientY,
        strike: cell.strike,
        optionType: type,
        oi,
        oiChange,
        volume,
        pcr: strikePcr,
      });
      void totalCe; void totalPe;
    },
    [activeStrikes],
  );

  const handleCellLeave = useCallback(() => {
    setTooltip((t) => ({ ...t, visible: false }));
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const heatmapGrid = (
    <div ref={containerRef} className="relative flex-1 min-h-0 flex flex-col overflow-auto px-2 py-1.5 gap-1">
      {/* Row labels + CE row */}
      <div className="flex gap-px" style={{ minHeight: 52 }}>
        {/* Label column */}
        <div className="flex-none w-7 flex items-center justify-center">
          <span className="text-xxs text-text-muted rotate-180 writing-mode-vertical font-mono uppercase tracking-wider"
            style={{ writingMode: "vertical-rl" }}>CE</span>
        </div>
        {/* Cells */}
        {activeStrikes.map((cell) => {
          const intensity = activeMaxCe > 0 ? cell.ceOi / activeMaxCe : 0;
          return (
            <div key={`ce-${cell.strike}`} className="flex-1 min-w-0" style={{ minWidth: 32, height: 52 }}>
              <HeatmapCell
                colour={ceColour(intensity)}
                oi={cell.ceOi}
                oiChange={cell.ceOiChange}
                isATM={cell.strike === activeATM}
                isMaxOI={cell.strike === maxCeStrike}
                onMouseEnter={(e) => handleCellEnter(e, cell, "CE")}
                onMouseLeave={handleCellLeave}
              />
            </div>
          );
        })}
      </div>

      {/* Strike labels */}
      <div className="flex gap-px">
        <div className="flex-none w-7" />
        {activeStrikes.map((cell) => (
          <div key={`lbl-${cell.strike}`} className="flex-1 min-w-0 flex items-center justify-center" style={{ minWidth: 32 }}>
            <span className={`text-xxs font-mono tabular-nums leading-none ${
              cell.strike === activeATM
                ? "text-accent font-semibold"
                : "text-text-muted"
            }`}>
              {cell.strike}
            </span>
          </div>
        ))}
      </div>

      {/* PE row */}
      <div className="flex gap-px" style={{ minHeight: 52 }}>
        <div className="flex-none w-7 flex items-center justify-center">
          <span className="text-xxs text-text-muted rotate-180 font-mono uppercase tracking-wider"
            style={{ writingMode: "vertical-rl" }}>PE</span>
        </div>
        {activeStrikes.map((cell) => {
          const intensity = activeMaxPe > 0 ? cell.peOi / activeMaxPe : 0;
          return (
            <div key={`pe-${cell.strike}`} className="flex-1 min-w-0" style={{ minWidth: 32, height: 52 }}>
              <HeatmapCell
                colour={peColour(intensity)}
                oi={cell.peOi}
                oiChange={cell.peOiChange}
                isATM={cell.strike === activeATM}
                isMaxOI={cell.strike === maxPeStrike}
                onMouseEnter={(e) => handleCellEnter(e, cell, "PE")}
                onMouseLeave={handleCellLeave}
              />
            </div>
          );
        })}
      </div>

      {/* Tooltip */}
      {tooltip.visible && (
        <div
          className="absolute z-50 pointer-events-none bg-surface-card border border-border-default rounded-md shadow-lg p-2 text-xs min-w-[120px]"
          style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}
          data-testid="oi-tooltip"
        >
          <div className="font-semibold text-text-primary mb-1">
            {tooltip.strike} {tooltip.optionType}
          </div>
          <div className="flex flex-col gap-0.5 text-xxs">
            <div className="flex justify-between gap-3">
              <span className="text-text-muted">OI</span>
              <span className="font-mono tabular-nums text-text-primary">{fmtOI(tooltip.oi)}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-text-muted">OI Chg</span>
              <span className={`font-mono tabular-nums ${tooltip.oiChange >= 0 ? "text-profit" : "text-loss"}`}>
                {tooltip.oiChange >= 0 ? "+" : ""}{fmtOI(Math.abs(tooltip.oiChange))}
              </span>
            </div>
            {tooltip.pcr !== null && (
              <div className="flex justify-between gap-3">
                <span className="text-text-muted">PCR</span>
                <span className="font-mono tabular-nums text-text-primary">{tooltip.pcr.toFixed(2)}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" data-testid="oiheatmap-widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        <select
          value={symbolIdx}
          onChange={(e) => setSymbolIdx(Number(e.target.value))}
          className="px-2 py-1 text-xs bg-surface-hover border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/50"
          data-testid="symbol-select"
        >
          {SYMBOLS.map((s, i) => (
            <option key={s.label} value={i}>{s.label}</option>
          ))}
        </select>

        {isConnected && expiries.length > 0 && (
          <select
            value={selectedExpiry}
            onChange={(e) => setSelectedExpiry(e.target.value)}
            className="px-2 py-1 text-xs bg-surface-hover border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/50"
            data-testid="expiry-select"
          >
            {expiries.map((ex) => (
              <option key={ex} value={ex}>{ex}</option>
            ))}
          </select>
        )}

        <div className="flex-1" />

        {/* PCR badge */}
        {isConnected && pcr !== null && (
          <span className={`px-1.5 py-0.5 text-xxs font-mono tabular-nums rounded border ${
            pcr >= 1.2
              ? "text-profit bg-profit/10 border-profit/30"
              : pcr <= 0.8
                ? "text-loss bg-loss/10 border-loss/30"
                : "text-warning bg-warning/10 border-warning/30"
          }`}>
            PCR {pcr.toFixed(2)}
          </span>
        )}

        <button
          onClick={() => void fetchChain()}
          disabled={fetching || !isConnected}
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
          title="Refresh"
          data-testid="refresh-btn"
        >
          <RefreshCw size={11} className={fetching ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{error}</span>
        </div>
      )}

      {/* Loading full-screen */}
      {isConnected && loading && activeStrikes.length === 0 && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={16} className="animate-spin" />
          Loading OI data...
        </div>
      )}

      {/* Empty state (connected but no chain loaded yet) */}
      {isConnected && !loading && activeStrikes.length === 0 && !error && (
        <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
          Select symbol and expiry to view OI heatmap
        </div>
      )}

      {/* Heatmap */}
      {activeStrikes.length > 0 && (
        isConnected ? (
          <>{heatmapGrid}<ColourLegend /></>
        ) : (
          <FeatureTeaser status="in_dev" featureName="OI Heatmap" version="v0.3.0">
            {heatmapGrid}
            <ColourLegend />
          </FeatureTeaser>
        )
      )}
    </div>
  );
}

export default memo(OIHeatmapWidget);
