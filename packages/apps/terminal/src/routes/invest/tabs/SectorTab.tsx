/**
 * SectorTab.tsx
 *
 * Real sector allocation view — replaces the old FeatureLockCard placeholder.
 *
 * Data flow: InvestContext holdings → getSectorBreakdown() → Flint donut + Table.
 *
 * Design absorbed from:
 * - etftracker Dashboard4_IndiaSectors: side-by-side donut + sortable sector rows
 * - openalgo-chart SectorHeatmapModal: sector pills with percentage rings
 *
 * Accessibility:
 * - Table has aria-label and aria-sort on sortable columns
 * - Colour swatches have aria-hidden since they are decorative
 * - Empty/loading states are announced via role="status"
 */

import { useMemo, useState } from "react";
import { FlintDonutBreakdown } from "@flinttrade/design-system";
import { RefreshCw, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { StaggeredList } from "@/components/motion/StaggeredList";
import { getSectorBreakdown, type SectorBreakdownEntry } from "@/lib/sectors";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";
import { useInvest } from "../InvestContext";
import { formatINRCompact } from "../formatters";
import type { Holding } from "@/types/api";

// ─── Demo data ────────────────────────────────────────────────────────────────

const DEMO_HOLDINGS: Holding[] = [
  { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2520, pnl: 3500, pnlPercent: 2.86 },
  { symbol: "TCS", exchange: "NSE", quantity: 25, averagePrice: 3800, ltp: 3920, pnl: 3000, pnlPercent: 3.16 },
  { symbol: "HDFCBANK", exchange: "NSE", quantity: 40, averagePrice: 1650, ltp: 1710, pnl: 2400, pnlPercent: 3.64 },
  { symbol: "INFY", exchange: "NSE", quantity: 30, averagePrice: 1500, ltp: 1475, pnl: -750, pnlPercent: -1.67 },
  { symbol: "ICICIBANK", exchange: "NSE", quantity: 60, averagePrice: 1100, ltp: 1145, pnl: 2700, pnlPercent: 4.09 },
  { symbol: "WIPRO", exchange: "NSE", quantity: 100, averagePrice: 450, ltp: 462, pnl: 1200, pnlPercent: 2.67 },
  { symbol: "ITC", exchange: "NSE", quantity: 200, averagePrice: 480, ltp: 495, pnl: 3000, pnlPercent: 3.13 },
  { symbol: "BHARTIARTL", exchange: "NSE", quantity: 30, averagePrice: 1700, ltp: 1745, pnl: 1350, pnlPercent: 2.65 },
  { symbol: "SBIN", exchange: "NSE", quantity: 80, averagePrice: 780, ltp: 798, pnl: 1440, pnlPercent: 2.31 },
  { symbol: "LT", exchange: "NSE", quantity: 20, averagePrice: 3200, ltp: 3150, pnl: -1000, pnlPercent: -1.56 },
];

// ─── Palette ──────────────────────────────────────────────────────────────────
// 10 distinct Tailwind colours mapped by sector index (cyclically)
const SECTOR_PALETTE = [
  { bg: "bg-blue-500", text: "text-blue-400", hex: "#3b82f6" },
  { bg: "bg-emerald-500", text: "text-emerald-400", hex: "#10b981" },
  { bg: "bg-purple-500", text: "text-purple-400", hex: "#a855f7" },
  { bg: "bg-amber-500", text: "text-amber-400", hex: "#f59e0b" },
  { bg: "bg-rose-500", text: "text-rose-400", hex: "#f43f5e" },
  { bg: "bg-cyan-500", text: "text-cyan-400", hex: "#06b6d4" },
  { bg: "bg-orange-500", text: "text-orange-400", hex: "#f97316" },
  { bg: "bg-lime-500", text: "text-lime-400", hex: "#84cc16" },
  { bg: "bg-fuchsia-500", text: "text-fuchsia-400", hex: "#d946ef" },
  { bg: "bg-teal-500", text: "text-teal-400", hex: "#14b8a6" },
];

function paletteFor(index: number) {
  return SECTOR_PALETTE[index % SECTOR_PALETTE.length];
}

// ─── Sort state ───────────────────────────────────────────────────────────────

type SortField = "sector" | "value" | "pct";
type SortDir = "asc" | "desc";

function sortBreakdown(
  data: SectorBreakdownEntry[],
  field: SortField,
  dir: SortDir,
): SectorBreakdownEntry[] {
  return [...data].sort((a, b) => {
    let cmp = 0;
    if (field === "sector") {
      cmp = a.sector.localeCompare(b.sector);
    } else if (field === "value") {
      cmp = a.value - b.value;
    } else {
      cmp = a.pct - b.pct;
    }
    return dir === "asc" ? cmp : -cmp;
  });
}

// ─── Sub-component: sort header button ────────────────────────────────────────

function SortHeader({
  label,
  field,
  active,
  dir,
  onSort,
}: {
  label: string;
  field: SortField;
  active: boolean;
  dir: SortDir;
  onSort: (f: SortField) => void;
}) {
  return (
    <button
      className="flex items-center gap-1 text-xxs font-medium text-text-muted uppercase tracking-wider hover:text-text-secondary transition-colors"
      onClick={() => onSort(field)}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      {label}
      {active ? (
        dir === "asc" ? (
          <ArrowUp className="size-3" />
        ) : (
          <ArrowDown className="size-3" />
        )
      ) : (
        <ArrowUpDown className="size-3 opacity-40" />
      )}
    </button>
  );
}

// ─── Component ────────────────────────────────────────────────────────────────

export function SectorTab() {
  const { holdings: liveHoldings, isLoading, isError } = useInvest();

  // Fall back to demo data when API fails or returns empty
  const isDemo = isError || (!isLoading && liveHoldings.length === 0);
  const holdings = isDemo ? DEMO_HOLDINGS : liveHoldings;

  const [sortField, setSortField] = useState<SortField>("value");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const breakdown = useMemo(
    () =>
      getSectorBreakdown(
        holdings.map((h) => ({ symbol: h.symbol, currentVal: h.ltp * h.quantity })),
      ),
    [holdings],
  );

  const sorted = useMemo(
    () => sortBreakdown(breakdown, sortField, sortDir),
    [breakdown, sortField, sortDir],
  );

  function handleSort(field: SortField) {
    if (field === sortField) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  if (isLoading) {
    return (
      <div
        className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted"
        role="status"
        aria-live="polite"
      >
        <RefreshCw className="size-5 animate-spin" aria-hidden="true" />
        <span className="text-sm">Loading sector data...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Demo banner */}
      {isDemo && <DemoBanner />}

      {/* Header */}
      <div>
        <h3 className="font-heading font-semibold text-sm text-text-primary">
          Sector Allocation
        </h3>
        <p className="text-xs text-text-muted mt-0.5">
          Portfolio value distribution across NSE sectors, derived from your live holdings.
        </p>
      </div>

      {/* Donut + legend */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <GlassCard className="p-5 flex flex-col items-center gap-4">
          <div className="text-xxs text-text-muted uppercase tracking-wider self-start">
            Allocation by sector
          </div>
          <div className="relative w-40 h-40 flex items-center justify-center">
            <FlintDonutBreakdown
              ariaLabel="Sector allocation donut"
              slices={breakdown.map((s, index) => ({
                label: s.sector,
                value: s.value,
                color: paletteFor(index).hex,
              }))}
              className="size-40"
            />
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-xxs text-text-muted">sectors</span>
              <span className="font-mono text-lg font-bold text-text-primary tabular-nums">
                {breakdown.length}
              </span>
            </div>
          </div>
        </GlassCard>

        {/* Top sectors as pills */}
        <GlassCard className="p-5 gap-3">
          <div className="text-xxs text-text-muted uppercase tracking-wider">
            Top sectors by weight
          </div>
          <StaggeredList staggerDelay={40} className="space-y-2">
            {breakdown.slice(0, 6).map((entry, i) => {
              const pal = paletteFor(i);
              return (
                <div key={entry.sector} className="flex items-center gap-2">
                  <span
                    className={cn("size-2.5 rounded-sm shrink-0", pal.bg)}
                    aria-hidden="true"
                  />
                  <span className="text-xs text-text-secondary flex-1">{entry.sector}</span>
                  <Badge
                    variant="outline"
                    className="text-xs font-mono tabular-nums border-border-default text-text-primary"
                  >
                    {entry.pct.toFixed(1)}%
                  </Badge>
                  <span className="text-xs font-mono tabular-nums text-text-muted w-20 text-right shrink-0">
                    {formatINRCompact(entry.value)}
                  </span>
                </div>
              );
            })}
          </StaggeredList>
          {breakdown.length > 6 && (
            <p className="text-xs text-text-muted">
              +{breakdown.length - 6} more sector{breakdown.length - 6 !== 1 ? "s" : ""}
            </p>
          )}
        </GlassCard>
      </div>

      {/* Full breakdown table */}
      <GlassCard className="p-0 overflow-hidden">
        <Table aria-label="Sector breakdown">
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              <TableHead className="h-9 pl-4 w-6" aria-hidden="true" />
              <TableHead className="h-9">
                <SortHeader
                  label="Sector"
                  field="sector"
                  active={sortField === "sector"}
                  dir={sortDir}
                  onSort={handleSort}
                />
              </TableHead>
              <TableHead className="h-9 text-right">
                <SortHeader
                  label="Value"
                  field="value"
                  active={sortField === "value"}
                  dir={sortDir}
                  onSort={handleSort}
                />
              </TableHead>
              <TableHead className="h-9 text-right">
                <SortHeader
                  label="Weight"
                  field="pct"
                  active={sortField === "pct"}
                  dir={sortDir}
                  onSort={handleSort}
                />
              </TableHead>
              <TableHead className="h-9 pr-4 text-right">
                <span className="text-xxs font-medium text-text-muted uppercase tracking-wider">
                  Bar
                </span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((entry) => {
              // Find original index for stable colour across sort changes
              const origIdx = breakdown.findIndex((b) => b.sector === entry.sector);
              const pal = paletteFor(origIdx);
              return (
                <TableRow
                  key={entry.sector}
                  className="border-border-default hover:bg-surface-card transition-colors"
                >
                  <TableCell className="pl-4 w-6 py-2">
                    <span
                      className={cn("size-2.5 rounded-sm inline-block", pal.bg)}
                      aria-hidden="true"
                    />
                  </TableCell>
                  <TableCell className="py-2 text-xs font-semibold text-text-primary">
                    {entry.sector}
                  </TableCell>
                  <TableCell className="py-2 text-right font-mono tabular-nums text-xs text-text-secondary">
                    {formatINRCompact(entry.value)}
                  </TableCell>
                  <TableCell className="py-2 text-right font-mono tabular-nums text-xs text-text-primary">
                    {entry.pct.toFixed(1)}%
                  </TableCell>
                  <TableCell className="py-2 pr-4">
                    <div
                      className="h-1.5 rounded-full overflow-hidden bg-border-default"
                      role="presentation"
                      aria-label={`${entry.pct.toFixed(1)}% allocation bar`}
                    >
                      <div
                        className={cn("h-full rounded-full transition-[width] duration-500", pal.bg)}
                        style={{ width: `${entry.pct}%` }}
                      />
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </GlassCard>

      <p className="text-xs text-text-muted">
        Sector classification based on NSE symbol mapping. Unrecognised symbols are grouped
        under "Other". Data sourced from live holdings via OpenAlgo.
      </p>
    </div>
  );
}
