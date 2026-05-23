/**
 * TickerSettings — Settings section for the TopBar ticker strip.
 *
 * Controls:
 *   - Mode selector (Off / Pinned / Scroll / Marquee)
 *   - Speed slider (10–60 s, shown only when mode is "marquee")
 *   - Symbol list with remove buttons + add symbol input with autocomplete
 */

import { useState, useRef, useEffect, useCallback, type KeyboardEvent } from "react";
import { GripVertical, X, Plus, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSettingsStore, DEFAULT_TICKER_SYMBOLS, type TickerMode } from "@/stores/settingsStore";
import { searchSymbol } from "@/services/api";
import { SectionTitle, FieldRow, SegmentControl } from "@/tools/Settings/shared";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SearchResult {
  symbol: string;
  exchange: string;
}

// ---------------------------------------------------------------------------
// SpeedSlider — native range input styled for the settings panel
// ---------------------------------------------------------------------------

interface SpeedSliderProps {
  value: number;
  onChange: (v: number) => void;
}

function SpeedSlider({ value, onChange }: SpeedSliderProps) {
  const pct = ((value - 10) / (60 - 10)) * 100;
  return (
    <div className="space-y-1 max-w-xs">
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={10}
          max={60}
          step={1}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1 h-1.5 rounded-full appearance-none cursor-pointer"
          style={{
            background: `linear-gradient(90deg, var(--color-accent, #7c6aff) ${pct}%, rgba(255,255,255,0.1) ${pct}%)`,
          }}
          aria-label="Ticker scroll duration in seconds"
          aria-valuemin={10}
          aria-valuemax={60}
          aria-valuenow={value}
          data-testid="ticker-speed-slider"
        />
        <span className="text-xs font-mono tabular-nums text-text-secondary w-10 shrink-0 text-right">
          {value}s
        </span>
      </div>
      <div className="flex justify-between text-xs text-text-muted select-none">
        <span>10s (fast)</span>
        <span>60s (slow)</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SymbolTag — single removable chip in the symbol list
// ---------------------------------------------------------------------------

interface SymbolTagProps {
  value: string;
  onRemove: () => void;
}

function SymbolTag({ value, onRemove }: SymbolTagProps) {
  return (
    <div
      className="flex items-center gap-1 px-2 py-1 rounded bg-surface-base border border-border-default text-xs text-text-primary"
      data-testid={`ticker-symbol-tag-${value}`}
    >
      <span
        className="text-text-muted/40 cursor-grab active:cursor-grabbing select-none"
        aria-hidden="true"
      >
        <GripVertical size={12} />
      </span>
      <span className="font-mono">{value}</span>
      <button
        type="button"
        onClick={onRemove}
        className="ml-1 text-text-muted/50 hover:text-loss transition-colors"
        aria-label={`Remove ${value}`}
        data-testid={`remove-symbol-${value}`}
      >
        <X size={11} />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AddSymbolInput — text input with live search autocomplete
// ---------------------------------------------------------------------------

interface AddSymbolInputProps {
  onAdd: (symbol: string) => void;
}

function AddSymbolInput({ onAdd }: AddSymbolInputProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [activeIdx, setActiveIdx] = useState(-1);

  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const hits = await searchSymbol(q.trim());
      setResults(hits.slice(0, 8));
      setOpen(hits.length > 0);
    } catch {
      setResults([]);
      setOpen(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    setActiveIdx(-1);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(val), 300);
  };

  const handleSelect = (result: SearchResult) => {
    const composed = `${result.exchange}:${result.symbol}`;
    onAdd(composed);
    setQuery("");
    setResults([]);
    setOpen(false);
    setActiveIdx(-1);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      handleSelect(results[activeIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
      setActiveIdx(-1);
    }
  };

  // Direct entry in EXCHANGE:SYMBOL format via + button
  const handleAddDirect = () => {
    if (results.length > 0 && activeIdx >= 0) {
      handleSelect(results[activeIdx]);
    } else if (query.includes(":")) {
      onAdd(query.toUpperCase().trim());
      setQuery("");
      setResults([]);
      setOpen(false);
    }
  };

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        inputRef.current &&
        !inputRef.current.contains(e.target as Node) &&
        listRef.current &&
        !listRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Input
            ref={inputRef}
            value={query}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Search symbol (e.g. NIFTY, GOLD)"
            className="h-8 text-xs font-mono bg-surface-base border-border-default pr-7"
            aria-label="Search symbol to add"
            aria-autocomplete="list"
            aria-controls={open ? "ticker-symbol-results" : undefined}
            aria-activedescendant={activeIdx >= 0 ? `ticker-result-${activeIdx}` : undefined}
            data-testid="ticker-symbol-search"
          />
          {loading && (
            <Loader2
              size={12}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted animate-spin"
              aria-hidden="true"
            />
          )}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 px-2 text-xs shrink-0"
          onClick={handleAddDirect}
          aria-label="Add symbol"
          data-testid="ticker-add-symbol-btn"
        >
          <Plus size={13} />
        </Button>
      </div>

      {open && results.length > 0 && (
        <ul
          ref={listRef}
          id="ticker-symbol-results"
          role="listbox"
          aria-label="Search results"
          className="absolute z-50 mt-1 w-full rounded border border-border-default bg-surface-floating shadow-lg overflow-auto max-h-44"
          data-testid="ticker-symbol-results"
        >
          {results.map((r, i) => (
            <li
              key={`${r.exchange}:${r.symbol}`}
              id={`ticker-result-${i}`}
              role="option"
              aria-selected={i === activeIdx}
              onClick={() => handleSelect(r)}
              className={`flex items-center justify-between px-3 py-1.5 text-xs cursor-pointer transition-colors ${
                i === activeIdx
                  ? "bg-accent/15 text-accent"
                  : "text-text-primary hover:bg-surface-hover"
              }`}
            >
              <span className="font-mono">{r.symbol}</span>
              <span className="text-text-muted ml-2">{r.exchange}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TickerSettings
// ---------------------------------------------------------------------------

export function TickerSettings() {
  const tickerMode    = useSettingsStore((s) => s.tickerMode);
  const tickerSymbols = useSettingsStore((s) => s.tickerSymbols);
  const tickerSpeed   = useSettingsStore((s) => s.tickerSpeed);

  const setTickerMode    = useSettingsStore((s) => s.setTickerMode);
  const setTickerSymbols = useSettingsStore((s) => s.setTickerSymbols);
  const setTickerSpeed   = useSettingsStore((s) => s.setTickerSpeed);

  const handleRemove = (idx: number) => {
    setTickerSymbols(tickerSymbols.filter((_, i) => i !== idx));
  };

  const handleAdd = (symbol: string) => {
    if (!symbol || tickerSymbols.includes(symbol)) return;
    setTickerSymbols([...tickerSymbols, symbol]);
  };

  const handleReset = () => {
    setTickerSymbols(DEFAULT_TICKER_SYMBOLS);
  };

  // Drag-and-drop reorder — native HTML5 drag
  const dragIdx = useRef<number | null>(null);
  const dragOverIdx = useRef<number | null>(null);

  const handleDragStart = (idx: number) => {
    dragIdx.current = idx;
  };
  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    dragOverIdx.current = idx;
  };
  const handleDrop = () => {
    if (dragIdx.current === null || dragOverIdx.current === null) return;
    if (dragIdx.current === dragOverIdx.current) return;
    const next = [...tickerSymbols];
    const [moved] = next.splice(dragIdx.current, 1);
    next.splice(dragOverIdx.current, 0, moved);
    setTickerSymbols(next);
    dragIdx.current = null;
    dragOverIdx.current = null;
  };

  return (
    <div className="space-y-6">
      <SectionTitle>Ticker Bar</SectionTitle>

      {/* Mode selector */}
      <FieldRow
        label="Display Mode"
        hint="Controls how the ticker strip appears in the top bar."
      >
        <SegmentControl
          value={tickerMode}
          onChange={(v) => setTickerMode(v as TickerMode)}
          options={[
            { value: "off",     label: "Off"     },
            { value: "pinned",  label: "Pinned"  },
            { value: "scroll",  label: "Scroll"  },
            { value: "marquee", label: "Marquee" },
          ]}
          aria-label="Ticker display mode"
        />
      </FieldRow>

      {/* Speed slider — only visible in marquee mode */}
      {tickerMode === "marquee" && (
        <FieldRow
          label="Scroll Duration"
          hint="Total seconds for one full scroll loop. Lower values scroll faster."
          tooltip="Duration of the marquee animation cycle. Adjust until the speed feels comfortable."
        >
          <SpeedSlider value={tickerSpeed} onChange={setTickerSpeed} />
        </FieldRow>
      )}

      {/* Symbol list */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-secondary">
            Symbols ({tickerSymbols.length})
          </span>
          <button
            type="button"
            onClick={handleReset}
            className="text-xs text-text-muted hover:text-text-secondary transition-colors"
            aria-label="Reset symbols to defaults"
            data-testid="ticker-reset-symbols"
          >
            Reset to defaults
          </button>
        </div>

        {tickerSymbols.length === 0 ? (
          <p className="text-xs text-text-muted py-2">
            No symbols configured. Add some below.
          </p>
        ) : (
          <div
            className="flex flex-wrap gap-1.5"
            role="list"
            aria-label="Ticker symbols"
            data-testid="ticker-symbol-list"
          >
            {tickerSymbols.map((sym, idx) => (
              <div
                key={sym}
                role="listitem"
                draggable
                onDragStart={() => handleDragStart(idx)}
                onDragOver={(e) => handleDragOver(e, idx)}
                onDrop={handleDrop}
              >
                <SymbolTag
                  value={sym}
                  onRemove={() => handleRemove(idx)}
                />
              </div>
            ))}
          </div>
        )}

        {/* Add symbol input */}
        <AddSymbolInput onAdd={handleAdd} />
        <p className="text-xs text-text-muted">
          Drag chips to reorder. Type at least 2 characters to search. You can also type
          in <code className="font-mono text-text-secondary">EXCHANGE:SYMBOL</code> format
          and press the + button.
        </p>
      </div>
    </div>
  );
}
