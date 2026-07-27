/**
 * HeatMapView — the "heat" view of the Positions widget.
 *
 * Absorbed from the retired Position Heat Map widget: the squarified treemap,
 * the sector / exchange / flat grouping modes, the hover tooltip and the
 * click-to-open-a-chart contract (`flinttrade:addWidget`, handled in
 * TerminalRoute — the older `flinttrade:navigate` event carried no `path`, so
 * the listener resolved null and the click was a dead no-op).
 *
 * Cell AREA is {@link PositionRow.exposure} and cell COLOUR is the row's P&L%,
 * both from the shared kernel — the same numbers the other two views show.
 */

import { useCallback, useEffect, useMemo, useRef, useState, memo } from "react";
import type { MouseEvent } from "react";
import { SquareStack } from "lucide-react";
import { divergingColourScaleRange } from "@/lib/colourScale";
import { fmtPnl, fmtPnlPct, type PositionRow } from "./positionBook";
import { squarifiedTreemap } from "./treemap";

// ---------------------------------------------------------------------------
// Grouping modes
// ---------------------------------------------------------------------------

export type GroupMode = "sector" | "exchange" | "flat";

export const GROUP_MODES: readonly GroupMode[] = ["sector", "exchange", "flat"];

export const GROUP_LABELS: Record<GroupMode, string> = {
  sector: "Sector",
  exchange: "Exchange",
  flat: "Flat",
};

/** Resolves the `params.group` panel parameter, defaulting to sector. */
export function resolveGroupMode(value: unknown): GroupMode {
  return typeof value === "string" && (GROUP_MODES as readonly string[]).includes(value)
    ? (value as GroupMode)
    : "sector";
}

/** Cells smaller than this are invisible noise — no label is drawn. */
const MIN_CELL_PX = 4;

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

interface TooltipProps {
  cell: PositionRow;
  x: number;
  y: number;
  containerWidth: number;
}

function CellTooltip({ cell, x, y, containerWidth }: TooltipProps) {
  // Keep the tooltip on screen — flip left when near the right edge.
  const isRight = x > containerWidth / 2;

  function fmtLevel(price: number): string {
    if (price >= 1000) return price.toFixed(0);
    if (price >= 100) return price.toFixed(1);
    return price.toFixed(2);
  }

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
      <div className="text-xxs text-text-muted mb-1">
        {cell.sector}
        {cell.product ? ` · ${cell.product}` : ""}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xxs">
        <span className="text-text-muted">Qty</span>
        <span className={`font-mono text-right ${cell.quantity > 0 ? "text-profit" : "text-loss"}`}>
          {cell.quantity > 0 ? "+" : ""}{cell.quantity}
        </span>
        <span className="text-text-muted">Entry</span>
        <span className="font-mono text-right text-text-secondary">₹{fmtLevel(cell.averagePrice)}</span>
        <span className="text-text-muted">LTP</span>
        <span className="font-mono text-right text-text-secondary">₹{fmtLevel(cell.ltp)}</span>
        <span className="text-text-muted">P&L</span>
        <span className={`font-mono text-right font-medium ${cell.mtm >= 0 ? "text-profit" : "text-loss"}`}>
          {fmtPnl(cell.mtm)}
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
// View
// ---------------------------------------------------------------------------

type LaidOutCell = PositionRow & { value: number; x: number; y: number; width: number; height: number };

export interface HeatMapViewProps {
  rows: PositionRow[];
  groupMode: GroupMode;
  /** Empty-state line shown when nothing has exposure. */
  emptyMessage: string;
  emptyHint: string;
  onOpenChart: (row: PositionRow) => void;
}

function HeatMapView({ rows, groupMode, emptyMessage, emptyHint, onOpenChart }: HeatMapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [tooltip, setTooltip] = useState<{ cell: PositionRow; x: number; y: number } | null>(null);

  // Measure the container responsively.
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
    const rect = el.getBoundingClientRect();
    setDimensions({ width: Math.floor(rect.width), height: Math.floor(rect.height) });

    return () => observer.disconnect();
  }, []);

  // Only rows with something at risk can occupy area (a closed position has
  // zero exposure and would be an invisible zero-area tile).
  const cells = useMemo(() => rows.filter((row) => row.exposure > 0), [rows]);

  // Symmetric bounds so neutral grey sits at zero P&L.
  const { pnlMin, pnlMax } = useMemo(() => {
    if (cells.length === 0) return { pnlMin: -4, pnlMax: 4 };
    let mn = Infinity;
    let mx = -Infinity;
    cells.forEach((cell) => {
      if (cell.pnlPercent < mn) mn = cell.pnlPercent;
      if (cell.pnlPercent > mx) mx = cell.pnlPercent;
    });
    const bound = Math.max(Math.abs(mn), Math.abs(mx), 0.5);
    return { pnlMin: -bound, pnlMax: bound };
  }, [cells]);

  const heatmapCells = useMemo<LaidOutCell[]>(() => {
    const { width, height } = dimensions;
    if (width < 10 || height < 10 || cells.length === 0) return [];

    if (groupMode === "flat") {
      const sorted = [...cells].sort((a, b) => b.exposure - a.exposure);
      return squarifiedTreemap(
        sorted.map((cell) => ({ ...cell, value: cell.exposure })),
        0,
        0,
        width,
        height,
      );
    }

    const groups = new Map<string, PositionRow[]>();
    cells.forEach((cell) => {
      const key = groupMode === "exchange" ? (cell.exchange || "NSE") : cell.sector;
      const bucket = groups.get(key) ?? [];
      bucket.push(cell);
      groups.set(key, bucket);
    });

    interface GroupNode {
      value: number;
      key: string;
      members: PositionRow[];
    }
    const groupNodes: GroupNode[] = [...groups.entries()]
      .map(([key, members]) => ({
        key,
        members,
        value: members.reduce((sum, member) => sum + member.exposure, 0),
      }))
      .sort((a, b) => b.value - a.value);

    const groupLayout = squarifiedTreemap(groupNodes, 0, 0, width, height);

    const result: LaidOutCell[] = [];
    groupLayout.forEach((group) => {
      const members = [...group.members].sort((a, b) => b.exposure - a.exposure);
      const BORDER = 1; // pixel gutter between the group and its cells
      result.push(
        ...squarifiedTreemap(
          members.map((member) => ({ ...member, value: member.exposure })),
          group.x + BORDER,
          group.y + BORDER,
          group.width - BORDER * 2,
          group.height - BORDER * 2,
        ),
      );
    });

    return result;
  }, [cells, dimensions, groupMode]);

  const handleMouseMove = useCallback((event: MouseEvent<HTMLDivElement>, cell: PositionRow) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltip({ cell, x: event.clientX - rect.left, y: event.clientY - rect.top });
  }, []);

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  return (
    <div className="flex-1 min-h-0 relative" ref={containerRef} onMouseLeave={handleMouseLeave}>
      {cells.length === 0 ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-text-muted">
          <SquareStack size={28} className="text-text-disabled" />
          <span className="text-sm">{emptyMessage}</span>
          <span className="text-xxs text-text-disabled">{emptyHint}</span>
        </div>
      ) : (
        <div className="absolute inset-0 overflow-hidden">
          {heatmapCells.map((cell) => {
            if (cell.width < MIN_CELL_PX || cell.height < MIN_CELL_PX) return null;

            const showLabel = cell.width >= 40 && cell.height >= 24;
            const showPnl = cell.width >= 60 && cell.height >= 36;

            return (
              <div
                key={`${cell.symbol}-${cell.product}-${cell.exchange}`}
                className="absolute border border-surface-base cursor-pointer select-none transition-opacity duration-75 hover:opacity-90 hover:z-10"
                style={{
                  left: cell.x,
                  top: cell.y,
                  width: cell.width,
                  height: cell.height,
                  backgroundColor: divergingColourScaleRange(cell.pnlPercent, pnlMin, pnlMax),
                }}
                onMouseMove={(event) => handleMouseMove(event, cell)}
                onClick={() => onOpenChart(cell)}
                role="button"
                tabIndex={0}
                aria-label={`${cell.symbol}: ${fmtPnl(cell.mtm)} (${fmtPnlPct(cell.pnlPercent)})`}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") onOpenChart(cell);
                }}
              >
                {showLabel && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center px-1 overflow-hidden">
                    <span className="font-mono text-xxs font-semibold text-white/90 truncate w-full text-center leading-tight drop-shadow-sm">
                      {cell.symbol}
                    </span>
                    {showPnl && (
                      <span className="font-mono text-xxs text-white/75 mt-0.5 leading-tight drop-shadow-sm">
                        {fmtPnl(cell.mtm)}
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {tooltip && (
        <CellTooltip
          cell={tooltip.cell}
          x={tooltip.x}
          y={tooltip.y}
          containerWidth={dimensions.width}
        />
      )}
    </div>
  );
}

export default memo(HeatMapView);
