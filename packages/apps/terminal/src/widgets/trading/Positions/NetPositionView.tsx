/**
 * NetPositionView — the "net" view of the Positions widget.
 *
 * Absorbed from the retired Net Position widget: netting per symbol with flat
 * rows dropped, collapsible grouping by underlying, and the totals footer.
 *
 * It renders from the SAME normalised rows as the table and heat views, so the
 * money it shows cannot drift from theirs (see `positionBook.ts`).
 */

import { useState, memo } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  fmtExposure,
  fmtPnl,
  fmtPrice,
  groupByUnderlying,
  offsetLegTooltip,
  type NetPositionRow,
} from "./positionBook";

interface UnderlyingGroupProps {
  underlying: string;
  rows: NetPositionRow[];
}

function UnderlyingGroup({ underlying, rows }: UnderlyingGroupProps) {
  const [expanded, setExpanded] = useState(true);

  const groupPnl = rows.reduce((sum, row) => sum + row.mtm, 0);
  const groupExposure = rows.reduce((sum, row) => sum + row.exposure, 0);

  return (
    <tbody>
      {/* Group header row */}
      <tr
        className="bg-surface-card cursor-pointer hover:bg-surface-hover transition-colors"
        onClick={() => setExpanded((open) => !open)}
        aria-expanded={expanded}
        aria-label={`${underlying} group — ${rows.length} positions`}
      >
        <td className="py-1.5 px-2 text-xs font-semibold text-text-primary" colSpan={2}>
          <span className="flex items-center gap-1">
            {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            {underlying}
            <span className="ml-1 text-xxs text-text-muted font-normal">({rows.length})</span>
          </span>
        </td>
        <td className="py-1.5 px-2 text-xs text-right text-text-muted" />
        <td className="py-1.5 px-2 text-xs text-right text-text-muted" />
        <td
          className={cn(
            "py-1.5 px-2 text-xs font-mono font-semibold text-right",
            groupPnl >= 0 ? "text-profit" : "text-loss",
          )}
        >
          {fmtPnl(groupPnl)}
        </td>
        <td className="py-1.5 px-2 text-xs text-right text-text-muted">
          {fmtExposure(groupExposure)}
        </td>
      </tr>

      {/* Position rows */}
      {expanded && rows.map((row, index) => (
        <tr
          key={`${row.symbol}:${row.product ?? ""}:${index}`}
          className="border-t border-border-subtle hover:bg-surface-hover transition-colors"
          aria-label={
            row.offset && row.product
              ? `${row.symbol} ${row.product}: net qty ${row.netQty}`
              : `${row.symbol}: net qty ${row.netQty}`
          }
        >
          <td
            className="py-1.5 pl-6 pr-2 text-xs text-text-secondary max-w-40"
            title={row.legs > 1 ? `${row.symbol} — netted from ${row.legs} rows` : row.symbol}
          >
            <span className="inline-flex items-center gap-1 min-w-0">
              <span className="truncate">{row.symbol}</span>
              {row.offset && (
                <Badge
                  variant="outline"
                  title={offsetLegTooltip(row.offsetProducts ?? [])}
                  className="h-4 px-1 text-xxs font-medium text-text-secondary"
                >
                  Offset
                </Badge>
              )}
            </span>
          </td>

          <td
            className={cn(
              "py-1.5 px-2 text-xs font-mono tabular-nums font-semibold text-center",
              row.netQty > 0 ? "text-profit" : "text-loss",
            )}
          >
            {row.netQty > 0 ? `+${row.netQty}` : row.netQty}
          </td>

          <td className="py-1.5 px-2 text-xs font-mono tabular-nums text-right text-text-secondary">
            {fmtPrice(row.avgPrice)}
          </td>

          <td className="py-1.5 px-2 text-xs font-mono tabular-nums text-right text-text-primary">
            {fmtPrice(row.ltp)}
          </td>

          <td
            className={cn(
              "py-1.5 px-2 text-xs font-mono tabular-nums font-semibold text-right",
              row.mtm >= 0 ? "text-profit" : "text-loss",
            )}
          >
            {fmtPnl(row.mtm)}
          </td>

          <td className="py-1.5 px-2 text-xs font-mono tabular-nums text-right text-text-muted">
            {fmtExposure(row.exposure)}
          </td>
        </tr>
      ))}
    </tbody>
  );
}

export interface NetPositionViewProps {
  rows: NetPositionRow[];
  /**
   * Mark-to-market of the WHOLE book, including symbols netted out of the
   * table below. Same figure the header shows in every view.
   */
  totalPnl: number;
  /** Σ exposure of the net rows shown. */
  totalExposure: number;
  /** Symbols whose legs are all at quantity 0. Hidden in the footer at 0. */
  flatSymbols: number;
  /** Symbols whose legs net to 0 but still have an open leg. Hidden at 0. */
  offsetSymbols: number;
}

function NetPositionView({
  rows,
  totalPnl,
  totalExposure,
  flatSymbols,
  offsetSymbols,
}: NetPositionViewProps) {
  const underlyings = groupByUnderlying(rows);

  return (
    <div className="flex-1 min-h-0 overflow-auto">
      <table className="w-full text-xs border-collapse" aria-label="Net positions table">
        <thead className="sticky top-0 z-10">
          <tr className="bg-surface-card border-b border-border-default">
            <th className="text-left py-1.5 px-2 text-xxs text-text-muted font-medium">Symbol</th>
            <th className="text-center py-1.5 px-2 text-xxs text-text-muted font-medium">Net Qty</th>
            <th className="text-right py-1.5 px-2 text-xxs text-text-muted font-medium">Avg</th>
            <th className="text-right py-1.5 px-2 text-xxs text-text-muted font-medium">LTP</th>
            <th className="text-right py-1.5 px-2 text-xxs text-text-muted font-medium">Net P&amp;L</th>
            <th className="text-right py-1.5 px-2 text-xxs text-text-muted font-medium">Exposure</th>
          </tr>
        </thead>

        {[...underlyings.entries()].map(([underlying, groupRows]) => (
          <UnderlyingGroup key={underlying} underlying={underlying} rows={groupRows} />
        ))}

        {/* Totals. The P&L column carries the WHOLE book's mark-to-market.
            Flat symbols are absent from the rows; offset symbols stay, one
            row per open leg, so their margin is in the exposure column. */}
        <tfoot>
          <tr className="bg-surface-card border-t-2 border-border-default">
            <td className="py-2 px-2 text-xs font-bold text-text-primary" colSpan={4}>
              Total
              {offsetSymbols > 0 && (
                <span className="ml-1 text-xxs font-normal text-text-muted">
                  incl. {offsetSymbols} offset symbol{offsetSymbols === 1 ? "" : "s"} (legs still open)
                </span>
              )}
              {flatSymbols > 0 && (
                <span className="ml-1 text-xxs font-normal text-text-muted">
                  incl. {flatSymbols} flat symbol{flatSymbols === 1 ? "" : "s"}
                </span>
              )}
            </td>
            <td
              className={cn(
                "py-2 px-2 text-xs font-mono tabular-nums font-bold text-right",
                totalPnl >= 0 ? "text-profit" : "text-loss",
              )}
            >
              {fmtPnl(totalPnl)}
            </td>
            <td className="py-2 px-2 text-xs font-mono tabular-nums font-bold text-right text-text-secondary">
              {fmtExposure(totalExposure)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export default memo(NetPositionView);
