/**
 * StocksTab.tsx
 *
 * Real stock screener tab for the Invest route.
 * Replaces the FeatureLockCard placeholder from LockedTabs.tsx.
 *
 * Data flow:
 *   searchSymbol() → symbol search results (on demand)
 *   localStorage("flinttrade:stock-watchlist") → persisted symbol list
 *   getMultiQuotes() → TanStack Query (30s refetch) → live prices
 *
 * Design follows EtfTab.tsx:
 *   - TanStack Table for sortable rows
 *   - GlassCard for table container
 *   - Loading skeletons, error state with retry
 *   - formatINR / formatPercent from invest formatters
 *
 * Accessibility:
 *   - Search input: labelled with htmlFor
 *   - Table: aria-label, aria-sort on sortable columns
 *   - Loading skeleton: role="status" + aria-live
 *   - Error state: retry button with aria-label
 *   - Add/remove buttons: descriptive aria-label per row
 */

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import {
  AlertCircle,
  BarChart3,
  Plus,
  RefreshCw,
  Search,
  Star,
  StarOff,
  X,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { searchSymbol, getMultiQuotes } from "@/services/api";
import type { Quote } from "@/types/api";
import { classifySector } from "@/lib/sectors";
import { cn } from "@/lib/utils";
import { formatINR, formatPercent } from "../formatters";

// ─── Constants ────────────────────────────────────────────────────────────────

const WATCHLIST_KEY = "flinttrade:stock-watchlist";

// ─── Types ────────────────────────────────────────────────────────────────────

interface WatchlistEntry {
  symbol: string;
  exchange: string;
}

interface StockScreenerRow {
  symbol: string;
  exchange: string;
  ltp: number;
  changePct: number;
  change: number;
  volume: number;
  sector: string;
}

// ─── Watchlist persistence ────────────────────────────────────────────────────

function loadWatchlist(): WatchlistEntry[] {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is WatchlistEntry =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as Record<string, unknown>).symbol === "string" &&
        typeof (item as Record<string, unknown>).exchange === "string",
    );
  } catch {
    return [];
  }
}

function saveWatchlist(entries: WatchlistEntry[]): void {
  try {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(entries));
  } catch {
    // localStorage may be unavailable in some contexts — fail silently
  }
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

function useWatchlist() {
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>(loadWatchlist);

  const add = useCallback((entry: WatchlistEntry) => {
    setWatchlist((prev) => {
      if (prev.some((e) => e.symbol.toUpperCase() === entry.symbol.toUpperCase())) {
        return prev;
      }
      const next = [...prev, entry];
      saveWatchlist(next);
      return next;
    });
  }, []);

  const remove = useCallback((symbol: string) => {
    setWatchlist((prev) => {
      const next = prev.filter((e) => e.symbol.toUpperCase() !== symbol.toUpperCase());
      saveWatchlist(next);
      return next;
    });
  }, []);

  const has = useCallback(
    (symbol: string) =>
      watchlist.some((e) => e.symbol.toUpperCase() === symbol.toUpperCase()),
    [watchlist],
  );

  return { watchlist, add, remove, has };
}

function useStockQuotes(symbols: WatchlistEntry[]) {
  return useQuery<Quote[]>({
    queryKey: ["stock-watchlist-quotes", symbols.map((s) => s.symbol).join(",")],
    queryFn: () => getMultiQuotes(symbols),
    enabled: symbols.length > 0,
    refetchInterval: 30_000,
    retry: 1,
  });
}

function useSymbolSearch(query: string) {
  return useQuery<Array<{ symbol: string; exchange: string }>>({
    queryKey: ["symbol-search", query],
    queryFn: () => searchSymbol(query),
    enabled: query.trim().length >= 2,
    staleTime: 30_000,
    retry: 0,
  });
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function mergeWatchlistWithQuotes(
  watchlist: WatchlistEntry[],
  quotes: Quote[],
): StockScreenerRow[] {
  const quoteMap = new Map<string, Quote>(
    quotes.map((q) => [q.symbol.toUpperCase(), q]),
  );

  return watchlist.map((entry): StockScreenerRow => {
    const q = quoteMap.get(entry.symbol.toUpperCase());
    const ltp = q?.ltp ?? 0;
    const prevClose = q?.prev_close ?? q?.close ?? 0;
    const change = prevClose > 0 ? ltp - prevClose : (q?.change ?? 0);
    const changePct =
      prevClose > 0 ? (change / prevClose) * 100 : (q?.pct ?? 0);
    return {
      symbol: entry.symbol,
      exchange: entry.exchange,
      ltp,
      change,
      changePct,
      volume: q?.volume ?? 0,
      sector: classifySector(entry.symbol),
    };
  });
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ChangeCell({ change, pct }: { change: number; pct: number }) {
  const pos = change >= 0;
  return (
    <div className={cn("text-right tabular-nums", pos ? "text-profit" : "text-loss")}>
      <div className="font-mono text-xs font-semibold">{formatPercent(pct)}</div>
      <div className="font-mono text-xs opacity-75">{formatINR(change)}</div>
    </div>
  );
}

function RowSkeleton() {
  return (
    <TableRow className="border-border-default">
      {[120, 80, 90, 70, 70, 60].map((w, i) => (
        <TableCell key={i} className="py-2">
          <div
            className="animate-pulse h-3 rounded bg-surface-card"
            style={{ width: w }}
          />
        </TableCell>
      ))}
    </TableRow>
  );
}

// ─── Column definitions ───────────────────────────────────────────────────────

function buildColumns(
  onRemove: (s: string) => void,
): ColumnDef<StockScreenerRow>[] {
  return [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <div>
          <div className="font-mono text-xs font-bold text-text-primary">
            {row.original.symbol}
          </div>
          <div className="text-xs text-text-muted">{row.original.exchange}</div>
        </div>
      ),
    },
    {
      accessorKey: "sector",
      header: "Sector",
      cell: ({ getValue }) => (
        <Badge
          variant="outline"
          className="text-xs border-border-default text-text-muted font-normal"
        >
          {getValue() as string}
        </Badge>
      ),
    },
    {
      accessorKey: "ltp",
      header: () => <span className="block text-right">LTP</span>,
      cell: ({ getValue }) => {
        const v = getValue() as number;
        return (
          <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
            {v > 0 ? formatINR(v) : "—"}
          </div>
        );
      },
    },
    {
      accessorKey: "changePct",
      header: () => <span className="block text-right">Change</span>,
      cell: ({ row }) => (
        <ChangeCell change={row.original.change} pct={row.original.changePct} />
      ),
    },
    {
      accessorKey: "volume",
      header: () => <span className="block text-right">Volume</span>,
      cell: ({ getValue }) => {
        const v = getValue() as number;
        return (
          <div className="text-right font-mono tabular-nums text-xs text-text-muted">
            {v > 0 ? v.toLocaleString("en-IN") : "—"}
          </div>
        );
      },
    },
    {
      id: "actions",
      header: "",
      enableSorting: false,
      cell: ({ row }) => {
        const sym = row.original.symbol;
        return (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 text-text-muted hover:text-loss"
            onClick={() => onRemove(sym)}
            aria-label={`Remove ${sym} from watchlist`}
          >
            <X className="size-3" aria-hidden="true" />
          </Button>
        );
      },
    },
  ];
}

// ─── Search Panel ─────────────────────────────────────────────────────────────

interface SearchPanelProps {
  hasSymbol: (s: string) => boolean;
  onAdd: (entry: WatchlistEntry) => void;
}

function SearchPanel({ hasSymbol, onAdd }: SearchPanelProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const trimmedQuery = query.trim();
  const { data: results, isFetching } = useSymbolSearch(trimmedQuery);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const showDropdown =
    open && trimmedQuery.length >= 2 && (isFetching || (results && results.length > 0));

  return (
    <div className="relative" ref={panelRef}>
      <label htmlFor="stock-search" className="sr-only">
        Search for a stock symbol
      </label>
      <div className="relative">
        <Search
          className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3 text-text-muted pointer-events-none"
          aria-hidden="true"
        />
        <input
          id="stock-search"
          ref={inputRef}
          type="search"
          placeholder="Search symbol (e.g. RELIANCE, TCS…)"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          className={cn(
            "h-8 w-full rounded-md border border-border-default bg-surface-card pl-8 pr-3",
            "text-xs text-text-primary placeholder:text-text-muted",
            "focus:outline-none focus:ring-1 focus:ring-ring",
            "transition-colors",
          )}
          autoComplete="off"
        />
        {isFetching && (
          <RefreshCw
            className="absolute right-2.5 top-1/2 -translate-y-1/2 size-3 text-text-muted animate-spin"
            aria-hidden="true"
          />
        )}
      </div>

      {showDropdown && (
        <div
          className="absolute z-50 mt-1 w-full rounded-md border border-border-default bg-surface-card shadow-lg"
        >
          {results && results.length > 0 ? (
            <ul className="max-h-48 overflow-y-auto py-1">
              {results.slice(0, 15).map((r) => {
                const alreadyAdded = hasSymbol(r.symbol);
                return (
                  <li
                    key={`${r.symbol}-${r.exchange}`}
                  >
                    <button
                      type="button"
                      disabled={alreadyAdded}
                      onClick={() => {
                        if (!alreadyAdded) {
                          onAdd({ symbol: r.symbol, exchange: r.exchange });
                          setQuery("");
                          setOpen(false);
                          inputRef.current?.focus();
                        }
                      }}
                      className={cn(
                        "flex w-full items-center justify-between px-3 py-1.5 text-xs",
                        "hover:bg-surface-hover transition-colors",
                        alreadyAdded
                          ? "opacity-50 cursor-not-allowed"
                          : "cursor-pointer",
                      )}
                      aria-label={
                        alreadyAdded
                          ? `${r.symbol} already in watchlist`
                          : `Add ${r.symbol} (${r.exchange}) to watchlist`
                      }
                    >
                      <span className="flex items-center gap-2">
                        <span className="font-mono font-bold text-text-primary">
                          {r.symbol}
                        </span>
                        <span className="text-text-muted">{r.exchange}</span>
                      </span>
                      {alreadyAdded ? (
                        <Star className="size-3 text-profit" aria-hidden="true" />
                      ) : (
                        <Plus className="size-3 text-text-muted" aria-hidden="true" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            !isFetching && (
              <div className="px-3 py-2 text-xs text-text-muted">
                No results for &quot;{trimmedQuery}&quot;
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────

function EmptyWatchlist() {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3 text-text-muted">
      <Star className="size-8 text-text-disabled" aria-hidden="true" />
      <span className="text-sm font-medium text-text-secondary">
        Your watchlist is empty
      </span>
      <span className="text-xs text-text-muted max-w-xs text-center">
        Search for a symbol above and add it to see live prices here.
      </span>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function StocksTab() {
  const { watchlist, add, remove, has } = useWatchlist();

  const { data: quotes, isLoading, isError, refetch } = useStockQuotes(watchlist);

  const [sorting, setSorting] = useState<SortingState>([
    { id: "changePct", desc: true },
  ]);

  const columns = useMemo(() => buildColumns(remove), [remove]);

  const rows = useMemo<StockScreenerRow[]>(
    () =>
      quotes
        ? mergeWatchlistWithQuotes(watchlist, quotes)
        : watchlist.map((entry) => ({
            symbol: entry.symbol,
            exchange: entry.exchange,
            ltp: 0,
            change: 0,
            changePct: 0,
            volume: 0,
            sector: classifySector(entry.symbol),
          })),
    [quotes, watchlist],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Stock Screener
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Track individual stocks with live prices. Search and add to your
            watchlist.
          </p>
        </div>
        {watchlist.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void refetch()}
            className="text-xs text-text-muted h-6 px-2 gap-1"
            aria-label="Refresh stock quotes"
          >
            <RefreshCw className="size-3" aria-hidden="true" />
            Refresh
          </Button>
        )}
      </div>

      {/* Symbol search */}
      <SearchPanel hasSymbol={has} onAdd={add} />

      {/* Error state */}
      {isError && watchlist.length > 0 && (
        <div className="flex flex-col items-center justify-center h-32 gap-3 text-text-muted">
          <AlertCircle className="size-5 text-loss" aria-hidden="true" />
          <span className="text-sm">Failed to load quotes.</span>
          <span className="text-xs text-text-muted max-w-xs text-center">
            Check that OpenAlgo is running and the connection is configured in
            Settings.
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
            className="text-xs"
            aria-label="Retry loading stock quotes"
          >
            <RefreshCw className="size-3 mr-1" aria-hidden="true" />
            Retry
          </Button>
        </div>
      )}

      {/* Empty watchlist */}
      {watchlist.length === 0 && !isError && <EmptyWatchlist />}

      {/* sr-only live region for table loading state */}
      <div className="sr-only" role="status" aria-live="polite">
        {isLoading ? "Loading stock quotes" : "Stock quotes loaded"}
      </div>

      {/* Watchlist table */}
      {watchlist.length > 0 && !isError && (
        <GlassCard className="p-0 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 border-b border-border-default">
            <div className="flex items-center gap-2">
              <StarOff className="size-3 text-text-muted" aria-hidden="true" />
              <span className="text-xs font-medium text-text-secondary">
                My Watchlist
              </span>
              <Badge
                variant="outline"
                className="text-xs border-border-default text-text-muted h-4 px-1.5"
              >
                {watchlist.length}
              </Badge>
            </div>
            <span className="text-xs text-text-muted">
              Refreshes every 30s
            </span>
          </div>

          <Table aria-label="Stock watchlist — sortable by any column">
            <TableHeader>
              {table.getHeaderGroups().map((hg) => (
                <TableRow
                  key={hg.id}
                  className="border-border-default hover:bg-transparent"
                >
                  {hg.headers.map((header) => {
                    const sorted = header.column.getIsSorted();
                    const canSort = header.column.getCanSort();
                    return (
                      <TableHead
                        key={header.id}
                        className={cn(
                          "h-8 text-xxs font-medium text-text-muted uppercase tracking-wider",
                          canSort && "cursor-pointer select-none",
                        )}
                        onClick={
                          canSort
                            ? header.column.getToggleSortingHandler()
                            : undefined
                        }
                        aria-sort={
                          canSort
                            ? sorted === "asc"
                              ? "ascending"
                              : sorted === "desc"
                                ? "descending"
                                : "none"
                            : undefined
                        }
                      >
                        <span className="flex items-center gap-1">
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                          {sorted === "asc" && <span aria-hidden="true"> ↑</span>}
                          {sorted === "desc" && <span aria-hidden="true"> ↓</span>}
                        </span>
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {isLoading
                ? watchlist.map((e) => <RowSkeleton key={e.symbol} />)
                : table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className="border-border-default hover:bg-surface-card transition-colors"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id} className="py-2 text-xs">
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
              {!isLoading && rows.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="py-8 text-center"
                  >
                    <div className="flex flex-col items-center gap-2 text-text-muted">
                      <BarChart3 className="size-5 text-text-disabled" aria-hidden="true" />
                      <span className="text-xs">
                        Connect to OpenAlgo to see live prices.
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </GlassCard>
      )}

      <p className="text-xs text-text-muted">
        Price data sourced from OpenAlgo. LTP and change% reflect the current
        session. Watchlist is saved locally in your browser.
      </p>
    </div>
  );
}
