/**
 * HeatMapView — the "heat" view of the Positions widget.
 *
 * Absorbed from the retired Position Heat Map widget: the squarified treemap,
 * the sector / exchange / flat grouping modes, the hover tooltip and the
 * click-to-open-a-chart contract (`flinttrade:addWidget`, handled in
 * TerminalRoute — the older `flinttrade:navigate` event carried no `path`, so
 * the listener resolved null and the click was a dead no-op).
 *
 * Group by Exchange / Sector draws a labelled band per group (name chip plus
 * optional exposure) so grouping is visible at a glance — not a silent
 * re-sort of the same P&L-coloured tiles (FT-TRADE-005). Flat stays leaf-only.
 *
 * Cell AREA is {@link PositionRow.exposure} and cell COLOUR is the row's P&L%,
 * both from the shared kernel — the same numbers the other two views show.
 */

import { useCallback, useEffect, useMemo, useRef, useState, memo } from "react";
import type { MouseEvent } from "react";
import { SquareStack } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { divergingColourScaleRange } from "@/lib/colourScale";
import { fmtExposure, fmtPnl, fmtPnlPct, type PositionRow } from "./positionBook";
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

/** Honest empty when Group by Exchange cannot form a real group. */
export const NO_EXCHANGE_GROUPS_MESSAGE = "No exchange groups in these positions";

/** Cells smaller than this are invisible noise — no label is drawn. */
const MIN_CELL_PX = 4;

/** Gutter between group bands — stronger than the 1px leaf-tile border. */
const GROUP_GUTTER_PX = 8;

/** Header strip reserved for the group-name chip (and optional exposure). */
const GROUP_HEADER_PX = 22;

/** Inner padding from the group border to the leaf tiles. */
const GROUP_PAD_PX = 3;

export interface HeatGroup {
  key: string;
  members: PositionRow[];
  exposure: number;
}

/**
 * Real group key for a heat cell. Exchange grouping never invents a default
 * (the old `|| "NSE"` fallback made missing metadata look like one silent
 * group). Sector uses the kernel classification, which is already filled in.
 */
export function heatGroupKey(row: PositionRow, groupMode: Exclude<GroupMode, "flat">): string | null {
  const raw = groupMode === "exchange" ? row.exchange : row.sector;
  const key = raw.trim();
  return key.length > 0 ? key : null;
}

/** Bucket cells into labelled groups; rows without a real key are dropped. */
export function collectHeatGroups(
  cells: readonly PositionRow[],
  groupMode: Exclude<GroupMode, "flat">,
): HeatGroup[] {
  const groups = new Map<string, PositionRow[]>();
  cells.forEach((cell) => {
    const key = heatGroupKey(cell, groupMode);
    if (!key) return;
    const bucket = groups.get(key) ?? [];
    bucket.push(cell);
    groups.set(key, bucket);
  });
  return [...groups.entries()]
    .map(([key, members]) => ({
      key,
      members,
      exposure: members.reduce((sum, member) => sum + member.exposure, 0),
    }))
    .sort((a, b) => b.exposure - a.exposure);
}

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

type LaidOutGroup = HeatGroup & { x: number; y: number; width: number; height: number };

type HeatLayout =
  | { kind: "empty-book" }
  | { kind: "empty-exchange" }
  | { kind: "flat"; cells: LaidOutCell[] }
  | { kind: "grouped"; groups: LaidOutGroup[]; cells: LaidOutCell[] };

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

  const heatLayout = useMemo<HeatLayout>(() => {
    if (cells.length === 0) return { kind: "empty-book" };

    if (groupMode !== "flat") {
      const groups = collectHeatGroups(cells, groupMode);
      if (groupMode === "exchange" && groups.length === 0) {
        return { kind: "empty-exchange" };
      }
    }

    const { width, height } = dimensions;
    if (width < 10 || height < 10) {
      return groupMode === "flat" ? { kind: "flat", cells: [] } : { kind: "grouped", groups: [], cells: [] };
    }

    if (groupMode === "flat") {
      const sorted = [...cells].sort((a, b) => b.exposure - a.exposure);
      return {
        kind: "flat",
        cells: squarifiedTreemap(
          sorted.map((cell) => ({ ...cell, value: cell.exposure })),
          0,
          0,
          width,
          height,
        ),
      };
    }

    const groups = collectHeatGroups(cells, groupMode);
    if (groups.length === 0) {
      const sorted = [...cells].sort((a, b) => b.exposure - a.exposure);
      return {
        kind: "flat",
        cells: squarifiedTreemap(
          sorted.map((cell) => ({ ...cell, value: cell.exposure })),
          0,
          0,
          width,
          height,
        ),
      };
    }

    const groupLayout = squarifiedTreemap(
      groups.map((group) => ({ ...group, value: group.exposure })),
      0,
      0,
      width,
      height,
    );

    const laidOutGroups: LaidOutGroup[] = [];
    const result: LaidOutCell[] = [];
    groupLayout.forEach((group) => {
      const gx = group.x + GROUP_GUTTER_PX / 2;
      const gy = group.y + GROUP_GUTTER_PX / 2;
      const gw = Math.max(0, group.width - GROUP_GUTTER_PX);
      const gh = Math.max(0, group.height - GROUP_GUTTER_PX);
      laidOutGroups.push({
        key: group.key,
        members: group.members,
        exposure: group.exposure,
        x: gx,
        y: gy,
        width: gw,
        height: gh,
      });

      const members = [...group.members].sort((a, b) => b.exposure - a.exposure);
      const innerX = gx + GROUP_PAD_PX;
      const innerY = gy + GROUP_HEADER_PX;
      const innerW = gw - GROUP_PAD_PX * 2;
      const innerH = gh - GROUP_HEADER_PX - GROUP_PAD_PX;
      result.push(
        ...squarifiedTreemap(
          members.map((member) => ({ ...member, value: member.exposure })),
          innerX,
          innerY,
          innerW,
          innerH,
        ),
      );
    });

    return { kind: "grouped", groups: laidOutGroups, cells: result };
  }, [cells, dimensions, groupMode]);

  const heatmapCells = heatLayout.kind === "flat" || heatLayout.kind === "grouped" ? heatLayout.cells : [];
  const groupBands = heatLayout.kind === "grouped" ? heatLayout.groups : [];
  const showExchangeEmpty = heatLayout.kind === "empty-exchange";

  const handleMouseMove = useCallback((event: MouseEvent<HTMLDivElement>, cell: PositionRow) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltip({ cell, x: event.clientX - rect.left, y: event.clientY - rect.top });
  }, []);

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  return (
    <div className="flex-1 min-h-0 relative" ref={containerRef} onMouseLeave={handleMouseLeave}>
      {cells.length === 0 || showExchangeEmpty ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-text-muted">
          <SquareStack size={28} className="text-text-disabled" />
          <span className="text-sm">{showExchangeEmpty ? NO_EXCHANGE_GROUPS_MESSAGE : emptyMessage}</span>
          {!showExchangeEmpty && <span className="text-xxs text-text-disabled">{emptyHint}</span>}
        </div>
      ) : (
        <div className="absolute inset-0 overflow-hidden">
          {groupBands.map((group) => {
            const showExposure = group.width >= 88;
            return (
              <div
                key={`heat-group-${group.key}`}
                role="group"
                aria-label={`${group.key} group`}
                data-testid="heat-group-band"
                data-heat-group={group.key}
                className="absolute rounded-sm border-2 border-border-default bg-surface-elevated/50 pointer-events-none overflow-hidden"
                style={{
                  left: group.x,
                  top: group.y,
                  width: group.width,
                  height: group.height,
                }}
              >
                <div className="absolute left-1 top-0.5 right-1 flex items-center gap-1 min-w-0">
                  <Badge
                    variant="outline"
                    data-testid={`heat-group-chip-${group.key}`}
                    className="h-4 px-1.5 text-xxs font-semibold text-text-primary bg-surface-card/95 border-border-default"
                  >
                    {group.key}
                  </Badge>
                  {showExposure && (
                    <span className="text-xxs text-text-muted truncate font-mono">
                      {fmtExposure(group.exposure)}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
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
