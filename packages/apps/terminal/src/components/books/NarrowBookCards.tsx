/**
 * NarrowBookCards — stacked position/holding rows for phone-width books.
 *
 * Each card keeps symbol, size, last price, and P&L / P&L% on one screen so
 * critical figures are not clipped off to the right of a wide nowrap table.
 */

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface NarrowBookCardRow {
  id: string;
  symbol: string;
  detail: string;
  pnl: string;
  pnlPercent: string;
  pnlPositive: boolean;
  actions?: ReactNode;
}

export function NarrowBookCards({
  rows,
  ariaLabel,
}: {
  rows: readonly NarrowBookCardRow[];
  ariaLabel: string;
}) {
  return (
    <ul
      aria-label={ariaLabel}
      data-layout="cards"
      className="min-h-0 flex-1 divide-y divide-border-subtle overflow-y-auto"
    >
      {rows.map((row) => (
        <li key={row.id} className="flex items-start justify-between gap-3 px-3 py-2">
          <div className="min-w-0">
            <div className="truncate font-mono font-medium text-text-primary">{row.symbol}</div>
            <div className="font-mono text-xxs tabular-nums text-text-muted">{row.detail}</div>
            {row.actions}
          </div>
          <div
            className={cn(
              "shrink-0 text-right font-mono tabular-nums",
              row.pnlPositive ? "text-profit" : "text-loss",
            )}
          >
            <div className="text-xs font-semibold">{row.pnl}</div>
            <div className="text-xxs opacity-75">{row.pnlPercent}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}
