/**
 * CorrelationMatrixWidget — Interactive correlation matrix for selected instruments.
 *
 * Features:
 *   - HTML table with colour-coded cells (diverging: -1 red → 0 neutral → +1 blue)
 *   - Add / remove instruments via symbol search input
 *   - Default instruments: NIFTY, BANKNIFTY, RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, GOLD
 *   - Hover tooltip showing exact coefficient and pair name
 *
 * DATA HONESTY: when a broker is connected, the widget fetches the live Pearson
 * correlation matrix from `/api/v1/analytics/correlation` (real `np.corrcoef`
 * over the backend's instrument set) and shows a "Live" badge — provided the
 * backend reports `is_sample_data: false`. Otherwise (disconnected, or the
 * backend itself falls back) it renders the deterministic `SAMPLE_MATRIX` +
 * `pseudoCorr` fallback with an amber "Sample data" badge so a trader is never
 * misled into reading sample coefficients as real market data. The live matrix
 * uses the backend's fixed instrument set, so the add/remove controls apply to
 * the sample (explore) matrix only and are disabled while live.
 */

import { useState, useMemo, useCallback, useRef, memo } from "react";
import { Grid2x2, Plus, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Input } from "@/components/ui/input";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getCorrelationMatrix } from "@/services/ftApi.analysis";
import type { CorrelationResponse } from "@/services/ftApi.analysis";

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
// Live matrix shaping
// ---------------------------------------------------------------------------

/** Convert the backend's symbols + 2-D matrix into the widget's nested map. */
function liveMatrixFrom(resp: CorrelationResponse): {
  symbols: string[];
  matrix: Record<string, Record<string, number>>;
} {
  const syms = resp.symbols ?? [];
  const m: Record<string, Record<string, number>> = {};
  syms.forEach((a, i) => {
    m[a] = {};
    syms.forEach((b, j) => {
      m[a][b] = resp.matrix?.[i]?.[j] ?? 0;
    });
  });
  return { symbols: syms, matrix: m };
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function CorrelationMatrixWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [symbols, setSymbols] = useState<string[]>(DEFAULT_SYMBOLS);
  const [searchInput, setSearchInput] = useState("");
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Live correlation matrix — only fetched once a broker is connected.
  const { data: liveResp } = useQuery({
    queryKey: ["correlation-matrix"],
    queryFn: () => getCorrelationMatrix(),
    enabled: isConnected,
    staleTime: 5 * 60_000,
    refetchInterval: isConnected ? 5 * 60_000 : false,
    retry: false,
  });

  // Live only when the backend reports genuinely-live data (not its own sample
  // fallback) and returns a usable matrix.
  const live = useMemo(
    () =>
      liveResp && liveResp.is_sample_data === false && (liveResp.matrix?.length ?? 0) > 0
        ? liveMatrixFrom(liveResp)
        : null,
    [liveResp],
  );
  const isLive = isConnected && live !== null;

  // Sample matrix (memoised) — the editable explore view.
  const sampleMatrix = useMemo(() => {
    const m: Record<string, Record<string, number>> = {};
    for (const a of symbols) {
      m[a] = {};
      for (const b of symbols) {
        m[a][b] = getCorr(symbols, a, b);
      }
    }
    return m;
  }, [symbols]);

  // What the table actually renders: backend set when live, editable set otherwise.
  const displaySymbols = isLive && live ? live.symbols : symbols;
  const matrix = isLive && live ? live.matrix : sampleMatrix;

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
        {/* Data-source badge — flips to "Live" only when a broker is connected
            AND the backend returns a genuinely-live matrix (is_sample_data
            false). Otherwise it stays on the honest amber "Sample data"
            affordance so a connected trader is never misled into reading the
            sample coefficients as real market data. */}
        {isLive ? (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-profit/10 text-profit border border-profit/30 rounded"
            role="status"
            aria-label="Showing the live correlation matrix from the connected broker"
            title="Live Pearson correlation matrix from /api/v1/analytics/correlation."
          >
            Live
          </span>
        ) : (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            role="status"
            aria-label="Showing sample data; no live correlation source is wired yet"
            title="No live data wired yet — showing a sample correlation matrix so the widget is usable in explore mode."
          >
            Sample data
          </span>
        )}
        <div className="flex-1" />
      </div>

      {/* Symbol add bar — editing applies to the sample (explore) matrix only;
          disabled while the live backend matrix (fixed instrument set) is shown. */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 border-b border-border-default bg-surface-base">
        <Input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value.toUpperCase())}
          onKeyDown={handleKeyDown}
          placeholder={isLive ? "Live matrix uses the broker instrument set" : "Add symbol (e.g. SBIN)"}
          className="flex-1 h-7 text-xs font-mono"
          maxLength={20}
          disabled={isLive}
          aria-label="Add instrument to correlation matrix"
        />
        <button
          onClick={addSymbol}
          disabled={isLive || !searchInput.trim() || symbols.length >= 12}
          aria-label="Add instrument"
          className="flex items-center gap-1 px-2 py-1 rounded bg-accent/10 text-accent border border-accent/30 text-xs hover:bg-accent/20 disabled:opacity-40 transition-colors"
        >
          <Plus size={11} aria-hidden="true" />
          Add
        </button>
      </div>

      {/* Active symbols chips */}
      <div className="flex-none flex flex-wrap gap-1 px-2 py-1.5 border-b border-border-default min-h-8">
        {displaySymbols.map((sym) => (
          <span
            key={sym}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xxs font-mono bg-surface-card border border-border-default text-text-secondary"
          >
            {sym}
            {!isLive && (
              <button
                onClick={() => removeSymbol(sym)}
                aria-label={`Remove ${sym} from matrix`}
                className="text-text-muted hover:text-loss transition-colors ml-0.5"
              >
                <X size={9} aria-hidden="true" />
              </button>
            )}
          </span>
        ))}
      </div>

      {/* Matrix table */}
      <div className="flex-1 min-h-0 overflow-auto">
        <table
          className="text-xxs border-collapse"
          aria-label="Correlation matrix table"
          style={{ minWidth: `${displaySymbols.length * 56 + 72}px` }}
        >
          <thead className="sticky top-0 z-10">
            <tr>
              <th className="bg-surface-card border border-border-default px-1 py-1.5 text-left w-16 font-medium text-text-muted">
                Symbol
              </th>
              {displaySymbols.map((sym) => (
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
            {displaySymbols.map((rowSym) => (
              <tr key={rowSym}>
                <td className="sticky left-0 bg-surface-card border border-border-default px-1 py-1.5 font-mono font-semibold text-text-primary whitespace-nowrap z-10">
                  {rowSym.length > 8 ? rowSym.slice(0, 8) : rowSym}
                </td>
                {displaySymbols.map((colSym) => {
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
          <span className="ml-auto text-text-muted">Pearson correlation of returns</span>
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
