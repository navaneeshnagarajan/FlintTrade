/**
 * DeliveryDataWidget — NSE delivery-percentage conviction table.
 *
 * Rehomed from the retired Market Intelligence tool's Delivery Data tab
 * (ruling D4). Nothing else in the terminal surfaces delivery percentage:
 * `Positions`, `Holdings` and the option surfaces all read intraday or F&O
 * planes, and the CNC/"delivery" strings elsewhere are PRODUCT types, not the
 * settled-quantity ratio this table is about. High delivery means buyers took
 * the shares rather than squaring off — the classic institutional-conviction
 * read on an Indian cash-market move.
 *
 * PROVENANCE — this widget is SAMPLE-ONLY and says so unconditionally.
 *
 * The figures come from the NSE full bhavcopy (the "full" variant the local
 * data pipeline already downloads — see
 * `packages/core/historical/src/flinttrade_historical/bhavcopy.py`, whose
 * header calls it "the full bhavcopy incl. delivery data", and Settings →
 * Local Data, which offers the download). What does NOT exist yet is a read
 * route over it: `local_data_routes.py` registers `/v1/historify/bars`,
 * `/v1/historify/bars/summary` and `/v1/historify/bhavcopy/download`, and
 * none of them serves per-symbol delivery. So there is no live path to fail
 * closed on — the badge is unconditional, exactly as it is for the other
 * sample-only widgets in the catalogue (Heat Calendar, Gap Analysis, PCR
 * Trend), and the empty-source note names the missing route rather than
 * implying the data merely has not arrived today.
 */

import { useState, useMemo, memo } from "react";
import { ArrowUpDown, Package } from "lucide-react";
import { FlintLinearMeter } from "@flinttrade/design-system";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// ---------------------------------------------------------------------------
// Types + sample rows
// ---------------------------------------------------------------------------

export interface DeliveryRow {
  symbol: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume_lakh: number;
  delivery_pct: number;
  series: string;
}

/**
 * Illustrative rows carried over from the Market Intelligence tab. Every
 * surface that renders them carries the unconditional "Sample data" badge
 * above; they are never presented as a settled session.
 */
export const SAMPLE_DELIVERY_ROWS: DeliveryRow[] = [
  { symbol: "HDFCBANK", open: 1672.0, high: 1698.5, low: 1668.0, close: 1689.5, volume_lakh: 128.4, delivery_pct: 78.4, series: "EQ" },
  { symbol: "TCS", open: 3840.0, high: 3880.0, low: 3824.0, close: 3848.5, volume_lakh: 24.8, delivery_pct: 72.1, series: "EQ" },
  { symbol: "RELIANCE", open: 2468.0, high: 2492.0, low: 2456.0, close: 2481.5, volume_lakh: 84.2, delivery_pct: 68.9, series: "EQ" },
  { symbol: "INFY", open: 1834.0, high: 1858.5, low: 1828.0, close: 1842.0, volume_lakh: 56.4, delivery_pct: 65.3, series: "EQ" },
  { symbol: "ITC", open: 458.5, high: 465.0, low: 455.0, close: 461.5, volume_lakh: 184.2, delivery_pct: 62.8, series: "EQ" },
  { symbol: "SBIN", open: 778.0, high: 792.0, low: 774.0, close: 784.5, volume_lakh: 248.0, delivery_pct: 58.4, series: "EQ" },
  { symbol: "WIPRO", open: 524.0, high: 530.5, low: 519.5, close: 526.0, volume_lakh: 42.8, delivery_pct: 55.2, series: "EQ" },
  { symbol: "BAJFINANCE", open: 6820.0, high: 6892.0, low: 6810.0, close: 6848.0, volume_lakh: 24.8, delivery_pct: 52.7, series: "EQ" },
  { symbol: "KOTAKBANK", open: 1748.0, high: 1768.0, low: 1742.0, close: 1754.0, volume_lakh: 38.4, delivery_pct: 48.9, series: "EQ" },
  { symbol: "AXISBANK", open: 1082.0, high: 1098.0, low: 1078.5, close: 1092.5, volume_lakh: 92.4, delivery_pct: 44.2, series: "EQ" },
];

// ---------------------------------------------------------------------------
// Conviction bands
// ---------------------------------------------------------------------------

/** Colour + fill for a delivery percentage band. */
export function deliveryBand(pct: number): { cls: string; fill: string; label: string } {
  if (pct >= 60) return { cls: "text-profit", fill: "#10b981", label: "High conviction" };
  if (pct >= 45) return { cls: "text-warning", fill: "#f59e0b", label: "Medium conviction" };
  return { cls: "text-text-secondary", fill: "#6b7280", label: "Low conviction" };
}

type SortField = keyof DeliveryRow;

const HEADERS: { label: string; field: SortField }[] = [
  { label: "Symbol", field: "symbol" },
  { label: "Open", field: "open" },
  { label: "High", field: "high" },
  { label: "Low", field: "low" },
  { label: "Close", field: "close" },
  { label: "Volume (L)", field: "volume_lakh" },
  { label: "Delivery %", field: "delivery_pct" },
];

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

function DeliveryDataWidget() {
  const [sortField, setSortField] = useState<SortField>("delivery_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    return [...SAMPLE_DELIVERY_ROWS].sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "desc" ? bv - av : av - bv;
      }
      return sortDir === "desc"
        ? String(bv).localeCompare(String(av))
        : String(av).localeCompare(String(bv));
    });
  }, [sortField, sortDir]);

  const handleSort = (field: SortField) => {
    if (sortField === field) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const sortStateFor = (field: SortField): "none" | "ascending" | "descending" => {
    if (sortField !== field) return "none";
    return sortDir === "asc" ? "ascending" : "descending";
  };

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Delivery Data widget">
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Package size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Delivery Data</span>
        <span
          className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
          role="status"
          aria-label="Showing sample delivery data; no delivery source is wired yet"
          title="No live delivery source is wired — the full bhavcopy is downloaded but no read route serves per-symbol delivery yet. Do not base trading decisions on these figures."
        >
          Sample data
        </span>
        <div className="flex-1" />
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              {HEADERS.map(({ label, field }) => (
                <TableHead
                  key={field}
                  aria-sort={sortStateFor(field)}
                  className={["h-8 px-2 text-xxs", sortField === field ? "text-accent" : "text-text-muted"].join(" ")}
                >
                  <button
                    type="button"
                    aria-label={`Sort by ${label}`}
                    className="inline-flex items-center gap-1 rounded-sm text-left hover:text-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
                    onClick={() => handleSort(field)}
                  >
                    <span>{label}</span>
                    {sortField === field && <ArrowUpDown size={9} className="opacity-80" aria-hidden="true" />}
                  </button>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((row) => {
              const changePct = ((row.close - row.open) / row.open) * 100;
              const band = deliveryBand(row.delivery_pct);
              return (
                <TableRow key={row.symbol} className="border-border-subtle hover:bg-surface-hover">
                  <TableCell className="px-2 py-1.5">
                    <div className="text-xs font-semibold font-mono text-text-primary">{row.symbol}</div>
                    <div className={`text-xxs font-mono ${changePct >= 0 ? "text-profit" : "text-loss"}`}>
                      {changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%
                    </div>
                  </TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary tabular-nums">{row.open.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-profit tabular-nums">{row.high.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-loss tabular-nums">{row.low.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-text-primary tabular-nums">{row.close.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary tabular-nums">{row.volume_lakh.toFixed(1)}L</TableCell>
                  <TableCell className="px-2 py-1.5">
                    <div className="flex items-center gap-2">
                      <FlintLinearMeter
                        ariaLabel={`${row.symbol} delivery percentage`}
                        value={row.delivery_pct}
                        fillColor={band.fill}
                        heightClassName="h-1.5"
                        className="flex-1"
                      />
                      <span className={`font-mono text-xs font-semibold w-10 text-right tabular-nums ${band.cls}`}>
                        {row.delivery_pct.toFixed(1)}%
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Legend + source note */}
      <div className="flex-none px-2 py-1.5 border-t border-border-default space-y-1">
        <div className="flex items-center gap-3 text-xxs">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-profit inline-block" aria-hidden="true" />
            <span className="text-text-muted">High ≥60%</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-warning inline-block" aria-hidden="true" />
            <span className="text-text-muted">Medium 45–60%</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-text-muted inline-block" aria-hidden="true" />
            <span className="text-text-muted">Low &lt;45%</span>
          </span>
        </div>
        <p className="text-xxs text-text-muted">
          Source would be the NSE full bhavcopy, published after 18:00 IST on trading
          days. The download exists under Settings → Local Data; no read route serves
          per-symbol delivery yet, so these rows stay illustrative.
        </p>
      </div>
    </div>
  );
}

export default memo(DeliveryDataWidget);
