/**
 * CorrelationMatrixWidget — Interactive correlation matrix for selected instruments.
 *
 * Features:
 *   - HTML table with colour-coded cells (diverging: -1 red → 0 neutral → +1 blue)
 *   - Add / remove instruments via symbol search input
 *   - Default instruments: NIFTY, BANKNIFTY, RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, GOLD
 *   - Hover tooltip showing exact coefficient and pair name
 *
 * DATA SOURCE: sample only. The matrix is computed from `SAMPLE_MATRIX` and a
 * deterministic `pseudoCorr` fallback — there is no live correlation endpoint
 * wired yet (a future `/ft-api/v1/correlation` route is planned). The "Sample
 * data" badge is therefore shown unconditionally so a connected (live) trader
 * is never misled into reading these coefficients as real market data.
 */

import { useState, useMemo, useCallback, useRef, memo } from "react";
import { Grid2x2, Plus, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Default symbols and sample correlation data
// ---------------------------------------------------------------------------

const DEFAULT_SYMBOLS = [
  "NIFTY",
  "BANKNIFTY",
  "RELIANCE",
  "TCS",
  "HDFCBANK",
  "INFY",
  "ICICIBANK",
  "GOLD",
];

// Pre-computed sample correlation matrix (symmetric, 8x8)
// Row/col order matches DEFAULT_SYMBOLS
const SAMPLE_MATRIX: Record<string, Record<string, number>> = {
  NIFTY:     { NIFTY: 1.00, BANKNIFTY: 0.94, RELIANCE: 0.76, TCS: 0.68, HDFCBANK: 0.81, INFY: 0.65, ICICIBANK: 0.79, GOLD: -0.21 },
  BANKNIFTY: { NIFTY: 0.94, BANKNIFTY: 1.00, RELIANCE: 0.71, TCS: 0.59, HDFCBANK: 0.89, INFY: 0.57, ICICIBANK: 0.91, GOLD: -0.18 },
  RELIANCE:  { NIFTY: 0.76, BANKNIFTY: 0.71, RELIANCE: 1.00, TCS: 0.52, HDFCBANK: 0.64, INFY: 0.48, ICICIBANK: 0.61, GOLD: -0.12 },
  TCS:       { NIFTY: 0.68, BANKNIFTY: 0.59, RELIANCE: 0.52, TCS: 1.00, HDFCBANK: 0.55, INFY: 0.72, ICICIBANK: 0.53, GOLD: -0.09 },
  HDFCBANK:  { NIFTY: 0.81, BANKNIFTY: 0.89, RELIANCE: 0.64, TCS: 0.55, HDFCBANK: 1.00, INFY: 0.51, ICICIBANK: 0.87, GOLD: -0.16 },
  INFY:      { NIFTY: 0.65, BANKNIFTY: 0.57, RELIANCE: 0.48, TCS: 0.72, HDFCBANK: 0.51, INFY: 1.00, ICICIBANK: 0.49, GOLD: -0.07 },
  ICICIBANK: { NIFTY: 0.79, BANKNIFTY: 0.91, RELIANCE: 0.61, TCS: 0.53, HDFCBANK: 0.87, INFY: 0.49, ICICIBANK: 1.00, GOLD: -0.14 },
  GOLD:      { NIFTY: -0.21, BANKNIFTY: -0.18, RELIANCE: -0.12, TCS: -0.09, HDFCBANK: -0.16, INFY: -0.07, ICICIBANK: -0.14, GOLD: 1.00 },
};

// Generate a plausible correlation for unknown symbol pairs
function pseudoCorr(a: string, b: string): number {
  if (a === b) return 1.0;
  // Deterministic but varied — based on char codes
  const seed =
    (a.charCodeAt(0) * 31 + b.charCodeAt(0) * 17) % 100;
  return parseFloat(((seed / 100) * 1.6 - 0.6).toFixed(2));
}

function getCorr(symbols: string[], a: string, b: string): number {
  void symbols;
  if (SAMPLE_MATRIX[a]?.[b] !== undefined) return SAMPLE_MATRIX[a][b];
  if (SAMPLE_MATRIX[b]?.[a] !== undefined) return SAMPLE_MATRIX[b][a];
  return pseudoCorr(a, b);
}

// ---------------------------------------------------------------------------
// Colour mapping: -1 red → 0 neutral (#16161f) → +1 blue
// ---------------------------------------------------------------------------

function corrToColour(v: number): string {
  if (v >= 0.99) return "bg-accent/30 text-accent font-bold";
  if (v >= 0.8)  return "bg-blue-500/30 text-blue-300";
  if (v >= 0.6)  return "bg-blue-500/20 text-blue-400";
  if (v >= 0.4)  return "bg-blue-500/10 text-blue-500";
  if (v >= 0.2)  return "bg-surface-hover text-text-secondary";
  if (v >= -0.2) return "bg-surface-base text-text-muted";
  if (v >= -0.4) return "bg-loss/10 text-orange-400";
  if (v >= -0.6) return "bg-loss/20 text-loss";
  return "bg-loss/30 text-red-400";
}

// ---------------------------------------------------------------------------
// Tooltip state
// ---------------------------------------------------------------------------

interface TooltipState {
  x: number;
  y: number;
  label: string;
  value: number;
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function CorrelationMatrixWidget() {
  // NOTE: We deliberately do NOT read `useBrokerConnected()` here. There is no
  // live correlation endpoint, so the data is sample-only regardless of broker
  // connection — gating anything on connection state would only let the UI
  // pretend the figures are live. The "Sample data" badge stays visible always.
  const track = useTrackBehavior();

  const [symbols, setSymbols] = useState<string[]>(DEFAULT_SYMBOLS);
  const [searchInput, setSearchInput] = useState("");
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Correlation matrix (memoised)
  const matrix = useMemo(() => {
    const m: Record<string, Record<string, number>> = {};
    for (const a of symbols) {
      m[a] = {};
      for (const b of symbols) {
        m[a][b] = getCorr(symbols, a, b);
      }
    }
    return m;
  }, [symbols]);

  const addSymbol = useCallback(() => {
    const sym = searchInput.trim().toUpperCase();
    if (!sym || symbols.includes(sym) || symbols.length >= 12) return;
    setSymbols((prev) => [...prev, sym]);
    setSearchInput("");
    track("trade", "correlation_matrix_add_symbol");
  }, [searchInput, symbols, track]);

  const removeSymbol = useCallback(
    (sym: string) => {
      setSymbols((prev) => prev.filter((s) => s !== sym));
      track("trade", "correlation_matrix_remove_symbol");
    },
    [track]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") addSymbol();
  };

  const handleCellEnter = (
    e: React.MouseEvent<HTMLTableCellElement>,
    a: string,
    b: string,
    v: number
  ) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltip({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      label: a === b ? a : `${a} / ${b}`,
      value: v,
    });
  };

  const handleCellLeave = () => setTooltip(null);

  return (
    <div
      ref={containerRef}
      className="h-full flex flex-col bg-surface-base overflow-hidden relative"
      aria-label="Correlation Matrix widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Grid2x2 size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Correlation Matrix</span>
        {/* Honest disclosure — the matrix is computed from `SAMPLE_MATRIX` and
            the `pseudoCorr` fallback; no live correlation endpoint is wired yet.
            The badge previously hid in `isConnected` mode, which masked the fact
            that a connected trader was still reading sample coefficients. Keep
            visible at all times. */}
        <span
          className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
          role="status"
          aria-label="Showing sample data; no live correlation source is wired yet"
          title="No live data wired yet — showing a sample correlation matrix so the widget is usable in explore mode."
        >
          Sample data
        </span>
        <div className="flex-1" />
      </div>

      {/* Symbol add bar */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 border-b border-border-default bg-surface-base">
        <Input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value.toUpperCase())}
          onKeyDown={handleKeyDown}
          placeholder="Add symbol (e.g. SBIN)"
          className="flex-1 h-7 text-xs font-mono"
          maxLength={20}
          aria-label="Add instrument to correlation matrix"
        />
        <button
          onClick={addSymbol}
          disabled={!searchInput.trim() || symbols.length >= 12}
          aria-label="Add instrument"
          className="flex items-center gap-1 px-2 py-1 rounded bg-accent/10 text-accent border border-accent/30 text-xs hover:bg-accent/20 disabled:opacity-40 transition-colors"
        >
          <Plus size={11} aria-hidden="true" />
          Add
        </button>
      </div>

      {/* Active symbols chips */}
      <div className="flex-none flex flex-wrap gap-1 px-2 py-1.5 border-b border-border-default min-h-8">
        {symbols.map((sym) => (
          <span
            key={sym}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xxs font-mono bg-surface-card border border-border-default text-text-secondary"
          >
            {sym}
            <button
              onClick={() => removeSymbol(sym)}
              aria-label={`Remove ${sym} from matrix`}
              className="text-text-muted hover:text-loss transition-colors ml-0.5"
            >
              <X size={9} aria-hidden="true" />
            </button>
          </span>
        ))}
      </div>

      {/* Matrix table */}
      <div className="flex-1 min-h-0 overflow-auto">
        <table
          className="text-xxs border-collapse"
          aria-label="Correlation matrix table"
          style={{ minWidth: `${symbols.length * 56 + 72}px` }}
        >
          <thead className="sticky top-0 z-10">
            <tr>
              <th className="bg-surface-card border border-border-default px-1 py-1.5 text-left w-16 font-medium text-text-muted">
                Symbol
              </th>
              {symbols.map((sym) => (
                <th
                  key={sym}
                  className="bg-surface-card border border-border-default px-1 py-1.5 text-center font-medium text-text-muted whitespace-nowrap w-14"
                >
                  {sym.length > 7 ? sym.slice(0, 7) : sym}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {symbols.map((rowSym) => (
              <tr key={rowSym}>
                <td className="sticky left-0 bg-surface-card border border-border-default px-1 py-1.5 font-mono font-semibold text-text-primary whitespace-nowrap z-10">
                  {rowSym.length > 8 ? rowSym.slice(0, 8) : rowSym}
                </td>
                {symbols.map((colSym) => {
                  const v = matrix[rowSym]?.[colSym] ?? 0;
                  const colourClass = corrToColour(v);
                  return (
                    <td
                      key={colSym}
                      className={`border border-border-default px-1 py-1.5 text-center font-mono tabular-nums cursor-default transition-opacity hover:opacity-80 ${colourClass}`}
                      onMouseEnter={(e) => handleCellEnter(e, rowSym, colSym, v)}
                      onMouseLeave={handleCellLeave}
                      aria-label={`${rowSym} and ${colSym} correlation ${v.toFixed(2)}`}
                    >
                      {v.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Scale legend */}
      <div className="flex-none px-2 py-1.5 border-t border-border-default">
        <div className="flex items-center gap-1 text-xxs">
          <span className="text-text-muted mr-1">Scale:</span>
          <span className="px-1 bg-loss/30 text-red-400 rounded">−1.0</span>
          <span className="px-1 bg-loss/20 text-loss rounded">−0.5</span>
          <span className="px-1 bg-surface-base text-text-muted rounded">0</span>
          <span className="px-1 bg-blue-500/20 text-blue-400 rounded">+0.5</span>
          <span className="px-1 bg-blue-500/30 text-blue-300 rounded">+1.0</span>
          <span className="ml-auto text-text-muted">20-day rolling returns</span>
        </div>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-50 px-2 py-1.5 bg-surface-card border border-border-default rounded shadow-lg text-xxs"
          style={{ left: tooltip.x + 12, top: tooltip.y - 28 }}
          aria-live="polite"
        >
          <span className="font-semibold text-text-primary">{tooltip.label}</span>
          <span className="text-text-muted ml-2">r = </span>
          <span
            className={`font-mono font-bold ${
              tooltip.value >= 0.5
                ? "text-blue-400"
                : tooltip.value <= -0.5
                ? "text-loss"
                : "text-text-secondary"
            }`}
          >
            {tooltip.value.toFixed(3)}
          </span>
        </div>
      )}
    </div>
  );
}

export default memo(CorrelationMatrixWidget);
