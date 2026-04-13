/**
 * PositionHeatMapWidget
 *
 * Visualises portfolio exposure across sectors and instruments as a treemap.
 * Each rectangle is sized by position value (quantity × LTP) and coloured
 * by P&L% — green gradient for profit, red for loss.
 *
 * Treemap algorithm: squarified treemap (inline, no external library).
 * Layout algorithm absorbed from SectorMapWidget / treemapLayout.ts pattern.
 *
 * Data sources:
 *   - Positions: usePositions() TanStack Query hook
 *   - LTP: position.ltp (from REST) or Jotai market atom fallback
 *   - Explore mode: inline sample data
 *
 * Interactions:
 *   - Hover: tooltip with qty, entry price, LTP, P&L, P&L%
 *   - Click: dispatch flinttrade:navigate to open symbol in ChartWidget
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  memo,
} from "react";
import type { MouseEvent } from "react";
import { SquareStack } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useModeStore } from "@/stores/modeStore";
import { usePositions } from "@/hooks/usePositions";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { divergingColourScaleRange } from "@/lib/colourScale";
import type { Position } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Squarified treemap layout (inline — no external library)
// Adapted from SectorMapWidget pattern, originally absorbed from
// openalgo-chart/src/components/SectorHeatmap/utils/treemapLayout.ts
// ---------------------------------------------------------------------------

interface TreeNode {
  value: number;
}

function squarifiedTreemap<T extends TreeNode>(
  nodes: T[],
  x: number,
  y: number,
  width: number,
  height: number,
): (T & { x: number; y: number; width: number; height: number })[] {
  type Out = T & { x: number; y: number; width: number; height: number };

  if (nodes.length === 0 || width <= 0 || height <= 0) return [];

  const total = nodes.reduce((s, n) => s + n.value, 0);
  if (total <= 0) return [];

  const result: Out[] = [];
  let remaining = [...nodes];
  let cx = x, cy = y, cw = width, ch = height;
  let remainingTotal = total;

  while (remaining.length > 0) {
    const horizontal = cw >= ch;
    const mainSide = horizontal ? ch : cw;
    let row = [remaining[0]];
    let rowVal = remaining[0].value;
    let worstRatio = Infinity;

    for (let i = 1; i < remaining.length; i++) {
      const candidate = [...row, remaining[i]];
      const candidateVal = rowVal + remaining[i].value;
      const thickness = (candidateVal / remainingTotal) * (horizontal ? cw : ch);
      let worst = 0;
      candidate.forEach((n) => {
        const len = (n.value / candidateVal) * mainSide;
        worst = Math.max(worst, Math.max(thickness / len, len / thickness));
      });
      if (worst <= worstRatio) {
        row = candidate;
        rowVal = candidateVal;
        worstRatio = worst;
      } else {
        break;
      }
    }

    const rowFraction = rowVal / remainingTotal;
    const rowSize = horizontal ? rowFraction * cw : rowFraction * ch;
    let offset = 0;

    row.forEach((n) => {
      const itemFraction = n.value / rowVal;
      const itemSize = itemFraction * mainSide;
      if (horizontal) {
        result.push({ ...n, x: cx, y: cy + offset, width: rowSize, height: itemSize });
      } else {
        result.push({ ...n, x: cx + offset, y: cy, width: itemSize, height: rowSize });
      }
      offset += itemSize;
    });

    remainingTotal -= rowVal;
    remaining = remaining.slice(row.length);
    if (horizontal) {
      cx += rowSize;
      cw -= rowSize;
    } else {
      cy += rowSize;
      ch -= rowSize;
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Sector mapping — same static map as SectorMapWidget for consistency
// ---------------------------------------------------------------------------

const SECTOR_MAP: Record<string, string> = {
  RELIANCE: "Energy", ONGC: "Energy", IOC: "Energy", BPCL: "Energy",
  TCS: "IT", INFY: "IT", WIPRO: "IT", HCLTECH: "IT", TECHM: "IT",
  HDFCBANK: "Banking", ICICIBANK: "Banking", SBIN: "Banking", KOTAKBANK: "Banking", AXISBANK: "Banking",
  HINDUNILVR: "FMCG", ITC: "FMCG", NESTLEIND: "FMCG", BRITANNIA: "FMCG",
  MARUTI: "Auto", TATAMOTORS: "Auto", M_M: "Auto", BAJAJ_AUTO: "Auto",
  SUNPHARMA: "Pharma", DRREDDY: "Pharma", CIPLA: "Pharma", DIVISLAB: "Pharma",
  LT: "Infra", POWERGRID: "Infra", NTPC: "Infra",
  BAJFINANCE: "NBFC", BAJAJFINSV: "NBFC", HDFCLIFE: "NBFC",
  TITAN: "Consumer", ASIANPAINT: "Consumer", ADANIPORTS: "Logistics",
};

function getSector(symbol: string): string {
  // Strip expiry/strike suffixes for F&O symbols — take root
  const root = symbol.replace(/\d{2}[A-Z]{3}\d{2}.*$/i, "").replace(/[-&.]/g, "_").toUpperCase();
  return SECTOR_MAP[root] ?? "Others";
}

// ---------------------------------------------------------------------------
// Explore-mode sample data (no broker connection required)
// ---------------------------------------------------------------------------

const EXPLORE_POSITIONS: Position[] = [
  { symbol: "NIFTY24APR22500CE", exchange: "NFO", product: "MIS", quantity: 75, averagePrice: 180, ltp: 235, pnl: 4125, pnlPercent: 30.6 },
  { symbol: "BANKNIFTY24APR49000PE", exchange: "NFO", product: "MIS", quantity: -30, averagePrice: 290, ltp: 210, pnl: 2400, pnlPercent: 27.6 },
  { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
  { symbol: "TCS", exchange: "NSE", product: "CNC", quantity: 50, averagePrice: 3900, ltp: 3820, pnl: -4000, pnlPercent: -2.1 },
  { symbol: "HDFCBANK", exchange: "NSE", product: "MIS", quantity: 200, averagePrice: 1640, ltp: 1658, pnl: 3600, pnlPercent: 1.1 },
  { symbol: "RELIANCE", exchange: "NSE", product: "CNC", quantity: 80, averagePrice: 2950, ltp: 2870, pnl: -6400, pnlPercent: -2.7 },
  { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 300, averagePrice: 810, ltp: 832, pnl: 6600, pnlPercent: 2.7 },
  { symbol: "WIPRO", exchange: "NSE", product: "CNC", quantity: 150, averagePrice: 455, ltp: 448, pnl: -1050, pnlPercent: -1.5 },
  { symbol: "SUNPHARMA", exchange: "NSE", product: "CNC", quantity: 60, averagePrice: 1620, ltp: 1580, pnl: -2400, pnlPercent: -2.5 },
  { symbol: "BAJFINANCE", exchange: "NSE", product: "MIS", quantity: 40, averagePrice: 7200, ltp: 7350, pnl: 6000, pnlPercent: 2.1 },
];

// ---------------------------------------------------------------------------
// Data model for a single heatmap cell
// ---------------------------------------------------------------------------

interface HeatCell {
  symbol: string;
  sector: string;
  qty: number;
  entryPrice: number;
  ltp: number;
  pnl: number;
  pnlPercent: number;
  positionValue: number; // |qty| × ltp — drives cell area
}

// ---------------------------------------------------------------------------
// Grouping modes
// ---------------------------------------------------------------------------

type GroupMode = "sector" | "exchange" | "flat";

const GROUP_LABELS: Record<GroupMode, string> = {
  sector: "Sector",
  exchange: "Exchange",
  flat: "Flat",
};

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function fmtPnl(pnl: number): string {
  const abs = INR.format(Math.abs(pnl));
  return pnl >= 0 ? `+₹${abs}` : `-₹${abs}`;
}

function fmtPnlPct(pct: number): string {
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function fmtPrice(p: number): string {
  if (p >= 1000) return p.toFixed(0);
  if (p >= 100) return p.toFixed(1);
  return p.toFixed(2);
}

// ---------------------------------------------------------------------------
// Tooltip component
// ---------------------------------------------------------------------------

interface TooltipProps {
  cell: HeatCell;
  x: number;
  y: number;
  containerWidth: number;
}

function CellTooltip({ cell, x, y, containerWidth }: TooltipProps) {
  // Keep tooltip on screen — flip left if near right edge
  const isRight = x > containerWidth / 2;

  return (
    <div
      className="absolute z-50 pointer-events-none bg-surface-card border border-border-default rounded-md shadow-lg p-2.5 min-w-40 max-w-55"
      style={{
        top: Math.max(4, y - 8),
        left: isRight ? "auto" : x + 12,
        right: isRight ? containerWidth - x + 12 : "auto",
      }}
    >
      <div className="font-mono font-semibold text-xs text-text-primary mb-1.5 truncate">
        {cell.symbol}
      </div>
      <div className="text-xxs text-text-muted mb-1">{cell.sector}</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xxs">
        <span className="text-text-muted">Qty</span>
        <span className={`font-mono text-right ${cell.qty > 0 ? "text-profit" : "text-loss"}`}>
          {cell.qty > 0 ? "+" : ""}{cell.qty}
        </span>
        <span className="text-text-muted">Entry</span>
        <span className="font-mono text-right text-text-secondary">₹{fmtPrice(cell.entryPrice)}</span>
        <span className="text-text-muted">LTP</span>
        <span className="font-mono text-right text-text-secondary">₹{fmtPrice(cell.ltp)}</span>
        <span className="text-text-muted">P&L</span>
        <span className={`font-mono text-right font-medium ${cell.pnl >= 0 ? "text-profit" : "text-loss"}`}>
          {fmtPnl(cell.pnl)}
        </span>
        <span className="text-text-muted">P&L%</span>
        <span className={`font-mono text-right font-medium ${cell.pnlPercent >= 0 ? "text-profit" : "text-loss"}`}>
          {fmtPnlPct(cell.pnlPercent)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface HeatmapCell extends HeatCell {
  x: number;
  y: number;
  width: number;
  height: number;
}

const MIN_CELL_PX = 4; // Cells smaller than this are invisible noise — skip label

function PositionHeatMapWidget(_props: WidgetProps) {
  const mode = useModeStore((s) => s.mode);
  const isExplore = mode === "explore";

  const { data: positionsData, isError, error, refetch, isFetching } = usePositions();
  const trackBehavior = useTrackBehavior();

  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [groupMode, setGroupMode] = useState<GroupMode>("sector");
  const [tooltip, setTooltip] = useState<{ cell: HeatCell; x: number; y: number } | null>(null);

  // Track widget mount
  useEffect(() => {
    trackBehavior("trade", "positionheatmap:view");
  }, [trackBehavior]);

  // Measure container dimensions responsively
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        setDimensions({ width: Math.floor(width), height: Math.floor(height) });
      }
    });

    observer.observe(el);
    // Set initial size
    const rect = el.getBoundingClientRect();
    setDimensions({ width: Math.floor(rect.width), height: Math.floor(rect.height) });

    return () => observer.disconnect();
  }, []);

  // Resolve positions — explore mode uses sample data
  const rawPositions: Position[] = useMemo(() => {
    if (isExplore) return EXPLORE_POSITIONS;
    return (positionsData ?? []) as Position[];
  }, [isExplore, positionsData]);

  // Map positions to HeatCell (normalise API snake_case + camelCase shapes)
  const cells = useMemo<HeatCell[]>(() => {
    return rawPositions
      .map((p) => {
        // OpenAlgo REST may return snake_case at runtime despite typed interface
        const raw = p as unknown as Record<string, unknown>;
        const symbol = (raw["symbol"] as string) ?? "";
        const qty = Number(raw["quantity"] ?? raw["qty"] ?? 0);
        const entry = Number(raw["average_price"] ?? raw["averagePrice"] ?? 0);
        const ltp = Number(raw["ltp"] ?? 0);
        const pnl = Number(raw["pnl"] ?? 0);
        const exchange = (raw["exchange"] as string) ?? "NSE";

        // Recalculate pnlPercent from entry if not provided (avoid 0)
        let pnlPct = Number(raw["pnl_percent"] ?? raw["pnlPercent"] ?? 0);
        if (pnlPct === 0 && entry > 0 && qty !== 0) {
          pnlPct = ((ltp - entry) / entry) * 100 * Math.sign(qty);
        }

        const positionValue = Math.abs(qty) * (ltp > 0 ? ltp : entry);

        return {
          symbol,
          sector: groupMode === "exchange" ? exchange : getSector(symbol),
          qty,
          entryPrice: entry,
          ltp,
          pnl,
          pnlPercent: pnlPct,
          positionValue,
        } satisfies HeatCell;
      })
      .filter((c) => c.positionValue > 0 && c.symbol.length > 0);
  }, [rawPositions, groupMode]);

  // Compute pnlPercent min/max for the diverging colour scale
  const { pnlMin, pnlMax } = useMemo(() => {
    if (cells.length === 0) return { pnlMin: -4, pnlMax: 4 };
    let mn = Infinity, mx = -Infinity;
    cells.forEach((c) => {
      if (c.pnlPercent < mn) mn = c.pnlPercent;
      if (c.pnlPercent > mx) mx = c.pnlPercent;
    });
    // Ensure symmetric range so neutral grey sits at zero
    const bound = Math.max(Math.abs(mn), Math.abs(mx), 0.5);
    return { pnlMin: -bound, pnlMax: bound };
  }, [cells]);

  // Build treemap layout
  const heatmapCells = useMemo<HeatmapCell[]>(() => {
    const { width, height } = dimensions;
    if (width < 10 || height < 10 || cells.length === 0) return [];

    if (groupMode === "flat") {
      // Single-level squarified treemap across all cells
      const sorted = [...cells].sort((a, b) => b.positionValue - a.positionValue);
      const nodes = sorted.map((c) => ({ ...c, value: c.positionValue }));
      return squarifiedTreemap(nodes, 0, 0, width, height);
    }

    // Group by sector/exchange then lay out groups, then cells within each group
    const groups = new Map<string, HeatCell[]>();
    cells.forEach((c) => {
      const key = c.sector;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(c);
    });

    // Group nodes sized by sum of position values — include members so they
    // travel through the layout intact (generic T preserves the field).
    interface GroupNode extends TreeNode {
      key: string;
      members: HeatCell[];
    }
    const groupNodes: GroupNode[] = Array.from(groups.entries())
      .map(([key, members]) => ({
        key,
        members,
        value: members.reduce((s, m) => s + m.positionValue, 0),
      }))
      .sort((a, b) => b.value - a.value);

    const groupLayout = squarifiedTreemap(groupNodes, 0, 0, width, height);

    const result: HeatmapCell[] = [];
    groupLayout.forEach((gl) => {
      const members = [...gl.members].sort((a, b) => b.positionValue - a.positionValue);
      const BORDER = 1; // pixel gutter between group and inner cells
      const innerNodes = members.map((m) => ({ ...m, value: m.positionValue }));
      const innerLayout = squarifiedTreemap(
        innerNodes,
        gl.x + BORDER,
        gl.y + BORDER,
        gl.width - BORDER * 2,
        gl.height - BORDER * 2,
      );
      result.push(...innerLayout);
    });

    return result;
  }, [cells, dimensions, groupMode]);

  // Totals for header
  const totalPnl = useMemo(() => cells.reduce((s, c) => s + c.pnl, 0), [cells]);

  // Handlers
  const handleMouseMove = useCallback(
    (e: MouseEvent<HTMLDivElement>, cell: HeatCell) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setTooltip({
        cell,
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      });
    },
    [],
  );

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  const handleCellClick = useCallback(
    (cell: HeatCell) => {
      trackBehavior("trade", "positionheatmap:navigate");
      window.dispatchEvent(
        new CustomEvent("flinttrade:navigate", {
          detail: { widget: "chart", symbol: cell.symbol, exchange: "NSE" },
        }),
      );
    },
    [trackBehavior],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      className="h-full flex flex-col overflow-hidden bg-surface-base"
      data-tour-target="positionheatmap"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0">
        <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
          Position Heat Map{cells.length > 0 ? ` (${cells.length})` : ""}
        </span>
        <div className="flex items-center gap-3">
          {cells.length > 0 && (
            <span
              className={`font-mono tabular-nums font-medium text-xs ${totalPnl >= 0 ? "text-profit" : "text-loss"}`}
            >
              {fmtPnl(totalPnl)}
            </span>
          )}
          {/* Group mode selector */}
          <Select value={groupMode} onValueChange={(v) => setGroupMode(v as GroupMode)}>
            <SelectTrigger className="h-6 text-xxs bg-surface-hover border-border-subtle text-text-secondary focus:ring-accent/50 w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-surface-card border-border-default">
              {(Object.keys(GROUP_LABELS) as GroupMode[]).map((m) => (
                <SelectItem key={m} value={m} className="text-xxs text-text-primary focus:bg-surface-hover">
                  {GROUP_LABELS[m]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Error banner */}
      {isError && !isExplore && (
        <div className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-xs text-loss shrink-0">
          <span className="flex-1">
            Failed to load positions{error instanceof Error ? `: ${error.message}` : ""}
          </span>
          <Button
            variant="link"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="shrink-0 h-auto p-0 text-xs font-medium text-loss hover:text-loss/80 disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {/* Treemap canvas */}
      <div className="flex-1 min-h-0 relative" ref={containerRef} onMouseLeave={handleMouseLeave}>
        {cells.length === 0 ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-text-muted">
            <SquareStack size={28} className="text-text-disabled" />
            <span className="text-sm">No positions</span>
            <span className="text-xxs text-text-disabled">Open positions will appear here</span>
          </div>
        ) : (
          <div className="absolute inset-0 overflow-hidden">
            {heatmapCells.map((cell) => {
              if (cell.width < MIN_CELL_PX || cell.height < MIN_CELL_PX) return null;

              const bgColour = divergingColourScaleRange(
                cell.pnlPercent,
                pnlMin,
                pnlMax,
              );

              const showLabel = cell.width >= 40 && cell.height >= 24;
              const showPnl = cell.width >= 60 && cell.height >= 36;

              return (
                <div
                  key={cell.symbol}
                  className="absolute border border-surface-base cursor-pointer select-none transition-opacity duration-75 hover:opacity-90 hover:z-10"
                  style={{
                    left: cell.x,
                    top: cell.y,
                    width: cell.width,
                    height: cell.height,
                    backgroundColor: bgColour,
                  }}
                  onMouseMove={(e) => handleMouseMove(e, cell)}
                  onClick={() => handleCellClick(cell)}
                  role="button"
                  tabIndex={0}
                  aria-label={`${cell.symbol}: ${fmtPnl(cell.pnl)} (${fmtPnlPct(cell.pnlPercent)})`}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") handleCellClick(cell);
                  }}
                >
                  {showLabel && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center px-1 overflow-hidden">
                      <span className="font-mono text-xxs font-semibold text-white/90 truncate w-full text-center leading-tight drop-shadow-sm">
                        {cell.symbol}
                      </span>
                      {showPnl && (
                        <span className="font-mono text-xxs text-white/75 mt-0.5 leading-tight drop-shadow-sm">
                          {fmtPnl(cell.pnl)}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Tooltip */}
        {tooltip && (
          <CellTooltip
            cell={tooltip.cell}
            x={tooltip.x}
            y={tooltip.y}
            containerWidth={dimensions.width}
          />
        )}
      </div>

      {/* Explore mode watermark */}
      {isExplore && (
        <div className="shrink-0 px-3 py-1 border-t border-border-subtle text-xxs text-text-disabled text-center">
          Sample data — connect a broker to see live positions
        </div>
      )}
    </div>
  );
}

export default memo(PositionHeatMapWidget);
