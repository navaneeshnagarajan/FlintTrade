import { useState, useMemo, useRef, useCallback, useEffect } from "react";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { safeParse } from "@/lib/safeParse";
import {
  Search,
  BookOpen,
  AlertCircle,
  RefreshCw,
  Camera,
  Eye,
  X,
} from "lucide-react";
import { formatCurrencyCompact } from "@/lib/formatters";
import { type TradeAnalytics } from "@/lib/journalAnalytics";
import { type JournalTrade } from "@/services/ftApi";
import {
  addJournalScreenshot,
  deleteJournalScreenshot,
  listJournalScreenshots,
  type JournalScreenshot,
} from "@/services/ftApi.journal";
import { useModeStore } from "@/stores/modeStore";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SummaryCards } from "./SummaryCards";
import { SkeletonRows } from "./StatCard";
import { formatDate, formatTime, formatPrice, pnlColor } from "./utils";

// ---------------------------------------------------------------------------
// Screenshot keys + legacy localStorage import
// ---------------------------------------------------------------------------

/** Legacy localStorage map key from the pre-backend era (import source only). */
const SCREENSHOTS_KEY = "flinttrade_journal_screenshots";

/** Max file size: 2 MiB (matches the backend's decoded-size cap). */
const MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024;

/**
 * Stable screenshot key for a trade row — independent of filtering. The old
 * key embedded the row's index in the *filtered* array, so a search re-pointed
 * every screenshot at the wrong row.
 */
function stableTradeKey(trade: JournalTrade): string {
  return `${trade.timestamp}|${trade.symbol}|${trade.orderid ?? "na"}`;
}

/**
 * Legacy key format (``timestamp-symbol-idx``, idx = position in the filtered
 * array) — imported keys are opaque strings, so rows also look up this shape
 * to keep matching where they matched before the migration.
 */
function legacyTradeKey(trade: JournalTrade, idx: number): string {
  return `${trade.timestamp}-${trade.symbol}-${idx}`;
}

/**
 * One-time import of the legacy localStorage screenshot map to the backend.
 *
 * Each entry is POSTed with its old key verbatim as ``trade_key``. The
 * localStorage key is removed only after EVERY entry succeeded — the backend
 * dedupes on ``(trade_key, content_sha256)``, so a partial import retried on
 * the next mount is safe. Returns true when anything was uploaded (the caller
 * invalidates the screenshots query).
 */
async function importLegacyScreenshots(): Promise<boolean> {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(SCREENSHOTS_KEY);
  } catch {
    return false;
  }
  if (!raw) return false;
  const map = safeParse(raw, z.record(z.string(), z.string()));
  if (!map) return false;

  let allSucceeded = true;
  let anySucceeded = false;
  for (const [tradeKey, dataUrl] of Object.entries(map)) {
    try {
      await addJournalScreenshot(tradeKey, dataUrl);
      anySucceeded = true;
    } catch {
      allSucceeded = false;
    }
  }
  if (allSucceeded) {
    try {
      localStorage.removeItem(SCREENSHOTS_KEY);
    } catch {
      // Removal failure is harmless — dedupe makes a re-import a no-op.
    }
  }
  return anySucceeded;
}

// ---------------------------------------------------------------------------
// Screenshot cell component
// ---------------------------------------------------------------------------

interface ScreenshotCellProps {
  shot: JournalScreenshot | undefined;
  /** True in Explore mode — attaching to fabricated sample rows is blocked. */
  attachDisabled: boolean;
  onAttach: (dataUrl: string) => void;
  onView: (shot: JournalScreenshot) => void;
}

function ScreenshotCell({ shot, attachDisabled, onAttach, onView }: ScreenshotCellProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_FILE_SIZE_BYTES) {
      alert("Screenshot must be under 2 MB.");
      return;
    }
    if (!file.type.startsWith("image/")) {
      alert("Only image files are supported.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        onAttach(reader.result);
      }
    };
    reader.readAsDataURL(file);
    // Reset input so the same file can be re-attached
    e.target.value = "";
  }, [onAttach]);

  if (shot) {
    return (
      <Button
        variant="ghost"
        size="icon"
        onClick={() => onView(shot)}
        className="flex items-center justify-center w-10 h-7 p-0 rounded overflow-hidden border border-border-default hover:border-accent transition-colors group"
        aria-label="View screenshot"
        title="Click to view screenshot"
      >
        <img
          src={shot.data_url}
          alt="Trade screenshot thumbnail"
          className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity"
        />
      </Button>
    );
  }

  return (
    <>
      <Input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleFile}
        aria-label="Attach screenshot"
      />
      <Button
        variant="ghost"
        size="icon"
        disabled={attachDisabled}
        onClick={() => inputRef.current?.click()}
        className="flex items-center justify-center w-8 h-7 p-0 rounded border border-dashed border-border-default text-text-disabled hover:text-text-muted hover:border-border-hover transition-colors"
        aria-label="Attach screenshot"
        title={
          attachDisabled
            ? "Sample data — attaching is disabled in Explore mode"
            : "Attach screenshot"
        }
      >
        <Camera size={11} />
      </Button>
    </>
  );
}

export function TradeLogTab({
  trades,
  analytics,
  isLoading,
  isError,
  onRetry,
}: {
  trades: JournalTrade[];
  analytics: TradeAnalytics;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  const isExploreMode = useModeStore((s) => s.mode === "explore");
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [filterAction, setFilterAction] = useState<"ALL" | "BUY" | "SELL">("ALL");

  // Screenshot state — served by the backend journal store.
  const screenshotsQuery = useQuery({
    queryKey: ["journalScreenshots"],
    queryFn: listJournalScreenshots,
    enabled: !isExploreMode,
  });

  const screenshotsByKey = useMemo(() => {
    const map: Record<string, JournalScreenshot> = {};
    for (const shot of screenshotsQuery.data ?? []) {
      if (!(shot.trade_key in map)) map[shot.trade_key] = shot;
    }
    return map;
  }, [screenshotsQuery.data]);

  const [viewingScreenshot, setViewingScreenshot] = useState<{
    screenshot: JournalScreenshot;
    symbol: string;
  } | null>(null);

  const attachMutation = useMutation({
    mutationFn: ({ tradeKey, dataUrl }: { tradeKey: string; dataUrl: string }) =>
      addJournalScreenshot(tradeKey, dataUrl),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["journalScreenshots"] });
    },
    onError: () => {
      alert("Screenshot not saved — backend unreachable.");
    },
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => deleteJournalScreenshot(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["journalScreenshots"] });
      setViewingScreenshot(null);
    },
    onError: () => {
      alert("Screenshot not removed — backend unreachable.");
    },
  });

  // One-time legacy import (skipped in Explore mode; runs once on the first
  // non-Explore render).
  const importAttemptedRef = useRef(false);
  useEffect(() => {
    if (isExploreMode || importAttemptedRef.current) return;
    importAttemptedRef.current = true;
    void importLegacyScreenshots().then((imported) => {
      if (imported) {
        void queryClient.invalidateQueries({ queryKey: ["journalScreenshots"] });
      }
    });
  }, [isExploreMode, queryClient]);

  // Sort newest first
  const sorted = useMemo(
    () =>
      [...trades].sort(
        (a, b) =>
          new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
      ),
    [trades],
  );

  const filtered = useMemo(() => {
    return sorted.filter((t) => {
      const matchSearch =
        search === "" || t.symbol.toLowerCase().includes(search.toLowerCase());
      const matchAction =
        filterAction === "ALL" || t.action === filterAction;
      return matchSearch && matchAction;
    });
  }, [sorted, search, filterAction]);

  return (
    <div className="flex flex-col h-full gap-2">
      {/* Screenshot viewer dialog */}
      <Dialog open={viewingScreenshot !== null} onOpenChange={(open) => { if (!open) setViewingScreenshot(null); }}>
        <DialogContent className="max-w-2xl bg-surface-card border-border-default">
          <DialogHeader>
            <DialogTitle className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <Eye size={14} />
              Trade Screenshot
              {viewingScreenshot && (
                <span className="text-text-muted font-mono text-xs font-normal ml-1">
                  {viewingScreenshot.symbol}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          {viewingScreenshot && (
            <div className="relative">
              <img
                src={viewingScreenshot.screenshot.data_url}
                alt="Trade screenshot"
                className="w-full rounded border border-border-default object-contain max-h-[60vh]"
              />
              <Button
                variant="ghost"
                size="sm"
                disabled={removeMutation.isPending}
                onClick={() => removeMutation.mutate(viewingScreenshot.screenshot.id)}
                className="absolute top-2 right-2 flex items-center gap-1 px-2 py-1 h-auto rounded bg-loss/80 text-white text-xs hover:bg-loss transition-colors"
                aria-label="Remove screenshot"
              >
                <X size={11} />
                Remove
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Summary cards */}
      {!isLoading && !isError && trades.length > 0 && (
        <SummaryCards analytics={analytics} />
      )}

      {/* Filters */}
      <div className="flex items-center gap-2 px-3 shrink-0">
        <div className="relative flex-1 max-w-52">
          <Search
            size={13}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <Input
            className="pl-7 h-7 text-xs bg-surface-base border-border-default text-text-primary placeholder:text-text-muted"
            placeholder="Search symbol..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-1">
          {(["ALL", "BUY", "SELL"] as const).map((v) => (
            <Button
              key={v}
              variant="ghost"
              size="sm"
              className={`h-7 px-2 text-xs ${
                filterAction === v
                  ? "bg-surface-elevated text-text-primary"
                  : "text-text-muted hover:text-text-primary"
              }`}
              onClick={() => setFilterAction(v)}
            >
              {v}
            </Button>
          ))}
        </div>
        {!isLoading && !isError && (
          <span className="text-xs text-text-muted ml-auto">
            {filtered.length} trades
          </span>
        )}
      </div>

      {/* Table */}
      <ScrollArea className="flex-1 px-3 pb-2">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Date / Time
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Symbol
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Exch
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Side
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                Qty
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                Entry
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                Exit
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                P&L
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal text-right">
                Fees
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal">
                Strategy
              </TableHead>
              <TableHead className="text-xs text-text-muted h-7 font-normal w-12">
                <span className="flex items-center gap-1">
                  <Camera size={10} />
                  Shot
                </span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && <SkeletonRows count={8} />}

            {isError && (
              <TableRow>
                <TableCell
                  colSpan={11}
                  className="text-center py-8 text-text-muted"
                >
                  <div className="flex flex-col items-center gap-2">
                    <AlertCircle size={20} className="text-loss" />
                    <span className="text-xs">Failed to load trade journal</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-xs h-6 text-text-muted hover:text-text-primary"
                      onClick={onRetry}
                    >
                      <RefreshCw size={11} className="mr-1" />
                      Retry
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            )}

            {!isLoading && !isError && filtered.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={11}
                  className="text-center py-8 text-text-muted"
                >
                  <div className="flex flex-col items-center gap-2">
                    <BookOpen size={24} />
                    <span className="text-xs">
                      No trades found for this period
                    </span>
                  </div>
                </TableCell>
              </TableRow>
            )}

            {!isLoading &&
              !isError &&
              filtered.map((trade, idx) => {
                const stableKey = stableTradeKey(trade);
                const shot =
                  screenshotsByKey[stableKey] ??
                  screenshotsByKey[legacyTradeKey(trade, idx)];
                return (
                <TableRow
                  key={`${stableKey}|${idx}`}
                  className="border-border-subtle hover:bg-surface-card"
                >
                  <TableCell className="py-1 text-xs text-text-secondary whitespace-nowrap">
                    <span>{formatDate(trade.timestamp)}</span>
                    <span className="ml-1 text-text-muted">
                      {formatTime(trade.timestamp)}
                    </span>
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-primary font-medium">
                    {trade.symbol}
                  </TableCell>
                  <TableCell className="py-1 text-xs text-text-muted">
                    {trade.exchange}
                  </TableCell>
                  <TableCell className="py-1">
                    <Badge
                      variant="outline"
                      className={`text-xxs px-1.5 py-0 border-0 font-medium ${
                        trade.action === "BUY"
                          ? "bg-bullish-bg text-profit"
                          : "bg-bearish-bg text-loss"
                      }`}
                    >
                      {trade.action}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-secondary text-right">
                    {trade.quantity}
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-primary text-right">
                    {formatPrice(trade.entry_price)}
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-primary text-right">
                    {trade.exit_price > 0 ? formatPrice(trade.exit_price) : "-"}
                  </TableCell>
                  <TableCell
                    className={`py-1 text-xs font-mono text-right font-medium ${pnlColor(trade.pnl)}`}
                  >
                    {typeof trade.pnl === "number" && trade.pnl !== 0
                      ? formatCurrencyCompact(trade.pnl)
                      : "-"}
                  </TableCell>
                  <TableCell className="py-1 text-xs font-mono text-text-muted text-right">
                    {trade.fees > 0 ? formatPrice(trade.fees) : "-"}
                  </TableCell>
                  <TableCell className="py-1 text-xs text-text-muted max-w-24 truncate">
                    {trade.strategy || "-"}
                  </TableCell>
                  <TableCell className="py-1">
                    <ScreenshotCell
                      shot={shot}
                      attachDisabled={isExploreMode}
                      onAttach={(dataUrl) =>
                        attachMutation.mutate({ tradeKey: stableKey, dataUrl })
                      }
                      onView={(s) =>
                        setViewingScreenshot({ screenshot: s, symbol: trade.symbol })
                      }
                    />
                  </TableCell>
                </TableRow>
                );
              })}
          </TableBody>
        </Table>
      </ScrollArea>
    </div>
  );
}
