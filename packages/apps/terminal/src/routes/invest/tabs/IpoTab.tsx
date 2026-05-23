/**
 * IpoTab.tsx
 *
 * Static IPO reference data tab — shows recent and upcoming Indian IPOs.
 * Live IPO tracking will replace this when the NSE IPO scraper
 * backend is available.
 *
 * Design absorbed from:
 * - EtfTab.tsx: GlassCard + TanStack Table sortable pattern
 * - SectorTab.tsx: sort-header, status badge pattern
 *
 * Accessibility:
 * - Table has aria-label and aria-sort on sortable columns
 * - Status badges use text labels (not colour-only signals)
 * - Info banner uses role="status"
 */

import { useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import { Info, TrendingUp, TrendingDown } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface IpoEntry {
  name: string;
  symbol: string;
  issueSize: string;
  priceRange: string;
  openDate: string;
  closeDate: string;
  listingDate: string;
  status: "upcoming" | "open" | "closed" | "listed";
  listingGain?: number;
}

// ─── Static data — real recent Indian IPOs (2025–2026) ──────────────────────

const RECENT_IPOS: IpoEntry[] = [
  {
    name: "Hexaware Technologies",
    symbol: "HEXAWARE",
    issueSize: "\u20B99,950 Cr",
    priceRange: "\u20B9674 - \u20B9708",
    openDate: "2025-02-12",
    closeDate: "2025-02-14",
    listingDate: "2025-02-19",
    status: "listed",
    listingGain: 2.6,
  },
  {
    name: "Dr Agarwal's Health Care",
    symbol: "DRAGARWAL",
    issueSize: "\u20B93,027 Cr",
    priceRange: "\u20B9382 - \u20B9402",
    openDate: "2025-01-29",
    closeDate: "2025-01-31",
    listingDate: "2025-02-05",
    status: "listed",
    listingGain: 11.4,
  },
  {
    name: "Stallion India Fluorochemicals",
    symbol: "STALFLUO",
    issueSize: "\u20B9600 Cr",
    priceRange: "\u20B9375 - \u20B9395",
    openDate: "2025-01-16",
    closeDate: "2025-01-20",
    listingDate: "2025-01-23",
    status: "listed",
    listingGain: 18.2,
  },
  {
    name: "Capital Infra Trust InvIT",
    symbol: "CAPITALIT",
    issueSize: "\u20B92,488 Cr",
    priceRange: "\u20B999 - \u20B9100",
    openDate: "2025-01-07",
    closeDate: "2025-01-09",
    listingDate: "2025-01-14",
    status: "listed",
    listingGain: -3.0,
  },
  {
    name: "Indo Farm Equipment",
    symbol: "INDOFARM",
    issueSize: "\u20B9260 Cr",
    priceRange: "\u20B9204 - \u20B9215",
    openDate: "2024-12-31",
    closeDate: "2025-01-02",
    listingDate: "2025-01-07",
    status: "listed",
    listingGain: 20.5,
  },
  {
    name: "Ventive Hospitality",
    symbol: "VENTIVE",
    issueSize: "\u20B91,600 Cr",
    priceRange: "\u20B9610 - \u20B9643",
    openDate: "2024-12-20",
    closeDate: "2024-12-24",
    listingDate: "2024-12-30",
    status: "listed",
    listingGain: -1.2,
  },
  {
    name: "Transrail Lighting",
    symbol: "TRANSRAIL",
    issueSize: "\u20B9839 Cr",
    priceRange: "\u20B9410 - \u20B9432",
    openDate: "2024-12-19",
    closeDate: "2024-12-23",
    listingDate: "2024-12-27",
    status: "listed",
    listingGain: 32.0,
  },
  {
    name: "Unimech Aerospace",
    symbol: "UNIMECH",
    issueSize: "\u20B9500 Cr",
    priceRange: "\u20B91,381 - \u20B91,455",
    openDate: "2024-12-23",
    closeDate: "2024-12-26",
    listingDate: "2024-12-31",
    status: "listed",
    listingGain: 88.8,
  },
  {
    name: "DAM Capital Advisors",
    symbol: "DAMCAPITAL",
    issueSize: "\u20B9840 Cr",
    priceRange: "\u20B9269 - \u20B9283",
    openDate: "2024-12-19",
    closeDate: "2024-12-23",
    listingDate: "2024-12-27",
    status: "listed",
    listingGain: 30.5,
  },
  {
    name: "Carraro India",
    symbol: "CARRARO",
    issueSize: "\u20B91,250 Cr",
    priceRange: "\u20B9668 - \u20B9704",
    openDate: "2024-12-20",
    closeDate: "2024-12-24",
    listingDate: "2024-12-30",
    status: "listed",
    listingGain: -4.6,
  },
];

// ─── Status badge helper ─────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  IpoEntry["status"],
  { label: string; className: string }
> = {
  upcoming: {
    label: "Upcoming",
    className: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  },
  open: {
    label: "Open",
    className: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  },
  closed: {
    label: "Closed",
    className: "bg-zinc-500/10 text-zinc-400 border-zinc-500/30",
  },
  listed: {
    label: "Listed",
    className: "bg-purple-500/10 text-purple-400 border-purple-500/30",
  },
};

function StatusBadge({ status }: { status: IpoEntry["status"] }) {
  const config = STATUS_CONFIG[status];
  return (
    <Badge
      variant="outline"
      className={cn("text-xs font-medium rounded px-2 py-0.5", config.className)}
    >
      {config.label}
    </Badge>
  );
}

// ─── Listing gain cell ───────────────────────────────────────────────────────

function ListingGainCell({ gain }: { gain: number | undefined }) {
  if (gain === undefined) {
    return <span className="text-xs text-text-muted">—</span>;
  }
  const positive = gain >= 0;
  return (
    <div className={cn("flex items-center gap-1 justify-end", positive ? "text-profit" : "text-loss")}>
      {positive ? (
        <TrendingUp className="size-3" aria-hidden="true" />
      ) : (
        <TrendingDown className="size-3" aria-hidden="true" />
      )}
      <span className="font-mono text-xs font-semibold tabular-nums">
        {positive ? "+" : ""}{gain.toFixed(1)}%
      </span>
    </div>
  );
}

// ─── Format date to readable ─────────────────────────────────────────────────

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

// ─── Column definitions ──────────────────────────────────────────────────────

function buildColumns(): ColumnDef<IpoEntry>[] {
  return [
    {
      accessorKey: "name",
      header: "Company",
      cell: ({ row }) => (
        <div>
          <div className="font-mono text-xs font-bold text-text-primary">{row.original.symbol}</div>
          <div className="text-xs text-text-muted truncate max-w-48">{row.original.name}</div>
        </div>
      ),
    },
    {
      accessorKey: "issueSize",
      header: () => <span className="block text-right">Issue Size</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono text-xs text-text-secondary tabular-nums">
          {getValue() as string}
        </div>
      ),
    },
    {
      accessorKey: "priceRange",
      header: () => <span className="block text-right">Price Range</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono text-xs text-text-secondary tabular-nums">
          {getValue() as string}
        </div>
      ),
    },
    {
      accessorKey: "openDate",
      header: "Open",
      cell: ({ getValue }) => (
        <div className="text-xs text-text-muted whitespace-nowrap">
          {formatDate(getValue() as string)}
        </div>
      ),
    },
    {
      accessorKey: "closeDate",
      header: "Close",
      cell: ({ getValue }) => (
        <div className="text-xs text-text-muted whitespace-nowrap">
          {formatDate(getValue() as string)}
        </div>
      ),
    },
    {
      accessorKey: "listingDate",
      header: "Listing",
      cell: ({ getValue }) => (
        <div className="text-xs text-text-muted whitespace-nowrap">
          {formatDate(getValue() as string)}
        </div>
      ),
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ getValue }) => <StatusBadge status={getValue() as IpoEntry["status"]} />,
    },
    {
      accessorKey: "listingGain",
      header: () => <span className="block text-right">Listing Gain</span>,
      cell: ({ row }) => <ListingGainCell gain={row.original.listingGain} />,
      sortingFn: (rowA, rowB) => {
        const a = rowA.original.listingGain ?? -Infinity;
        const b = rowB.original.listingGain ?? -Infinity;
        return a - b;
      },
    },
  ];
}

// ─── Summary stats ───────────────────────────────────────────────────────────

function IpoSummary({ entries }: { entries: IpoEntry[] }) {
  const listed = entries.filter((e) => e.status === "listed" && e.listingGain !== undefined);
  const avgGain = listed.length > 0
    ? listed.reduce((sum, e) => sum + (e.listingGain ?? 0), 0) / listed.length
    : 0;
  const positive = listed.filter((e) => (e.listingGain ?? 0) > 0).length;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <GlassCard className="p-3 gap-1">
        <div className="text-xs text-text-muted">Total IPOs</div>
        <div className="font-mono text-lg font-bold text-text-primary">{entries.length}</div>
      </GlassCard>
      <GlassCard className="p-3 gap-1">
        <div className="text-xs text-text-muted">Listed</div>
        <div className="font-mono text-lg font-bold text-text-primary">{listed.length}</div>
      </GlassCard>
      <GlassCard className="p-3 gap-1">
        <div className="text-xs text-text-muted">Avg Listing Gain</div>
        <div className={cn("font-mono text-lg font-bold", avgGain >= 0 ? "text-profit" : "text-loss")}>
          {avgGain >= 0 ? "+" : ""}{avgGain.toFixed(1)}%
        </div>
      </GlassCard>
      <GlassCard className="p-3 gap-1">
        <div className="text-xs text-text-muted">Positive Listing</div>
        <div className="font-mono text-lg font-bold text-profit">
          {positive}/{listed.length}
        </div>
      </GlassCard>
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export function IpoTab() {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "listingDate", desc: true },
  ]);

  const columns = useMemo(() => buildColumns(), []);

  const table = useReactTable({
    data: RECENT_IPOS,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="space-y-6">
      {/* Static data banner */}
      <div
        role="status"
        className="flex items-center gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-2.5"
      >
        <Info className="size-4 text-blue-400 shrink-0" aria-hidden="true" />
        <p className="text-xs text-blue-300">
          Static reference data — live IPO tracking with NSE integration coming in v0.3.0.
        </p>
      </div>

      {/* Header */}
      <div>
        <h3 className="font-heading font-semibold text-sm text-text-primary">IPO Tracker</h3>
        <p className="text-xs text-text-muted mt-0.5">
          {RECENT_IPOS.length} recent Indian IPOs — sorted by listing date.
        </p>
      </div>

      {/* Summary cards */}
      <IpoSummary entries={RECENT_IPOS} />

      {/* Sortable table */}
      <GlassCard className="p-0 overflow-hidden">
        <Table aria-label="Recent Indian IPOs — sortable by any column">
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id} className="border-border-default hover:bg-transparent">
                {hg.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <TableHead
                      key={header.id}
                      className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider cursor-pointer select-none"
                      onClick={header.column.getToggleSortingHandler()}
                      aria-sort={
                        sorted === "asc"
                          ? "ascending"
                          : sorted === "desc"
                            ? "descending"
                            : "none"
                      }
                    >
                      <span className="flex items-center gap-1">
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sorted === "asc" && " \u2191"}
                        {sorted === "desc" && " \u2193"}
                      </span>
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                className="border-border-default hover:bg-surface-card transition-colors"
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className="py-2 text-xs">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </GlassCard>

      <p className="text-xs text-text-muted">
        IPO data shown is historical reference data from NSE filings.
        Issue sizes are approximate. Listing gain is calculated as the percentage
        difference between issue price (upper band) and listing day closing price.
      </p>
    </div>
  );
}
