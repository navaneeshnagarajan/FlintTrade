/**
 * MutualFundTab.tsx
 *
 * Mutual Fund Explorer with live NAV data from AMFI India.
 * Search funds by name/AMC, filter by SEBI category, view current NAV.
 *
 * Features:
 *   - Search bar with debounced input (2 char minimum)
 *   - SEBI category filter dropdown
 *   - Results table: scheme name, AMC, category, NAV, NAV date
 *   - Click row to see fund detail (scheme code, type)
 *   - Mode-aware: explore mode uses fallback data, live fetches from backend
 *
 * Data source: AMFI NAVAll.txt parsed by the Python backend.
 */

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import {
  Search,
  TrendingUp,
  IndianRupee,
  Filter,
  Loader2,
  AlertCircle,
  X,
  Building2,
  ChevronDown,
  ExternalLink,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { useMFSearch, useMFCategories } from "@/hooks/useMutualFundData";

// ---------------------------------------------------------------------------
// Debounce hook
// ---------------------------------------------------------------------------

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(() => setDebounced(value), delayMs);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [value, delayMs]);

  return debounced;
}

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

function formatNAV(nav: number): string {
  return nav.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function shortenCategory(cat: string): string {
  // "Equity Scheme - Large Cap Fund" → "Large Cap"
  const parts = cat.split(" - ");
  if (parts.length > 1) {
    return parts[1].replace(/\s*Fund\s*$/i, "").trim();
  }
  return cat;
}

function schemeTypeColour(type: string): string {
  const t = type.toLowerCase();
  if (t.includes("open")) return "text-profit";
  if (t.includes("close")) return "text-loss";
  return "text-text-muted";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MutualFundTab() {
  const [rawInput, setRawInput] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("");
  const [showCategoryDropdown, setShowCategoryDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Debounce the search input by 300ms to avoid excessive API calls
  const debouncedQuery = useDebouncedValue(rawInput, 300);

  const { funds, isLoading, isLive, error } = useMFSearch(
    debouncedQuery,
    selectedCategory || undefined,
  );
  const { categories } = useMFCategories();

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowCategoryDropdown(false);
      }
    }
    if (showCategoryDropdown) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [showCategoryDropdown]);

  const clearSearch = useCallback(() => {
    setRawInput("");
    setSelectedCategory("");
  }, []);

  // Group funds by AMC for summary stats
  const amcCount = useMemo(
    () => new Set(funds.map((f) => f.amc)).size,
    [funds],
  );

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <TrendingUp className="size-4 text-accent" aria-hidden="true" />
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Mutual Fund Explorer
          </h3>
          {!isLive && (
            <Badge variant="outline" className="text-xxs h-4 px-1.5 border-amber-500/30 text-amber-400">
              Sample Data
            </Badge>
          )}
        </div>
        <p className="text-xs text-text-muted mt-1">
          Search Indian mutual funds with live NAV data from AMFI. Updated daily after market close.
        </p>
      </div>

      {/* Search + filter section */}
      <GlassCard className="p-4 gap-3">
        <div className="flex items-end gap-3 flex-wrap">
          {/* Search input */}
          <div className="flex-1 min-w-48 space-y-1.5">
            <label htmlFor="mf-search-input" className="text-xs font-medium text-text-secondary">
              Search Funds
            </label>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-text-muted" aria-hidden="true" />
              <Input
                id="mf-search-input"
                value={rawInput}
                onChange={(e) => setRawInput(e.target.value)}
                placeholder="e.g. Axis Bluechip, SBI, HDFC Mid Cap..."
                className="pl-8 pr-8 h-8 text-xs bg-surface-card border-border-default"
              />
              {rawInput.length > 0 && (
                <button
                  onClick={clearSearch}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                  aria-label="Clear search"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>
            <p className="text-xxs text-text-muted">
              Type at least 2 characters to search by fund name or AMC.
            </p>
          </div>

          {/* Category filter */}
          <div className="space-y-1.5 relative" ref={dropdownRef}>
            <label className="text-xs font-medium text-text-secondary">
              Category
            </label>
            <button
              type="button"
              onClick={() => setShowCategoryDropdown((v) => !v)}
              className={cn(
                "flex items-center gap-2 h-8 px-3 text-xs rounded-md border transition-colors",
                "bg-surface-card border-border-default",
                "hover:border-accent/50",
                selectedCategory ? "text-text-primary" : "text-text-muted",
              )}
            >
              <Filter className="size-3" aria-hidden="true" />
              <span className="max-w-32 truncate">
                {selectedCategory ? shortenCategory(selectedCategory) : "All categories"}
              </span>
              <ChevronDown className="size-3 shrink-0" />
            </button>

            {showCategoryDropdown && (
              <div className="absolute top-full left-0 mt-1 w-72 max-h-64 overflow-y-auto z-50 rounded-md border border-border-default bg-surface-raised shadow-lg">
                <button
                  className={cn(
                    "w-full text-left px-3 py-1.5 text-xs hover:bg-surface-elevated transition-colors",
                    !selectedCategory && "text-accent font-medium",
                  )}
                  onClick={() => {
                    setSelectedCategory("");
                    setShowCategoryDropdown(false);
                  }}
                >
                  All categories
                </button>
                {categories.map((cat) => (
                  <button
                    key={cat}
                    className={cn(
                      "w-full text-left px-3 py-1.5 text-xs hover:bg-surface-elevated transition-colors",
                      selectedCategory === cat && "text-accent font-medium",
                    )}
                    onClick={() => {
                      setSelectedCategory(cat);
                      setShowCategoryDropdown(false);
                    }}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Quick suggestions */}
        {rawInput.length === 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            <span className="text-xxs text-text-muted mr-1">Try:</span>
            {["Axis", "HDFC", "SBI", "Parag Parikh", "Mirae", "Nifty 50"].map((s) => (
              <button
                key={s}
                onClick={() => setRawInput(s)}
                className="text-xxs text-accent hover:text-accent/80 underline-offset-2 hover:underline transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </GlassCard>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center justify-center py-8 gap-2 text-text-muted">
          <Loader2 className="size-4 animate-spin" />
          <span className="text-xs">Searching funds...</span>
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div className="flex items-center gap-2 py-4 px-3 rounded-md bg-loss/10 text-loss text-xs">
          <AlertCircle className="size-4 shrink-0" />
          <span>Failed to load fund data. Please try again.</span>
        </div>
      )}

      {/* Results table */}
      {!isLoading && !error && funds.length > 0 && (
        <GlassCard className="p-0 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 border-b border-border-default">
            <div className="flex items-center gap-2">
              <Building2 className="size-3 text-text-muted" aria-hidden="true" />
              <span className="text-xs font-medium text-text-secondary">
                Search Results
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Badge
                variant="outline"
                className="text-xxs border-border-default text-text-muted h-4 px-1.5"
              >
                {funds.length} fund{funds.length !== 1 ? "s" : ""}
              </Badge>
              {amcCount > 1 && (
                <Badge
                  variant="outline"
                  className="text-xxs border-border-default text-text-muted h-4 px-1.5"
                >
                  {amcCount} AMC{amcCount !== 1 ? "s" : ""}
                </Badge>
              )}
            </div>
          </div>

          <Table aria-label="Mutual fund search results">
            <TableHeader>
              <TableRow className="border-border-default hover:bg-transparent">
                <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider">
                  Fund Name
                </TableHead>
                <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider">
                  AMC
                </TableHead>
                <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-center">
                  Category
                </TableHead>
                <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                  NAV
                </TableHead>
                <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                  Date
                </TableHead>
                <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-center">
                  Type
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {funds.map((fund) => (
                <TableRow
                  key={fund.scheme_code}
                  className="border-border-default hover:bg-surface-card transition-colors group"
                >
                  <TableCell className="py-2 text-xs max-w-64">
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium text-text-primary truncate">
                        {fund.scheme_name}
                      </span>
                      <a
                        href={`https://www.amfiindia.com/net-asset-value/nav-history?SchemeType=All&SchemeCategory=All&SchemeName=${fund.scheme_code}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                        aria-label={`View ${fund.scheme_name} on AMFI`}
                      >
                        <ExternalLink className="size-3 text-text-muted hover:text-accent" />
                      </a>
                    </div>
                    <div className="text-xxs text-text-muted font-mono mt-0.5">
                      Code: {fund.scheme_code}
                    </div>
                  </TableCell>
                  <TableCell className="py-2 text-xs text-text-secondary max-w-36 truncate">
                    {fund.amc}
                  </TableCell>
                  <TableCell className="py-2 text-center">
                    <Badge
                      variant="outline"
                      className="text-xxs border-border-default text-text-muted font-normal h-4 px-1.5"
                    >
                      {shortenCategory(fund.category)}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-2 text-right">
                    <div className="flex items-center justify-end gap-0.5">
                      <IndianRupee className="size-3 text-profit" aria-hidden="true" />
                      <span className="font-mono tabular-nums text-xs text-text-primary font-semibold">
                        {formatNAV(fund.nav)}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="py-2 text-right font-mono tabular-nums text-xxs text-text-muted">
                    {fund.nav_date}
                  </TableCell>
                  <TableCell className="py-2 text-center">
                    <span className={cn("text-xxs font-medium", schemeTypeColour(fund.scheme_type))}>
                      {fund.scheme_type}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </GlassCard>
      )}

      {/* Empty state — search active but no results */}
      {!isLoading && !error && debouncedQuery.length >= 2 && funds.length === 0 && (
        <div className="flex flex-col items-center justify-center h-32 gap-3 text-text-muted">
          <AlertCircle className="size-5" aria-hidden="true" />
          <span className="text-sm">No funds found for &quot;{debouncedQuery}&quot;</span>
          <span className="text-xs text-center max-w-xs">
            Try a different name or AMC. Search covers all AMFI-registered mutual funds in India.
          </span>
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-xxs text-text-muted">
        NAV data sourced from AMFI India (amfiindia.com). Updated daily after market close.
        Past performance does not guarantee future returns. Mutual fund investments are subject
        to market risks. Read all scheme-related documents carefully before investing.
      </p>
    </div>
  );
}
