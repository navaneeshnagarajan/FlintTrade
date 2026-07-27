/**
 * WatchlistWidget — multi-tab production watchlist for FlintTrade terminal.
 *
 * Features:
 *   - Up to 5 watchlist tabs, each with its own symbol list
 *   - Tab bar: compact pills, active tab highlighted with accent colour
 *   - "+" button to create a new tab
 *   - Right-click tab to Rename, Duplicate, or Delete
 *   - Persisted to localStorage key `flinttrade:watchlists` (all tabs)
 *   - Backward-compatible: migrates legacy `flinttrade:watchlist` key
 *   - Batch quote polling: 5s market hours, 60s off-hours
 *   - Debounced symbol search (300ms) with dropdown autocomplete
 *   - Per-row sparkline built from last 20 LTP samples
 *   - Right-click context menu on symbol to remove
 *   - Click broadcasts { symbol, exchange } on the widget's FDC3 user
 *     channel (red by default; `channel: "none"` broadcasts nowhere)
 *   - Dense dark layout matching FlintTrade terminal theme
 *
 * Modules:
 *   types.ts          — types, constants, helpers, persistence
 *   Sparkline.tsx     — design-system mini sparkline wrapper
 *   SearchDialog.tsx  — debounced symbol search overlay
 *   ContextMenus.tsx  — SymbolContextMenu, TabContextMenu, RenameInput
 *   SymbolRow.tsx     — individual watchlist row
 */

import { useState, useEffect, useCallback, useRef, memo } from "react";
import { Plus, TrendingUp, Trash2, MoreVertical, SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { channelFromParams, DEFAULT_CHANNEL_ID } from "@/services/fdc3/channels";
import { instrumentContext } from "@/services/fdc3/contexts";
import { useBroadcastInstrument } from "@/services/fdc3/hooks";
import { raiseIntent } from "@/services/fdc3/intents";
import type { WidgetProps } from "@/types/widgets";

import {
  loadTabs,
  saveTabs,
  loadViewSettings,
  saveViewSettings,
  generateId,
  DEFAULT_SYMBOLS,
  MAX_TABS,
  WATCHLIST_COLUMNS,
  WATCHLIST_FORMULAS,
} from "./types";
import type {
  WatchlistColumnId,
  WatchlistItem,
  WatchlistTab,
  SymbolContextMenuState,
  TabContextMenuState,
} from "./types";
import { useWatchlistPolling } from "./useWatchlistPolling";
import { SearchDialog } from "./SearchDialog";
import { FormulaBuilder } from "./FormulaBuilder";
import { SymbolContextMenu, TabContextMenu, RenameInput } from "./ContextMenus";
import { SymbolRow } from "./SymbolRow";

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function WatchlistWidget({ params }: WidgetProps) {
  const [tabs, setTabs]               = useState<WatchlistTab[]>(() => loadTabs());
  const [activeTabIdx, setActiveTabIdx] = useState(0);
  const [showSearch, setShowSearch]   = useState(false);
  const [showMenu, setShowMenu]       = useState(false);
  const [showColumns, setShowColumns] = useState(false);
  const [symbolCtxMenu, setSymbolCtxMenu] = useState<SymbolContextMenuState | null>(null);
  const [tabCtxMenu, setTabCtxMenu]   = useState<TabContextMenuState | null>(null);
  const [renamingIdx, setRenamingIdx] = useState<number | null>(null);
  const [viewSettings, setViewSettings] = useState(() => loadViewSettings());
  const menuRef                       = useRef<HTMLDivElement | null>(null);

  // FDC3 channel membership is panel config: no `channel` key means the
  // default (red) channel — exactly what the legacy selectedSymbolAtom
  // writers set — and `channel: "none"` means joined to nothing. The
  // watchlist is a BROADCASTER, so joined-to-none clicks broadcast nowhere.
  const channel = channelFromParams(params);
  const broadcast = useBroadcastInstrument(channel ?? DEFAULT_CHANNEL_ID);
  const broadcastSelection = useCallback(
    (item: WatchlistItem) => {
      if (channel) broadcast({ symbol: item.symbol, exchange: item.exchange });
    },
    [channel, broadcast],
  );

  // Keep active index within bounds when tabs change
  useEffect(() => {
    setActiveTabIdx((prev) => Math.min(prev, tabs.length - 1));
  }, [tabs.length]);

  // Persist whenever tabs change
  useEffect(() => {
    saveTabs(tabs);
  }, [tabs]);

  useEffect(() => {
    saveViewSettings(viewSettings);
  }, [viewSettings]);

  const activeTab = tabs[activeTabIdx] ?? tabs[0];
  const watchlist = activeTab?.symbols ?? [];

  const { quotes, sparkHistory, fetchError } = useWatchlistPolling(watchlist);

  // ---------------------------------------------------------------------------
  // Tab management
  // ---------------------------------------------------------------------------

  const handleAddTab = useCallback(() => {
    if (tabs.length >= MAX_TABS) return;
    setTabs((prev) => {
      const n = prev.length + 1;
      return [...prev, { id: generateId(), name: `Watchlist ${n}`, symbols: [] }];
    });
    setActiveTabIdx(tabs.length);
  }, [tabs.length]);

  const handleRenameTab = useCallback((idx: number, newName: string) => {
    setTabs((prev) =>
      prev.map((t, i) => (i === idx ? { ...t, name: newName } : t)),
    );
    setRenamingIdx(null);
    setTabCtxMenu(null);
  }, []);

  const handleDuplicateTab = useCallback((idx: number) => {
    if (tabs.length >= MAX_TABS) return;
    setTabs((prev) => {
      const src = prev[idx];
      if (!src) return prev;
      const copy: WatchlistTab = {
        id:      generateId(),
        name:    `${src.name} (copy)`,
        symbols: [...src.symbols],
      };
      const next = [...prev];
      next.splice(idx + 1, 0, copy);
      return next;
    });
    setActiveTabIdx(idx + 1);
    setTabCtxMenu(null);
  }, [tabs.length]);

  const handleDeleteTab = useCallback((idx: number) => {
    if (tabs.length <= 1) return;
    setTabs((prev) => prev.filter((_, i) => i !== idx));
    setActiveTabIdx((prev) => Math.min(prev, tabs.length - 2));
    setTabCtxMenu(null);
  }, [tabs.length]);

  // ---------------------------------------------------------------------------
  // Symbol management
  // ---------------------------------------------------------------------------

  const handleAdd = useCallback((item: WatchlistItem) => {
    setTabs((prev) =>
      prev.map((tab, i) => {
        if (i !== activeTabIdx) return tab;
        const exists = tab.symbols.some(
          (w) => w.symbol === item.symbol && w.exchange === item.exchange,
        );
        if (exists) return tab;
        return { ...tab, symbols: [...tab.symbols, { symbol: item.symbol, exchange: item.exchange }] };
      }),
    );
  }, [activeTabIdx]);

  const handleRemoveSymbol = useCallback((item: WatchlistItem) => {
    setTabs((prev) =>
      prev.map((tab, i) => {
        if (i !== activeTabIdx) return tab;
        return {
          ...tab,
          symbols: tab.symbols.filter(
            (w) => !(w.symbol === item.symbol && w.exchange === item.exchange),
          ),
        };
      }),
    );
    setSymbolCtxMenu(null);
  }, [activeTabIdx]);

  const handleClearAll = useCallback(() => {
    setTabs((prev) =>
      prev.map((tab, i) => (i !== activeTabIdx ? tab : { ...tab, symbols: [] })),
    );
    setShowMenu(false);
  }, [activeTabIdx]);

  const handleResetDefaults = useCallback(() => {
    setTabs((prev) =>
      prev.map((tab, i) => (i !== activeTabIdx ? tab : { ...tab, symbols: DEFAULT_SYMBOLS })),
    );
    setShowMenu(false);
  }, [activeTabIdx]);

  const toggleColumn = useCallback((column: WatchlistColumnId) => {
    if (column === "symbol") return;
    setViewSettings((prev) => {
      const visible = new Set(prev.visibleColumns);
      if (visible.has(column)) visible.delete(column);
      else visible.add(column);
      visible.add("symbol");
      return { ...prev, visibleColumns: Array.from(visible) };
    });
  }, []);

  const setFormula = useCallback((formula: string) => {
    setViewSettings((prev) => ({
      ...prev,
      formula,
      visibleColumns: Array.from(new Set([...prev.visibleColumns, "symbol", "formula"])),
    }));
  }, []);

  const addCustomFormula = useCallback((name: string, expression: string) => {
    const id = `custom:${generateId()}`;
    setViewSettings((prev) => ({
      ...prev,
      customFormulas: [...prev.customFormulas, { id, name, expression }],
      formula: id,
      visibleColumns: Array.from(new Set([...prev.visibleColumns, "symbol", "formula"])),
    }));
  }, []);

  const removeCustomFormula = useCallback((id: string) => {
    setViewSettings((prev) => ({
      ...prev,
      customFormulas: prev.customFormulas.filter((f) => f.id !== id),
      // Fall back to a built-in if the removed formula was selected.
      formula: prev.formula === id ? "rangePct" : prev.formula,
    }));
  }, []);

  // ---------------------------------------------------------------------------
  // Context menus
  // ---------------------------------------------------------------------------

  const openSymbolCtxMenu = useCallback((e: React.MouseEvent, item: WatchlistItem) => {
    e.preventDefault();
    setSymbolCtxMenu({ x: e.clientX, y: e.clientY, item });
  }, []);

  const openTabCtxMenu = useCallback((e: React.MouseEvent, idx: number) => {
    e.preventDefault();
    setTabCtxMenu({ x: e.clientX, y: e.clientY, idx });
  }, []);

  const handleSelect = useCallback((item: WatchlistItem) => {
    broadcastSelection(item);
  }, [broadcastSelection]);

  // Row-hover quick Buy/Sell: focus the symbol and open a PREFILLED order ticket.
  // This never places an order — the ticket's own (gated) submit path is
  // unchanged; the CreateOrder intent only launches the OrderPad panel with
  // symbol/exchange/side set (same flinttrade:addWidget detail as before).
  const handleQuickTrade = useCallback((item: WatchlistItem, side: "BUY" | "SELL") => {
    broadcastSelection(item);
    raiseIntent(
      "CreateOrder",
      instrumentContext({ symbol: item.symbol, exchange: item.exchange }),
      { side, title: `Order — ${item.symbol}` },
    );
  }, [broadcastSelection]);

  // Close overflow menu on outside click
  useEffect(() => {
    if (!showMenu) return;
    function handle(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [showMenu]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const count = watchlist.length;

  return (
    <div
      className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden relative"
      data-tour-target="watchlist"
    >
      {/* HEADER */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
          Watchlist
        </span>

        {count > 0 && (
          <span className="text-xxs font-mono bg-surface-hover text-text-muted border border-border-default rounded px-1 leading-4">
            {count}
          </span>
        )}

        {fetchError && (
          <span title={fetchError} className="w-1.5 h-1.5 rounded-full bg-loss shrink-0" />
        )}

        <div className="flex-1" />

        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowSearch(true)}
          className="h-5 w-5 p-0 text-text-muted hover:text-text-primary hover:bg-surface-hover"
          aria-label="Add symbol"
          title="Add symbol"
        >
          <Plus size={11} />
        </Button>

        <div className="relative" ref={menuRef}>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowMenu((v) => !v)}
            className="h-5 w-5 p-0 text-text-muted hover:text-text-primary hover:bg-surface-hover"
            aria-label="More options"
            title="More options"
          >
            <MoreVertical size={11} />
          </Button>

          {showMenu && (
            <div
              role="menu"
              className="absolute right-0 top-6 z-40 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-40"
            >
              <button
                role="menuitem"
                onClick={() => { setShowSearch(true); setShowMenu(false); }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                <Plus size={10} />
                Add symbol
              </button>
              <button
                role="menuitem"
                onClick={handleResetDefaults}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                <TrendingUp size={10} />
                Reset to defaults
              </button>
              <button
                role="menuitem"
                onClick={() => { setShowColumns((v) => !v); setShowMenu(false); }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                <SlidersHorizontal size={10} />
                Manage columns
              </button>
              <div className="border-t border-border-subtle my-1" />
              <button
                role="menuitem"
                onClick={handleClearAll}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-loss hover:bg-loss/10 transition-colors"
              >
                <Trash2 size={10} />
                Clear all
              </button>
            </div>
          )}
        </div>
      </div>

      {showColumns && (
        <div
          role="dialog"
          aria-label="Watchlist columns"
          className="absolute right-2 top-8 z-40 w-60 rounded-md border border-border-default bg-surface-card p-3 shadow-2xl"
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-text-secondary">Columns</span>
            <button
              type="button"
              onClick={() => setShowColumns(false)}
              className="flex h-5 w-5 items-center justify-center rounded text-text-muted hover:bg-surface-hover hover:text-text-primary"
              aria-label="Close columns"
            >
              <X size={12} />
            </button>
          </div>
          <div className="space-y-1">
            {WATCHLIST_COLUMNS.map((column) => (
              <label
                key={column.id}
                className="flex items-center justify-between gap-3 rounded px-1.5 py-1 text-xs text-text-secondary hover:bg-surface-hover"
              >
                <span>{column.label}</span>
                <input
                  type="checkbox"
                  checked={viewSettings.visibleColumns.includes(column.id)}
                  disabled={column.fixed}
                  onChange={() => toggleColumn(column.id)}
                  aria-label={`${column.label} column`}
                  className="accent-accent"
                />
              </label>
            ))}
          </div>
          <label className="mt-3 block text-xs text-text-secondary" htmlFor="watchlist-formula">
            Formula column
          </label>
          <select
            id="watchlist-formula"
            value={viewSettings.formula}
            onChange={(e) => setFormula(e.target.value)}
            className="mt-1 w-full rounded border border-border-default bg-surface-elevated px-2 py-1 text-xs text-text-primary"
          >
            {WATCHLIST_FORMULAS.map((formula) => (
              <option key={formula.id} value={formula.id}>{formula.label}</option>
            ))}
            {viewSettings.customFormulas.length > 0 && (
              <optgroup label="Custom">
                {viewSettings.customFormulas.map((formula) => (
                  <option key={formula.id} value={formula.id}>{formula.name}</option>
                ))}
              </optgroup>
            )}
          </select>
          <FormulaBuilder
            customFormulas={viewSettings.customFormulas}
            onAdd={addCustomFormula}
            onRemove={removeCustomFormula}
          />
        </div>
      )}

      {/* TAB BAR */}
      <div
        className="flex items-center gap-1 px-2 py-1 border-b border-border-default bg-surface-card shrink-0 overflow-x-auto scrollbar-none"
        role="tablist"
        aria-label="Watchlist tabs"
      >
        {tabs.map((tab, idx) => (
          <div key={tab.id} className="shrink-0 flex items-center">
            {renamingIdx === idx ? (
              <RenameInput
                initialValue={tab.name}
                onConfirm={(name) => handleRenameTab(idx, name)}
                onCancel={() => setRenamingIdx(null)}
              />
            ) : (
              <button
                role="tab"
                aria-selected={idx === activeTabIdx}
                onClick={() => setActiveTabIdx(idx)}
                onContextMenu={(e) => openTabCtxMenu(e, idx)}
                className={`text-xs px-2 py-0.5 rounded transition-colors whitespace-nowrap ${
                  idx === activeTabIdx
                    ? "bg-accent/20 text-accent border border-accent/40"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover border border-transparent"
                }`}
                title="Right-click for options"
              >
                {tab.name}
              </button>
            )}
          </div>
        ))}

        {tabs.length < MAX_TABS && (
          <button
            onClick={handleAddTab}
            title="New watchlist"
            aria-label="Add watchlist tab"
            className="shrink-0 w-5 h-5 flex items-center justify-center text-text-muted hover:text-accent hover:bg-surface-hover rounded transition-colors border border-transparent hover:border-accent/30"
          >
            <Plus size={10} />
          </button>
        )}
      </div>

      {/* SYMBOL LIST */}
      <div className="flex-1 overflow-auto">
        {watchlist.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 px-4">
            <TrendingUp size={24} className="text-text-muted" />
            <div className="text-center">
              <p className="text-xs text-text-secondary">Add symbols to {activeTab?.name ?? "watchlist"}</p>
              <p className="text-xs text-text-muted mt-0.5">Track prices in real-time</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowSearch(true)}
              className="h-7 px-3 text-xs bg-accent/10 text-accent border-accent/30 hover:bg-accent/20"
            >
              <Plus size={11} />
              Add symbol
            </Button>
          </div>
        ) : (
          watchlist.map((item) => {
            const key = `${item.symbol}:${item.exchange}`;
            return (
              <SymbolRow
                key={key}
                item={item}
                quote={quotes[key] ?? null}
                sparkPrices={sparkHistory[key] ?? []}
                visibleColumns={viewSettings.visibleColumns}
                formula={viewSettings.formula}
                customFormulas={viewSettings.customFormulas}
                onSelect={handleSelect}
                onRemove={openSymbolCtxMenu}
                onQuickTrade={handleQuickTrade}
              />
            );
          })
        )}
      </div>

      {/* SEARCH DIALOG (overlaid) */}
      {showSearch && (
        <SearchDialog
          onAdd={handleAdd}
          onClose={() => setShowSearch(false)}
        />
      )}

      {/* SYMBOL CONTEXT MENU */}
      {symbolCtxMenu && (
        <SymbolContextMenu
          x={symbolCtxMenu.x}
          y={symbolCtxMenu.y}
          symbol={symbolCtxMenu.item.symbol}
          onRemove={() => handleRemoveSymbol(symbolCtxMenu.item)}
          onClose={() => setSymbolCtxMenu(null)}
        />
      )}

      {/* TAB CONTEXT MENU */}
      {tabCtxMenu && (
        <TabContextMenu
          x={tabCtxMenu.x}
          y={tabCtxMenu.y}
          tabName={tabs[tabCtxMenu.idx]?.name ?? ""}
          canDelete={tabs.length > 1}
          onRename={() => { setRenamingIdx(tabCtxMenu.idx); setTabCtxMenu(null); }}
          onDuplicate={() => handleDuplicateTab(tabCtxMenu.idx)}
          onDelete={() => handleDeleteTab(tabCtxMenu.idx)}
          onClose={() => setTabCtxMenu(null)}
        />
      )}
    </div>
  );
}

export default memo(WatchlistWidget);
