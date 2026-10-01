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
 * Bands are stacked at full width. Each one is at least tall enough for its
 * header and one row of tiles, so a small group such as NFO always has a band.
 * When that stack is taller than the canvas the map scrolls. A tile that still
 * cannot fit is named by a "+N more" chip in that band: the tooltip lists the
 * hidden symbols, and the chip opens those rows in the positions list. The
 * omitted positions also stay in an sr-only list. A position is never missing
 * unless its own band says so.
 *
 * Cell AREA is {@link PositionRow.exposure} and cell COLOUR is the row's P&L%,
 * both from the shared kernel — the same numbers the other two views show.
 */

import { useCallback, useEffect, useMemo, useRef, useState, memo } from "react";
import type { MouseEvent } from "react";
import { SquareStack } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

/**
 * Shortest band that can show its header and one thin tile row.
 * A squarified sliver shorter than this used to drop the whole group.
 */
const GROUP_MIN_HEIGHT = GROUP_GUTTER_PX + GROUP_HEADER_PX + GROUP_PAD_PX + MIN_CELL_PX;

function positionTileLabel(row: PositionRow): string {
  return `${row.symbol}: ${fmtPnl(row.mtm)} (${fmtPnlPct(row.pnlPercent)})`;
}

/** Symbol list for a "+N more" title. A repeated symbol keeps its product. */
function hiddenSymbolTitle(rows: readonly PositionRow[]): string {
  const counts = new Map<string, number>();
  rows.forEach((row) => counts.set(row.symbol, (counts.get(row.symbol) ?? 0) + 1));
  return rows
    .map((row) => ((counts.get(row.symbol) ?? 0) > 1 && row.product ? `${row.symbol} ${row.product}` : row.symbol))
    .join(", ");
}

/**
 * Full-width bands, largest exposure first. Every group gets a band at least
 * {@link GROUP_MIN_HEIGHT} tall, even when the stack is taller than the canvas
 * (the map scrolls). Leftover height, once every band has its minimum, follows
 * exposure.
 */
function distributeBandHeights(exposures: readonly number[], height: number): number[] {
  if (exposures.length === 0) return [];
  const stack = Math.max(height, exposures.length * GROUP_MIN_HEIGHT);
  const weight = exposures.reduce((total, value) => total + value, 0) || 1;
  const extra = stack - exposures.length * GROUP_MIN_HEIGHT;
  const heights = exposures.map((value) => GROUP_MIN_HEIGHT + Math.floor((extra * value) / weight));
  let used = heights.reduce((total, value) => total + value, 0);
  let index = 0;
  while (used < stack) {
    heights[index % heights.length] += 1;
    used += 1;
    index += 1;
  }
  return heights;
}

function tileFits(width: number, height: number): boolean {
  return width >= MIN_CELL_PX && height >= MIN_CELL_PX;
}

/** Split `total` into parts of at least `min`, weighted by `values`. */
function splitSizes(values: readonly number[], total: number, min: number): number[] | null {
  if (values.length === 0 || values.length * min > total) return null;
  const weight = values.reduce((sum, value) => sum + value, 0) || 1;
  const extra = total - values.length * min;
  const sizes = values.map((value) => min + Math.floor((extra * value) / weight));
  let used = sizes.reduce((sum, value) => sum + value, 0);
  let index = 0;
  while (used < total) {
    sizes[index % sizes.length] += 1;
    used += 1;
    index += 1;
  }
  return sizes;
}

/**
 * One row or column of tiles, each at least {@link MIN_CELL_PX} on both sides.
 * Used when the squarified layout would crush a leg into nothing.
 */
function layoutStrip(
  members: readonly PositionRow[],
  x: number,
  y: number,
  width: number,
  height: number,
): { drawn: LaidOutCell[]; hidden: PositionRow[] } | null {
  const horizontal = width >= height;
  const along = Math.floor(horizontal ? width : height);
  const cross = horizontal ? height : width;
  if (cross < MIN_CELL_PX) return null;
  const capacity = Math.floor(along / MIN_CELL_PX);
  if (capacity <= 0) return null;
  const visible = members.slice(0, capacity);
  const sizes = splitSizes(visible.map((member) => member.exposure), along, MIN_CELL_PX);
  if (!sizes) return null;
  let cursor = 0;
  const drawn: LaidOutCell[] = visible.map((member, index) => {
    const size = sizes[index] ?? MIN_CELL_PX;
    const cell: LaidOutCell = {
      ...member,
      value: member.exposure,
      x: horizontal ? x + cursor : x,
      y: horizontal ? y : y + cursor,
      width: horizontal ? size : width,
      height: horizontal ? height : size,
    };
    cursor += size;
    return cell;
  });
  return { drawn, hidden: members.slice(capacity) };
}

function layoutCellsInRect(
  members: readonly PositionRow[],
  x: number,
  y: number,
  width: number,
  height: number,
): { drawn: LaidOutCell[]; hidden: PositionRow[] } {
  const ordered = [...members].sort((a, b) => b.exposure - a.exposure);
  if (width < MIN_CELL_PX || height < MIN_CELL_PX) {
    return { drawn: [], hidden: ordered };
  }
  const laid = squarifiedTreemap(
    ordered.map((member) => ({ ...member, value: member.exposure })),
    x,
    y,
    width,
    height,
  );
  const drawn = laid.filter((cell) => tileFits(cell.width, cell.height));
  const drawnKeys = new Set(drawn.map((cell) => heatRowKey(cell)));
  const squarifyHidden = ordered.filter((member) => !drawnKeys.has(heatRowKey(member)));
  if (squarifyHidden.length === 0) return { drawn, hidden: [] };

  const strip = layoutStrip(ordered, x, y, width, height);
  if (strip && strip.hidden.length < squarifyHidden.length) return strip;
  return { drawn, hidden: squarifyHidden };
}

function layoutFlatCells(
  cells: readonly PositionRow[],
  width: number,
  height: number,
): { cells: LaidOutCell[]; hidden: PositionRow[] } {
  const laid = layoutCellsInRect(cells, 0, 0, width, height);
  return { cells: laid.drawn, hidden: laid.hidden };
}

function layoutGroupedBands(
  groups: readonly HeatGroup[],
  width: number,
  height: number,
): { groups: LaidOutGroup[]; cells: LaidOutCell[]; contentHeight: number } {
  const heights = distributeBandHeights(groups.map((group) => group.exposure), height);
  const laidOutGroups: LaidOutGroup[] = [];
  const cells: LaidOutCell[] = [];
  let y = 0;
  heights.forEach((bandHeight, index) => {
    const group = groups[index];
    const gx = GROUP_GUTTER_PX / 2;
    const gy = y + GROUP_GUTTER_PX / 2;
    const gw = Math.max(0, width - GROUP_GUTTER_PX);
    const gh = Math.max(0, bandHeight - GROUP_GUTTER_PX);
    const laid = layoutCellsInRect(
      group.members,
      gx + GROUP_PAD_PX,
      gy + GROUP_HEADER_PX,
      gw - GROUP_PAD_PX * 2,
      gh - GROUP_HEADER_PX - GROUP_PAD_PX,
    );
    laidOutGroups.push({
      key: group.key,
      members: group.members,
      exposure: group.exposure,
      x: gx,
      y: gy,
      width: gw,
      height: gh,
      hidden: laid.hidden,
    });
    cells.push(...laid.drawn);
    y += bandHeight;
  });
  return { groups: laidOutGroups, cells, contentHeight: y };
}

function heatRowKey(row: PositionRow): string {
  return `${row.symbol}\0${row.product}\0${row.exchange}`;
}

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

type LaidOutGroup = HeatGroup & {
  x: number;
  y: number;
  width: number;
  height: number;
  /** Members of this band whose tile is thinner than a readable cell. */
  hidden: PositionRow[];
};

type HeatLayout =
  | { kind: "empty-book" }
  | { kind: "empty-exchange" }
  | { kind: "flat"; cells: LaidOutCell[]; hidden: PositionRow[] }
  | { kind: "grouped"; groups: LaidOutGroup[]; cells: LaidOutCell[]; contentHeight: number };

export interface HeatMapViewProps {
  rows: PositionRow[];
  groupMode: GroupMode;
  /** Empty-state line shown when nothing has exposure. */
  emptyMessage: string;
  emptyHint: string;
  onOpenChart: (row: PositionRow) => void;
  /** Open the positions list on the rows a "+N more" chip could not draw. */
  onRevealRows?: (rows: readonly PositionRow[]) => void;
}

function HeatMapView({ rows, groupMode, emptyMessage, emptyHint, onOpenChart, onRevealRows }: HeatMapViewProps) {
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
      return groupMode === "flat"
        ? { kind: "flat", cells: [], hidden: [] }
        : { kind: "grouped", groups: [], cells: [], contentHeight: 0 };
    }

    if (groupMode === "flat") {
      return { kind: "flat", ...layoutFlatCells(cells, width, height) };
    }

    const groups = collectHeatGroups(cells, groupMode);
    if (groups.length === 0) {
      return { kind: "flat", ...layoutFlatCells(cells, width, height) };
    }

    return { kind: "grouped", ...layoutGroupedBands(groups, width, height) };
  }, [cells, dimensions, groupMode]);

  const heatmapCells = heatLayout.kind === "flat" || heatLayout.kind === "grouped" ? heatLayout.cells : [];
  const groupBands = heatLayout.kind === "grouped" ? heatLayout.groups : [];
  const contentHeight = heatLayout.kind === "grouped" ? heatLayout.contentHeight : dimensions.height;
  const hiddenRows = heatLayout.kind === "flat"
    ? heatLayout.hidden
    : heatLayout.kind === "grouped"
      ? groupBands.flatMap((group) => group.hidden)
      : [];
  const showExchangeEmpty = heatLayout.kind === "empty-exchange";

  const handleMouseMove = useCallback((event: MouseEvent<HTMLDivElement>, cell: PositionRow) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltip({ cell, x: event.clientX - rect.left, y: event.clientY - rect.top });
  }, []);

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  return (
    <div
      className="flex-1 min-h-0 relative"
      data-testid="heat-map"
      ref={containerRef}
      onMouseLeave={handleMouseLeave}
    >
      {cells.length === 0 || showExchangeEmpty ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-text-muted">
          <SquareStack size={28} className="text-text-disabled" />
          <span className="text-sm">{showExchangeEmpty ? NO_EXCHANGE_GROUPS_MESSAGE : emptyMessage}</span>
          {!showExchangeEmpty && <span className="text-xxs text-text-disabled">{emptyHint}</span>}
        </div>
      ) : (
        <div className="absolute inset-0 overflow-auto">
          <div
            className="relative min-h-full"
            style={{ height: contentHeight > 0 ? contentHeight : "100%" }}
          >
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
                  <HeatMoreLabel
                    rows={group.hidden}
                    testId={`heat-more-${group.key}`}
                    onReveal={onRevealRows}
                  />
                </div>
              </div>
            );
          })}
          {heatLayout.kind === "flat" && hiddenRows.length > 0 && (
            <div className="absolute right-1 top-0.5 z-20">
              <HeatMoreLabel rows={hiddenRows} testId="heat-more-flat" onReveal={onRevealRows} />
            </div>
          )}
          {hiddenRows.length > 0 && (
            <ul className="sr-only" aria-label="Positions without a heat map tile">
              {hiddenRows.map((row) => (
                <li key={heatRowKey(row)}>{positionTileLabel(row)}</li>
              ))}
            </ul>
          )}
          {heatmapCells.map((cell) => {
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
                aria-label={positionTileLabel(cell)}
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

function HeatMoreLabel({
  rows,
  testId,
  onReveal,
}: {
  rows: readonly PositionRow[];
  testId: string;
  onReveal?: (rows: readonly PositionRow[]) => void;
}) {
  if (rows.length === 0) return null;
  const title = hiddenSymbolTitle(rows);
  return (
    <Button
      type="button"
      variant="outline"
      size="xs"
      data-testid={testId}
      title={title}
      aria-label={`+${rows.length} more: ${title}`}
      className="pointer-events-auto h-4 shrink-0 px-1 text-xxs font-medium"
      onClick={(event) => {
        event.stopPropagation();
        onReveal?.(rows);
      }}
    >
      +{rows.length} more
    </Button>
  );
}

export default memo(HeatMapView);
