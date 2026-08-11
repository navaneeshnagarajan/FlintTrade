/**
 * SymbolSearch — searchable symbol combobox (Popover + cmdk Command).
 * Supports live API search with instrument-list fallback when offline.
 */

import { useState, useEffect, useLayoutEffect, useMemo } from "react";
import { ChevronDown, Search, Loader2 } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { searchSymbol } from "@/services/api";
import type { SymbolDef, SymbolSearchResult, InstrumentRecord } from "./types";
import { SYMBOLS } from "./types";

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Debounce hook for search input */
function useDebounce(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

/** Map exchange from search API to option chain exchange */
function mapToOptionExchange(exchange: string): string {
  if (exchange === "NSE" || exchange === "NFO") return "NFO";
  if (exchange === "BSE" || exchange === "BFO") return "BFO";
  if (exchange === "MCX") return "MCX";
  if (exchange === "CDS") return "CDS";
  return "NFO";
}

/** Map exchange to spot exchange for quotes */
function mapToSpotExchange(exchange: string): string {
  if (exchange === "NFO" || exchange === "NSE") return "NSE";
  if (exchange === "BFO" || exchange === "BSE") return "BSE";
  if (exchange === "MCX") return "MCX";
  if (exchange === "CDS") return "CDS";
  return "NSE";
}

/** Convert an InstrumentRecord to a SymbolDef for the option chain */
export function instrumentToSymbolDef(inst: InstrumentRecord): SymbolDef {
  const optExchange  = mapToOptionExchange(inst.exchange);
  const spotExchange = mapToSpotExchange(inst.exchange);
  return {
    label: inst.symbol,
    exchange: optExchange,
    spotSymbol: inst.symbol,
    spotExchange,
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface SymbolSearchProps {
  activeSymbol: SymbolDef;
  dataScope: string;
  onSelect: (sym: SymbolDef) => void;
  instruments: InstrumentRecord[];
}

export default function SymbolSearch({ activeSymbol, dataScope, onSelect, instruments }: SymbolSearchProps) {
  const [open, setOpen]                       = useState(false);
  const [query, setQuery]                     = useState("");
  const [searchResults, setSearchResults]     = useState<SymbolSearchResult[]>([]);
  const [searchFailed, setSearchFailed]       = useState(false);
  const [searching, setSearching]             = useState(false);
  const debouncedQuery                        = useDebounce(query, 300);

  useLayoutEffect(() => {
    // Search results are authority-owned. Remove A's selectable contracts
    // before the browser can paint B, then let the scoped effect repopulate.
    setSearchResults([]);
    setSearchFailed(false);
    setSearching(false);
    setOpen(false);
  }, [dataScope]);

  // Known labels in the hardcoded SYMBOLS list — used for deduplication
  const hardcodedLabels = useMemo(() => new Set(SYMBOLS.map((s) => s.label)), []);

  // Extra instruments from the API that aren't in the hardcoded list
  const extraInstruments = useMemo(
    () => instruments.filter((inst) => !hardcodedLabels.has(inst.symbol)),
    [instruments, hardcodedLabels],
  );

  // Client-side filter of instruments matching the query (fallback when API search fails/returns nothing)
  const instrumentFallbackResults = useMemo<SymbolSearchResult[]>(() => {
    if (debouncedQuery.length < 2) return [];
    const q = debouncedQuery.toUpperCase();
    return instruments
      .filter((inst) => inst.symbol.includes(q) || inst.name.toUpperCase().includes(q))
      .slice(0, 15)
      .map((inst) => ({ symbol: inst.symbol, exchange: inst.exchange }));
  }, [debouncedQuery, instruments]);

  // Search API when query changes (2+ chars)
  useEffect(() => {
    if (debouncedQuery.length < 2) {
      setSearchResults([]);
      setSearchFailed(false);
      setSearching(false);
      return;
    }
    const controller = new AbortController();
    setSearchResults([]);
    setSearching(true);
    setSearchFailed(false);
    (async () => {
      try {
        const raw = await searchSymbol(
          debouncedQuery.trim(),
          undefined,
          controller.signal,
          dataScope,
        );
        if (controller.signal.aborted) return;
        const list = Array.isArray(raw)
          ? raw
          : ((raw as unknown as { data?: SymbolSearchResult[] })?.data ?? []);
        setSearchResults(list.slice(0, 15));
        setSearchFailed(false);
      } catch {
        if (!controller.signal.aborted) {
          setSearchResults([]);
          setSearchFailed(true);
        }
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    })();
    return () => controller.abort();
  }, [debouncedQuery, dataScope]);

  const showingFallback = !searching && debouncedQuery.length >= 2 && (searchFailed || searchResults.length === 0) && instrumentFallbackResults.length > 0;
  const displayResults  = showingFallback ? instrumentFallbackResults : searchResults;

  function instrumentName(symbol: string): string | null {
    const found = instruments.find((i) => i.symbol === symbol);
    return found?.name ?? null;
  }

  function handleSelectPopular(sym: SymbolDef) {
    onSelect(sym);
    setOpen(false);
    setQuery("");
    setSearchResults([]);
  }

  function handleSelectSearch(result: SymbolSearchResult) {
    const optExchange  = mapToOptionExchange(result.exchange);
    const spotExchange = mapToSpotExchange(result.exchange);
    onSelect({ label: result.symbol, exchange: optExchange, spotSymbol: result.symbol, spotExchange });
    setOpen(false);
    setQuery("");
    setSearchResults([]);
  }

  function handleSelectInstrument(inst: InstrumentRecord) {
    onSelect(instrumentToSymbolDef(inst));
    setOpen(false);
    setQuery("");
    setSearchResults([]);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className="flex items-center gap-1 px-2 py-1 text-xs font-semibold text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors"
          aria-label="Select symbol"
        >
          <Search size={10} className="text-text-muted" />
          {activeSymbol.label}
          <ChevronDown size={10} className={`text-text-muted transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0 bg-surface-card border-border-default" align="start" sideOffset={4}>
        <Command shouldFilter={false} className="bg-surface-card">
          <CommandInput
            placeholder="Search symbol..."
            value={query}
            onValueChange={setQuery}
            className="text-xs"
          />
          <CommandList className="max-h-72">

            {/* Search results — shown when typing */}
            {debouncedQuery.length >= 2 && (
              <CommandGroup heading={
                searching
                  ? "Searching..."
                  : showingFallback
                    ? `Offline matches for "${debouncedQuery}"`
                    : `Results for "${debouncedQuery}"`
              }>
                {searching && (
                  <div className="flex items-center justify-center py-2">
                    <Loader2 size={14} className="animate-spin text-text-muted" />
                  </div>
                )}
                {!searching && displayResults.length === 0 && (
                  <CommandEmpty>No symbols found</CommandEmpty>
                )}
                {!searching && displayResults.map((r) => {
                  const name = instrumentName(r.symbol);
                  return (
                    <CommandItem
                      key={`${r.symbol}-${r.exchange}`}
                      value={`${r.symbol}-${r.exchange}`}
                      onSelect={() => handleSelectSearch(r)}
                      className="text-xs cursor-pointer"
                    >
                      <span className="font-semibold text-text-primary">{r.symbol}</span>
                      {name && (
                        <span className="ml-1.5 text-xxs text-text-muted truncate max-w-28">{name}</span>
                      )}
                      <span className="ml-auto text-xxs text-text-muted shrink-0">{r.exchange}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            )}

            {/* Popular symbols — shown when no query */}
            {debouncedQuery.length < 2 && (
              <>
                <CommandGroup heading="Popular">
                  {SYMBOLS.map((sym) => (
                    <CommandItem
                      key={`${sym.label}-${sym.exchange}`}
                      value={`${sym.label}-${sym.exchange}`}
                      onSelect={() => handleSelectPopular(sym)}
                      className={`text-xs cursor-pointer ${
                        sym.label === activeSymbol.label ? "bg-accent/10 text-accent" : ""
                      }`}
                    >
                      <span className="font-semibold">{sym.label}</span>
                      <span className="ml-auto text-xxs text-text-muted">{sym.exchange}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>

                {extraInstruments.length > 0 && (
                  <>
                    <CommandSeparator />
                    <CommandGroup heading="All Instruments">
                      {extraInstruments.slice(0, 50).map((inst) => (
                        <CommandItem
                          key={`inst-${inst.symbol}-${inst.exchange}`}
                          value={`inst-${inst.symbol}-${inst.exchange}`}
                          onSelect={() => handleSelectInstrument(inst)}
                          className={`text-xs cursor-pointer ${
                            inst.symbol === activeSymbol.label ? "bg-accent/10 text-accent" : ""
                          }`}
                        >
                          <span className="font-semibold">{inst.symbol}</span>
                          <span className="ml-1.5 text-xxs text-text-muted truncate max-w-28">{inst.name}</span>
                          <span className="ml-auto text-xxs text-text-muted shrink-0">{inst.exchange}</span>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </>
                )}
              </>
            )}

            {/* When searching: show Popular shortcut below results */}
            {debouncedQuery.length >= 2 && displayResults.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Popular">
                  {SYMBOLS.slice(0, 5).map((sym) => (
                    <CommandItem
                      key={`pop-${sym.label}-${sym.exchange}`}
                      value={`pop-${sym.label}-${sym.exchange}`}
                      onSelect={() => handleSelectPopular(sym)}
                      className="text-xs cursor-pointer"
                    >
                      <span className="font-semibold">{sym.label}</span>
                      <span className="ml-auto text-xxs text-text-muted">{sym.exchange}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}

          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
