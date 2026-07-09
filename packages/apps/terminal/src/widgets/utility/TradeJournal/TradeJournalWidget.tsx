/**
 * TradeJournalWidget — Annotated trade journal for the FlintTrade terminal.
 *
 * Reads and writes the backend's SQLite + FTS5 annotated-journal store
 * (``/api/v1/journal/*``) entirely through TanStack Query — the repo's hard
 * rule that REST data flows through Query, never Jotai/Zustand. Features:
 *   - Searchable, filterable list of entries (full-text ``/search`` when the
 *     search box is non-empty, filtered ``/entries`` otherwise).
 *   - Per-row symbol, side, quantity, entry/exit price, P&L (coloured by sign),
 *     strategy, tags and a notes snippet.
 *   - Add / edit / delete entries (a dialog form for create and edit, a
 *     confirm dialog for delete) — every mutation invalidates the journal
 *     cache so the list and stats refresh.
 *   - A stats summary strip (win rate, total P&L, win/loss counts) from
 *     ``/stats``.
 *
 * The journal is the operator's own annotated data held on the backend, so it
 * is fetched regardless of broker connection. Loading / error / empty states
 * are rendered honestly — never fabricated rows.
 */

import { useCallback, useMemo, useState, memo } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  NotebookPen,
  Plus,
  Search,
  RefreshCw,
  Loader2,
  AlertCircle,
  Pencil,
  Trash2,
  Download,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import { queryKeys } from "@/services/queryKeys";
import {
  createJournalEntry,
  deleteJournalEntry,
  fetchJournalCsv,
  getJournalStats,
  listJournalEntries,
  searchJournalEntries,
  updateJournalEntry,
} from "@/services/ftApi.journal";
import type {
  JournalEntry,
  JournalEntryInput,
  JournalSide,
} from "@/services/ftApi.journal";

// ---------------------------------------------------------------------------
// Constants & formatters
// ---------------------------------------------------------------------------

const LIST_LIMIT = 200;
const QUALITY_NONE = "none";
const QUALITY_OPTIONS = ["1", "2", "3", "4", "5"] as const;

type SideFilter = "all" | JournalSide;

const NUM_FMT = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const QTY_FMT = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function fmtNum(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return NUM_FMT.format(value);
}

function fmtQty(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return QTY_FMT.format(value);
}

/** Signed rupee P&L, e.g. ``+₹1,250.00`` / ``−₹800.00``. */
function fmtPnl(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}₹${NUM_FMT.format(Math.abs(value))}`;
}

/**
 * Format the win rate. The backend returns it as a percentage already scaled to
 * 0–100 (`win_count / closed * 100`), so render it directly — scaling a genuine
 * low rate (e.g. 1%) would wrongly inflate it to 100%.
 */
function fmtWinRate(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(1)}%`;
}

function pnlColour(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value === 0) return "text-text-secondary";
  return value > 0 ? "text-profit" : "text-loss";
}

function parseTags(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}

// ---------------------------------------------------------------------------
// Entry-form state
// ---------------------------------------------------------------------------

interface FormState {
  symbol: string;
  exchange: string;
  side: JournalSide;
  quantity: string;
  entry_price: string;
  exit_price: string;
  strategy: string;
  tags: string;
  setup_quality: string;
  execution_quality: string;
  notes: string;
}

function emptyForm(): FormState {
  return {
    symbol: "",
    exchange: "NSE",
    side: "BUY",
    quantity: "",
    entry_price: "",
    exit_price: "",
    strategy: "",
    tags: "",
    setup_quality: QUALITY_NONE,
    execution_quality: QUALITY_NONE,
    notes: "",
  };
}

function formFromEntry(entry: JournalEntry): FormState {
  return {
    symbol: entry.symbol,
    exchange: entry.exchange,
    side: entry.side,
    quantity: String(entry.quantity),
    entry_price: String(entry.entry_price),
    exit_price: entry.exit_price != null ? String(entry.exit_price) : "",
    strategy: entry.strategy ?? "",
    tags: entry.tags.join(", "),
    setup_quality: entry.setup_quality != null ? String(entry.setup_quality) : QUALITY_NONE,
    execution_quality:
      entry.execution_quality != null ? String(entry.execution_quality) : QUALITY_NONE,
    notes: entry.notes ?? "",
  };
}

function formToInput(form: FormState): JournalEntryInput {
  return {
    symbol: form.symbol.trim().toUpperCase(),
    exchange: form.exchange.trim().toUpperCase(),
    side: form.side,
    quantity: Number(form.quantity),
    entry_price: Number(form.entry_price),
    exit_price: form.exit_price.trim() ? Number(form.exit_price) : null,
    strategy: form.strategy.trim() ? form.strategy.trim() : null,
    tags: parseTags(form.tags),
    notes: form.notes.trim() ? form.notes.trim() : null,
    setup_quality: form.setup_quality === QUALITY_NONE ? null : Number(form.setup_quality),
    execution_quality:
      form.execution_quality === QUALITY_NONE ? null : Number(form.execution_quality),
  };
}

function isFormValid(form: FormState): boolean {
  const qty = Number(form.quantity);
  const entry = Number(form.entry_price);
  const exitOk = !form.exit_price.trim() || Number.isFinite(Number(form.exit_price));
  return (
    form.symbol.trim().length > 0 &&
    form.exchange.trim().length > 0 &&
    Number.isFinite(qty) &&
    qty > 0 &&
    Number.isFinite(entry) &&
    entry > 0 &&
    exitOk
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

interface JournalRowProps {
  entry: JournalEntry;
  onEdit: (entry: JournalEntry) => void;
  onDelete: (entry: JournalEntry) => void;
}

function JournalRow({ entry, onEdit, onDelete }: JournalRowProps) {
  const sideClass =
    entry.side === "BUY"
      ? "bg-profit/10 text-profit border-profit/20"
      : "bg-loss/10 text-loss border-loss/20";

  return (
    <tr className="border-b border-border-subtle hover:bg-surface-hover/40 transition-colors align-top">
      <td className="px-2 py-1.5 whitespace-nowrap">
        <span className="text-xs font-medium text-text-primary">{entry.symbol}</span>
        <span className="ml-1 text-xxs text-text-muted">{entry.exchange}</span>
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        <span className={cn("text-xxs px-1.5 py-px rounded border font-mono", sideClass)}>
          {entry.side}
        </span>
      </td>
      <td className="px-2 py-1.5 text-right whitespace-nowrap">
        <span className="text-xs font-mono tabular-nums text-text-secondary">
          {fmtQty(entry.quantity)}
        </span>
      </td>
      <td className="px-2 py-1.5 text-right whitespace-nowrap">
        <span className="text-xs font-mono tabular-nums text-text-secondary">
          {fmtNum(entry.entry_price)}
        </span>
      </td>
      <td className="px-2 py-1.5 text-right whitespace-nowrap">
        <span className="text-xs font-mono tabular-nums text-text-secondary">
          {entry.exit_price != null ? fmtNum(entry.exit_price) : "—"}
        </span>
      </td>
      <td className="px-2 py-1.5 text-right whitespace-nowrap">
        <span className={cn("text-xs font-mono tabular-nums font-medium", pnlColour(entry.pnl))}>
          {fmtPnl(entry.pnl)}
        </span>
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        <span className="text-xs text-text-secondary">{entry.strategy ?? "—"}</span>
      </td>
      <td className="px-2 py-1.5 max-w-[160px]">
        <div className="flex flex-wrap gap-1">
          {entry.tags.length === 0 ? (
            <span className="text-xxs text-text-muted">—</span>
          ) : (
            entry.tags.map((tag) => (
              <span
                key={tag}
                className="text-xxs px-1 py-px rounded bg-surface-hover border border-border-subtle text-text-muted"
              >
                {tag}
              </span>
            ))
          )}
        </div>
      </td>
      <td className="px-2 py-1.5 max-w-[220px]">
        <span className="text-xs text-text-muted line-clamp-2" title={entry.notes ?? undefined}>
          {entry.notes ?? "—"}
        </span>
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={() => onEdit(entry)}
            aria-label={`Edit ${entry.symbol} entry`}
            className="text-text-muted hover:text-text-primary"
          >
            <Pencil size={12} aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={() => onDelete(entry)}
            aria-label={`Delete ${entry.symbol} entry`}
            className="text-text-muted hover:text-loss"
          >
            <Trash2 size={12} aria-hidden="true" />
          </Button>
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function TradeJournalWidget() {
  const queryClient = useQueryClient();

  // Filters / search
  const [search, setSearch] = useState("");
  const [sideFilter, setSideFilter] = useState<SideFilter>("all");
  const [strategyFilter, setStrategyFilter] = useState("");

  // Dialog state
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [deleteTarget, setDeleteTarget] = useState<JournalEntry | null>(null);

  const trimmedSearch = search.trim();
  const isSearching = trimmedSearch.length > 0;

  // -- Queries --------------------------------------------------------------
  const listQuery = useQuery({
    queryKey: queryKeys.journal.list(trimmedSearch, sideFilter, strategyFilter.trim()),
    queryFn: () =>
      isSearching
        ? searchJournalEntries({ q: trimmedSearch, limit: LIST_LIMIT })
        : listJournalEntries({
            side: sideFilter === "all" ? undefined : sideFilter,
            strategy: strategyFilter.trim() || undefined,
            limit: LIST_LIMIT,
          }),
    staleTime: 15_000,
  });

  const statsQuery = useQuery({
    queryKey: queryKeys.journal.stats(),
    queryFn: () => getJournalStats(),
    staleTime: 30_000,
  });

  const entries = listQuery.data?.entries ?? [];
  const stats = statsQuery.data;

  // -- Mutations ------------------------------------------------------------
  const invalidateJournal = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.journal.all });
  }, [queryClient]);

  const closeForm = useCallback(() => {
    setFormOpen(false);
    setEditingId(null);
    setForm(emptyForm());
  }, []);

  const createMutation = useMutation({
    mutationFn: (input: JournalEntryInput) => createJournalEntry(input),
    onSuccess: () => {
      invalidateJournal();
      closeForm();
    },
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id: string; input: JournalEntryInput }) =>
      updateJournalEntry(vars.id, vars.input),
    onSuccess: () => {
      invalidateJournal();
      closeForm();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteJournalEntry(id),
    onSuccess: () => {
      invalidateJournal();
      setDeleteTarget(null);
    },
  });

  const mutationError =
    (createMutation.error as Error | null)?.message ??
    (updateMutation.error as Error | null)?.message ??
    (deleteMutation.error as Error | null)?.message ??
    null;
  const isSaving = createMutation.isPending || updateMutation.isPending;

  // -- Handlers -------------------------------------------------------------
  const openCreate = useCallback(() => {
    setEditingId(null);
    setForm(emptyForm());
    setFormOpen(true);
  }, []);

  const openEdit = useCallback((entry: JournalEntry) => {
    setEditingId(entry.id);
    setForm(formFromEntry(entry));
    setFormOpen(true);
  }, []);

  const handleFormOpenChange = useCallback(
    (open: boolean) => {
      if (!open) closeForm();
      else setFormOpen(true);
    },
    [closeForm],
  );

  const setField = useCallback(<K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!isFormValid(form)) return;
      const input = formToInput(form);
      if (editingId) {
        updateMutation.mutate({ id: editingId, input });
      } else {
        createMutation.mutate(input);
      }
    },
    [form, editingId, updateMutation, createMutation],
  );

  const handleExport = useCallback(async () => {
    try {
      const blob = await fetchJournalCsv();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `flinttrade-journal-${new Date().toISOString().slice(0, 10)}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      // Surface nothing intrusive — the export button is best-effort; the list
      // remains the source of truth. A failed export leaves the UI unchanged.
    }
  }, []);

  const clearFilters = useCallback(() => {
    setSearch("");
    setSideFilter("all");
    setStrategyFilter("");
  }, []);

  const hasFilters = isSearching || sideFilter !== "all" || strategyFilter.trim().length > 0;
  const formValid = useMemo(() => isFormValid(form), [form]);

  // -----------------------------------------------------------------------
  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <NotebookPen size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Trade Journal</span>
        <div className="flex-1" />
        <Button
          variant="outline"
          size="xs"
          onClick={() => void handleExport()}
          className="text-text-muted border-border-subtle hover:text-text-primary"
          aria-label="Export journal to CSV"
        >
          <Download size={10} aria-hidden="true" />
          CSV
        </Button>
        <Button
          variant="ghost"
          size="icon-xs"
          onClick={() => void listQuery.refetch()}
          disabled={listQuery.isFetching}
          className="text-text-muted hover:text-text-primary disabled:opacity-40"
          aria-label="Refresh journal"
        >
          <RefreshCw
            size={11}
            className={listQuery.isFetching ? "animate-spin" : ""}
            aria-hidden="true"
          />
        </Button>
        <Button variant="default" size="xs" onClick={openCreate} aria-label="Add journal entry">
          <Plus size={11} aria-hidden="true" />
          Add entry
        </Button>
      </div>

      {/* Stats strip */}
      <div className="flex-none flex items-center gap-4 px-3 py-1.5 border-b border-border-subtle bg-surface-elevated overflow-x-auto">
        <Stat label="Entries" value={stats ? String(stats.total_entries) : "—"} />
        <Stat label="Closed" value={stats ? String(stats.closed_entries) : "—"} />
        <Stat label="Win rate" value={stats ? fmtWinRate(stats.win_rate) : "—"} />
        <Stat
          label="W / L"
          value={stats ? `${stats.win_count} / ${stats.loss_count}` : "—"}
        />
        <Stat
          label="Total P&L"
          value={stats ? fmtPnl(stats.total_pnl) : "—"}
          valueClass={stats ? pnlColour(stats.total_pnl) : undefined}
        />
      </div>

      {/* Filters */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 border-b border-border-subtle bg-surface-card">
        <div className="relative flex-1 min-w-[140px] max-w-[280px]">
          <Search
            size={12}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search notes, tags, symbol…"
            className="h-6 pl-7 text-xxs"
            aria-label="Search journal"
          />
        </div>
        <Select
          value={sideFilter}
          onValueChange={(v) => setSideFilter(v as SideFilter)}
          disabled={isSearching}
        >
          <SelectTrigger className="h-6 w-24 text-xxs" aria-label="Filter by side">
            <SelectValue placeholder="Side" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">All sides</SelectItem>
            <SelectItem value="BUY" className="text-xs">Buy</SelectItem>
            <SelectItem value="SELL" className="text-xs">Sell</SelectItem>
          </SelectContent>
        </Select>
        <Input
          value={strategyFilter}
          onChange={(e) => setStrategyFilter(e.target.value)}
          placeholder="Strategy"
          className="h-6 w-32 text-xxs"
          aria-label="Filter by strategy"
          disabled={isSearching}
        />
        {hasFilters && (
          <Button
            variant="ghost"
            size="xs"
            className="text-text-muted"
            onClick={clearFilters}
            aria-label="Clear filters"
          >
            <X size={10} aria-hidden="true" />
            Clear
          </Button>
        )}
        <span className="ml-auto text-xxs text-text-muted tabular-nums whitespace-nowrap">
          {entries.length} shown
        </span>
      </div>

      {/* Mutation error banner */}
      {mutationError && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} aria-hidden="true" />
          <span>{mutationError}</span>
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-auto">
        {listQuery.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-text-muted text-sm">
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            Loading journal…
          </div>
        ) : listQuery.isError ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-loss text-sm">
            <AlertCircle size={16} aria-hidden="true" />
            <span>{(listQuery.error as Error | null)?.message ?? "Failed to load journal"}</span>
            <Button variant="outline" size="sm" onClick={() => void listQuery.refetch()}>
              Retry
            </Button>
          </div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-text-muted text-sm">
            <NotebookPen size={18} aria-hidden="true" />
            <span>
              {hasFilters
                ? "No entries match the current search or filters."
                : "No journal entries yet."}
            </span>
            {!hasFilters && (
              <Button variant="outline" size="sm" onClick={openCreate}>
                <Plus size={12} aria-hidden="true" />
                Add your first entry
              </Button>
            )}
          </div>
        ) : (
          <table className="w-full border-collapse" aria-label="Trade journal entries">
            <thead>
              <tr className="border-b border-border-default sticky top-0 bg-surface-card z-10">
                <Th>Scrip</Th>
                <Th>Side</Th>
                <Th align="right">Qty</Th>
                <Th align="right">Entry</Th>
                <Th align="right">Exit</Th>
                <Th align="right">P&amp;L</Th>
                <Th>Strategy</Th>
                <Th>Tags</Th>
                <Th>Notes</Th>
                <Th>{""}</Th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <JournalRow
                  key={entry.id}
                  entry={entry}
                  onEdit={openEdit}
                  onDelete={setDeleteTarget}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Add / edit dialog */}
      <Dialog open={formOpen} onOpenChange={handleFormOpenChange}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingId ? "Edit journal entry" : "Add journal entry"}</DialogTitle>
            <DialogDescription>
              Record the trade with your annotations. P&amp;L is computed on the backend when an
              exit price is present.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3">
              <Field id="journal-symbol" label="Scrip (symbol)">
                <Input
                  id="journal-symbol"
                  value={form.symbol}
                  onChange={(e) => setField("symbol", e.target.value)}
                  placeholder="NIFTY"
                  aria-label="Symbol"
                  required
                />
              </Field>
              <Field id="journal-exchange" label="Exchange">
                <Input
                  id="journal-exchange"
                  value={form.exchange}
                  onChange={(e) => setField("exchange", e.target.value)}
                  placeholder="NSE"
                  aria-label="Exchange"
                  required
                />
              </Field>
              <Field id="journal-side" label="Side">
                <Select value={form.side} onValueChange={(v) => setField("side", v as JournalSide)}>
                  <SelectTrigger id="journal-side" aria-label="Side">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="BUY">Buy</SelectItem>
                    <SelectItem value="SELL">Sell</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field id="journal-qty" label="Quantity">
                <Input
                  id="journal-qty"
                  type="number"
                  inputMode="numeric"
                  min="0"
                  value={form.quantity}
                  onChange={(e) => setField("quantity", e.target.value)}
                  placeholder="50"
                  aria-label="Quantity"
                  required
                />
              </Field>
              <Field id="journal-entry" label="Entry price">
                <Input
                  id="journal-entry"
                  type="number"
                  inputMode="decimal"
                  step="0.05"
                  min="0"
                  value={form.entry_price}
                  onChange={(e) => setField("entry_price", e.target.value)}
                  placeholder="0.00"
                  aria-label="Entry price"
                  required
                />
              </Field>
              <Field id="journal-exit" label="Exit price (optional)">
                <Input
                  id="journal-exit"
                  type="number"
                  inputMode="decimal"
                  step="0.05"
                  min="0"
                  value={form.exit_price}
                  onChange={(e) => setField("exit_price", e.target.value)}
                  placeholder="0.00"
                  aria-label="Exit price"
                />
              </Field>
              <Field id="journal-strategy" label="Strategy (optional)">
                <Input
                  id="journal-strategy"
                  value={form.strategy}
                  onChange={(e) => setField("strategy", e.target.value)}
                  placeholder="Breakout"
                  aria-label="Strategy"
                />
              </Field>
              <Field id="journal-tags" label="Tags (comma-separated)">
                <Input
                  id="journal-tags"
                  value={form.tags}
                  onChange={(e) => setField("tags", e.target.value)}
                  placeholder="momentum, gap-up"
                  aria-label="Tags"
                />
              </Field>
              <Field id="journal-setup" label="Setup quality (1–5)">
                <Select
                  value={form.setup_quality}
                  onValueChange={(v) => setField("setup_quality", v)}
                >
                  <SelectTrigger id="journal-setup" aria-label="Setup quality">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={QUALITY_NONE}>—</SelectItem>
                    {QUALITY_OPTIONS.map((q) => (
                      <SelectItem key={q} value={q}>
                        {q}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field id="journal-exec" label="Execution quality (1–5)">
                <Select
                  value={form.execution_quality}
                  onValueChange={(v) => setField("execution_quality", v)}
                >
                  <SelectTrigger id="journal-exec" aria-label="Execution quality">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={QUALITY_NONE}>—</SelectItem>
                    {QUALITY_OPTIONS.map((q) => (
                      <SelectItem key={q} value={q}>
                        {q}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
            <Field id="journal-notes" label="Notes (optional)">
              <Textarea
                id="journal-notes"
                value={form.notes}
                onChange={(e) => setField("notes", e.target.value)}
                placeholder="What was the thesis? How did the execution feel?"
                aria-label="Notes"
                rows={3}
              />
            </Field>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={closeForm} disabled={isSaving}>
                Cancel
              </Button>
              <Button type="submit" disabled={!formValid || isSaving}>
                {isSaving ? (
                  <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                ) : null}
                {editingId ? "Save changes" : "Save entry"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete confirm */}
      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this journal entry?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget
                ? `The ${deleteTarget.side} ${deleteTarget.symbol} entry will be permanently removed. This cannot be undone.`
                : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (deleteTarget) deleteMutation.mutate(deleteTarget.id);
              }}
              disabled={deleteMutation.isPending}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small presentational helpers
// ---------------------------------------------------------------------------

function Stat({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex flex-col leading-tight whitespace-nowrap">
      <span className="text-xxs uppercase tracking-wide text-text-muted">{label}</span>
      <span className={cn("text-xs font-medium tabular-nums text-text-primary", valueClass)}>
        {value}
      </span>
    </div>
  );
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th
      className={cn(
        "px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted",
        align === "right" ? "text-right" : "text-left",
      )}
    >
      {children}
    </th>
  );
}

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id} className="text-xxs text-text-secondary">
        {label}
      </Label>
      {children}
    </div>
  );
}

export default memo(TradeJournalWidget);
