/**
 * SearchDialog — debounced symbol search overlay for WatchlistWidget.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { Search, X } from "lucide-react";
import { searchSymbol } from "@/services/api";
import type { WatchlistItem, SearchResult } from "./types";

export interface SearchDialogProps {
  onAdd:   (item: WatchlistItem) => void;
  onClose: () => void;
}

export function SearchDialog({ onAdd, onClose }: SearchDialogProps) {
  const [query,   setQuery]   = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const debounceRef           = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef              = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleQuery = useCallback((val: string) => {
    setQuery(val);
    setError(null);
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!val.trim()) {
      setResults([]);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchSymbol(val.trim());
        const list = Array.isArray(data) ? (data as SearchResult[]) : [];
        setResults(list.slice(0, 12));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed");
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  }, []);

  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
  }, []);

  const handleSelect = useCallback((item: SearchResult) => {
    onAdd({ symbol: item.symbol, exchange: item.exchange });
    onClose();
  }, [onAdd, onClose]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Search symbols"
      className="absolute inset-0 z-50 flex flex-col bg-surface-base/90 backdrop-blur-sm"
      onKeyDown={handleKeyDown}
    >
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border-default bg-surface-card shrink-0">
        <Search size={11} className="text-text-muted shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleQuery(e.target.value)}
          placeholder="Search symbol… e.g. SBIN, TCS"
          className="flex-1 bg-transparent text-xs text-text-primary placeholder-text-muted focus:outline-none"
        />
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text-primary transition-colors"
          aria-label="Close search"
        >
          <X size={11} />
        </button>
      </div>

      <div className="flex-1 overflow-auto">
        {loading && <div className="px-3 py-2 text-xs text-text-muted">Searching…</div>}
        {error && !loading && <div className="px-3 py-2 text-xs text-loss">{error}</div>}
        {!loading && !error && results.length === 0 && query.trim() && (
          <div className="px-3 py-2 text-xs text-text-muted">No results for &quot;{query}&quot;</div>
        )}
        {!loading && !error && results.length === 0 && !query.trim() && (
          <div className="px-3 py-2 text-xs text-text-muted">Type to search symbols</div>
        )}
        {results.map((item, idx) => (
          <button
            key={`${item.symbol}-${item.exchange}-${idx}`}
            onClick={() => handleSelect(item)}
            className="w-full flex items-center justify-between px-3 py-1.5 hover:bg-surface-hover text-left transition-colors border-b border-border-subtle"
          >
            <div className="flex flex-col min-w-0">
              <span className="text-xs font-medium text-text-primary font-mono truncate">
                {item.symbol}
              </span>
              {item.name && (
                <span className="text-xs text-text-muted truncate">{item.name}</span>
              )}
            </div>
            <span className="text-xs text-text-muted ml-2 shrink-0 font-mono">
              {item.exchange}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
