/** FlintTrade holdings allocation, grouped by the shared sector vocabulary. */
import { useMemo } from "react";
import { FlintDonutBreakdown } from "@flinttrade/design-system";
import { ExampleChip } from "@/components/ui/ExampleChip";
import { getSectorBreakdown } from "@/lib/sectors";
import { useInvest } from "../InvestContext";
import { formatINR } from "../formatters";

const COLOURS = ["#34d399", "#60a5fa", "#fbbf24", "#c084fc", "#fb7185", "#22d3ee", "#a3e635"];

export function SectorTab() {
  const { holdings, isLoading, isError, isSampleData } = useInvest();
  const valued = useMemo(() => holdings.flatMap((holding) => {
    const value = holding.quantity * holding.ltp;
    return Number.isFinite(value) && value > 0 ? [{ symbol: holding.symbol, currentVal: value }] : [];
  }), [holdings]);
  const sectors = useMemo(() => getSectorBreakdown(valued), [valued]);
  const total = sectors.reduce((sum, row) => sum + row.value, 0);
  const unavailable = holdings.length - valued.length;

  return <section className="h-full overflow-auto p-4 space-y-4" aria-label="Sector allocation">
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold text-text-primary">Sector Allocation</h2>
      {isSampleData ? <ExampleChip always /> : null}
    </div>
    <p className="text-xs text-text-muted">{isSampleData
      ? "Example sector split. Connect a broker to see yours."
      : "Portfolio value distribution across NSE sectors, derived from your live holdings."}</p>
    {isLoading ? <p role="status">Loading holdings…</p> : isError ? <p role="alert">Holdings are unavailable. Sector values cannot be calculated.</p> : total <= 0
      ? <p className="text-sm text-text-muted">No valued holdings to group by sector.</p>
      : <div className="flex flex-wrap items-start gap-6">
        <FlintDonutBreakdown ariaLabel="Sector allocation donut"
          slices={sectors.map((row, index) => ({ label: row.sector, value: row.value, color: COLOURS[index % COLOURS.length] }))}
          centerValue={formatINR(total)} centerLabel="Holdings value" />
        <table className="min-w-64 flex-1 text-xs" aria-label="Holdings by sector">
          <thead><tr className="text-text-muted border-b border-border"><th className="text-left py-2">Sector</th><th className="text-right">Value</th><th className="text-right">Share</th></tr></thead>
          <tbody>{sectors.map((row, index) => <tr key={row.sector} className="border-b border-border/50">
            <td className="py-3"><span aria-hidden="true" className="inline-block size-2 mr-2 rounded-full" style={{ backgroundColor: COLOURS[index % COLOURS.length] }} />{row.sector}</td>
            <td className="text-right font-mono">{formatINR(row.value)}</td><td className="text-right font-mono">{row.pct.toFixed(1)}%</td>
          </tr>)}</tbody>
        </table>
      </div>}
    {unavailable > 0 ? <p className="text-xs text-text-muted">{unavailable} holding(s) have no positive market value and are excluded from this allocation.</p> : null}
    <p className="text-xs text-text-muted">{isSampleData ? "Example data. Not from your holdings." : "Data sourced from live holdings via your active broker data source."}</p>
  </section>;
}
