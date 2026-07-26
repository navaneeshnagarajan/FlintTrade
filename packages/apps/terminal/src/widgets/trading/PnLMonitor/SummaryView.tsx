/**
 * SummaryView — ported from the P&L Dashboard tool's Summary tab (merge 2.10).
 *
 * Funds cards, donut breakdown, open-positions table and winners/losers bar
 * lists over the SAME positions/funds entries the Live view reads.
 *
 * Corrections made while porting (the tool's originals were bugs):
 *   - Every rupee figure now derives from lib/pnl `positionMtm` instead of the
 *     raw broker `pnl` field (CLAUDE.md quirk 4) — the tool's donut, table and
 *     winners/losers could contradict the Live headline on the same book.
 *   - The headline card shows the parent's corrected day P&L (realised +
 *     unrealised incl. tradebook partial closes), not a raw position sum.
 *   - Numeric cells coerce wire-format rows (string numerics, snake_case);
 *     the tool called `pos.averagePrice.toFixed(2)` on raw rows, which throws
 *     on a string-typed adapter payload.
 *   - "Open positions" now counts rows with a non-zero quantity; the tool
 *     counted every positionbook row, including closed (qty 0) ones.
 */

import { FlintDonutBreakdown, FlintRankedBarList } from "@flinttrade/design-system";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { positionMtm } from "@/lib/pnl";
import type { Funds, Position } from "@/types/api";
import {
  averagePriceOf,
  formatCompactINR,
  ltpOf,
  pnlColor,
  pnlPercentOf,
  quantityOf,
  symbolOf,
} from "./pnlMonitorShared";

// ---------------------------------------------------------------------------
// Derived shapes
// ---------------------------------------------------------------------------

interface SymbolPnl {
  symbol: string;
  pnl: number;
}

function computeSymbolBreakdown(positions: Position[]): SymbolPnl[] {
  return positions
    .map((p) => ({ symbol: symbolOf(p), pnl: positionMtm(p) }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
}

// ---------------------------------------------------------------------------
// Chart fragments (ported from the tool)
// ---------------------------------------------------------------------------

function PnlBreakdownDonut({ data }: { data: { name: string; value: number }[] }) {
  const colours = ["#34d399", "#60a5fa", "#a78bfa", "#fbbf24", "#fb7185", "#22d3ee"];
  const slices = data.slice(0, 6).map((item, index) => ({
    label: item.name,
    value: item.value,
    color: colours[index % colours.length],
  }));

  return (
    <div className="flex w-full items-center justify-center gap-5">
      <FlintDonutBreakdown
        ariaLabel="P&L breakdown by symbol"
        slices={slices}
        className="size-32"
      />
      <div className="min-w-0 space-y-1">
        {slices.map((slice) => (
          <div key={slice.label} className="flex items-center gap-2 text-xs">
            <span
              className="size-2 rounded-full"
              style={{ backgroundColor: slice.color }}
            />
            <span className="min-w-20 text-text-secondary">{slice.label}</span>
            <span className="font-mono text-text-primary">{formatCompactINR(slice.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PnlBarList({
  data,
  tone,
  ariaLabel,
  valueFormatter = formatCompactINR,
}: {
  data: { name: string; value: number }[];
  tone: "profit" | "loss";
  ariaLabel: string;
  valueFormatter?: (value: number) => string;
}) {
  const color = tone === "profit" ? "var(--color-profit, #34d399)" : "var(--color-loss, #f87171)";

  return (
    <FlintRankedBarList
      ariaLabel={ariaLabel}
      entries={data.map((item) => ({ label: item.name, value: item.value, color }))}
      valueFormatter={valueFormatter}
    />
  );
}

// ---------------------------------------------------------------------------
// Summary view
// ---------------------------------------------------------------------------

export interface SummaryViewProps {
  positions: Position[];
  funds: Funds | undefined;
  /** The parent's corrected net day P&L — the same figure the Live headline shows. */
  netPnL: number;
}

export function SummaryView({ positions, funds, netPnL }: SummaryViewProps) {
  const openCount = positions.filter((p) => quantityOf(p) !== 0).length;
  const positiveCount = positions.filter((p) => positionMtm(p) > 0).length;
  const negativeCount = positions.filter((p) => positionMtm(p) < 0).length;

  return (
    <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-2">
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Day P&amp;L</div>
            <div className={`text-xl font-bold font-mono tabular-nums ${pnlColor(netPnL)}`}>{formatCompactINR(netPnL)}</div>
            <div className="text-xs text-text-muted mt-0.5">{openCount} open positions</div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Available Margin</div>
            <div className="text-xl font-bold font-mono tabular-nums text-text-primary">{formatCompactINR(funds?.availableCash ?? 0)}</div>
            <div className="text-xs text-text-muted mt-0.5">Used: {formatCompactINR(funds?.usedMargin ?? 0)}</div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Total Balance</div>
            <div className="text-xl font-bold font-mono tabular-nums text-text-primary">{formatCompactINR(funds?.totalBalance ?? 0)}</div>
            <div className="text-xs text-text-muted mt-0.5">
              {positiveCount}P / {negativeCount}N positions
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Symbol P&L donut */}
      {positions.length > 0 && (() => {
        const donutData = computeSymbolBreakdown(positions)
          .filter((s) => s.pnl !== 0)
          .map((s) => ({ name: s.symbol, value: Math.abs(s.pnl) }));
        return donutData.length > 0 ? (
          <Card className="bg-surface-card border-border-default">
            <CardHeader className="p-3 pb-1">
              <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">P&amp;L Breakdown</CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-1 flex items-center justify-center">
              <PnlBreakdownDonut data={donutData} />
            </CardContent>
          </Card>
        ) : null;
      })()}

      {/* Positions breakdown */}
      <Card className="bg-surface-card border-border-default">
        <CardHeader className="p-3 pb-1">
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">Open Positions</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {positions.length === 0 ? (
            <div className="text-center py-6 text-text-muted text-xs">No open positions</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="text-xs text-text-muted h-7 pl-3 font-normal">Symbol</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 font-normal">Product</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right font-normal">Qty</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right font-normal">Avg</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right font-normal">LTP</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right pr-3 font-normal">P&amp;L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positions.map((pos, i) => {
                  const rowPnl = positionMtm(pos);
                  const avg = averagePriceOf(pos);
                  const ltp = ltpOf(pos);
                  const pct = pnlPercentOf(pos);
                  return (
                    <TableRow key={`${symbolOf(pos)}-${i}`} className="border-border-subtle hover:bg-surface-base">
                      <TableCell className="py-1 pl-3 text-xs font-mono text-text-primary font-medium">{symbolOf(pos)}</TableCell>
                      <TableCell className="py-1 text-xs text-text-muted">{pos.product}</TableCell>
                      <TableCell className="py-1 text-xs font-mono text-text-secondary text-right">{quantityOf(pos)}</TableCell>
                      <TableCell className="py-1 text-xs font-mono text-text-secondary text-right">{avg !== null ? avg.toFixed(2) : "—"}</TableCell>
                      <TableCell className="py-1 text-xs font-mono text-text-primary text-right">{ltp !== null ? ltp.toFixed(2) : "—"}</TableCell>
                      <TableCell className={`py-1 text-xs font-mono text-right pr-3 ${pnlColor(rowPnl)}`}>
                        {formatCompactINR(rowPnl)}
                        {pct !== null && (
                          <span className={`text-xxs ml-1 ${pnlColor(pct)}`}>
                            ({pct >= 0 ? "+" : ""}{pct.toFixed(2)}%)
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Instrument P&L breakdown */}
      {positions.length > 0 && (() => {
        const breakdown = computeSymbolBreakdown(positions);
        const winners = breakdown.filter((s) => s.pnl >= 0).map((s) => ({ name: s.symbol, value: s.pnl }));
        const losers = breakdown.filter((s) => s.pnl < 0).map((s) => ({ name: s.symbol, value: Math.abs(s.pnl) }));
        return (
          <div className="grid grid-cols-2 gap-2">
            {winners.length > 0 && (
              <Card className="bg-surface-card border-border-default">
                <CardHeader className="p-3 pb-1">
                  <CardTitle className="font-heading font-semibold text-xs text-profit uppercase tracking-wider">Top Winners</CardTitle>
                </CardHeader>
                <CardContent className="p-3 pt-1">
                  <PnlBarList data={winners} tone="profit" ariaLabel="Top winners P&L" />
                </CardContent>
              </Card>
            )}
            {losers.length > 0 && (
              <Card className="bg-surface-card border-border-default">
                <CardHeader className="p-3 pb-1">
                  <CardTitle className="font-heading font-semibold text-xs text-loss uppercase tracking-wider">Top Losers</CardTitle>
                </CardHeader>
                <CardContent className="p-3 pt-1">
                  <PnlBarList
                    data={losers}
                    tone="loss"
                    ariaLabel="Top losers P&L"
                    valueFormatter={(v: number) => `-${formatCompactINR(v)}`}
                  />
                </CardContent>
              </Card>
            )}
          </div>
        );
      })()}
    </div>
  );
}
