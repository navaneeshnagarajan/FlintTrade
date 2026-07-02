/**
 * DocsTab — Command Palette inline docs search tab.
 *
 * Activated by the "?" prefix in the Ctrl+K palette. Searches docs via
 * /ft-api/v1/docs/search and renders inline results within the palette.
 */

import { useEffect, useLayoutEffect, useState, useRef } from "react";
import { FileText, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { searchDocs, type DocSearchResult } from "@/components/DocsSearch/DocsSearch";

interface DocsTabProps {
  query: string;
  activeIndex: number;
  onClose: () => void;
  onActiveIndexChange: (index: number) => void;
  onActiveDocChange?: (result: DocSearchResult | null) => void;
}

export function DocsTab({
  query,
  activeIndex,
  onClose,
  onActiveIndexChange,
  onActiveDocChange,
}: DocsTabProps) {
  const [results, setResults] = useState<DocSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setLoading(true);
      const found = await searchDocs(query, abortRef.current.signal);
      setResults(found);
      onActiveIndexChange(0);
      setLoading(false);
    }, 250);

    return () => clearTimeout(timer);
  }, [query, onActiveIndexChange]);

  // Clamp active index
  useEffect(() => {
    if (results.length > 0 && activeIndex >= results.length) {
      onActiveIndexChange(results.length - 1);
    }
  }, [activeIndex, results.length, onActiveIndexChange]);

  useLayoutEffect(() => {
    onActiveDocChange?.(results[activeIndex] ?? null);
  }, [activeIndex, results, onActiveDocChange]);

  function handleSelect(result: DocSearchResult) {
    window.dispatchEvent(
      new CustomEvent("flinttrade:openDoc", { detail: { path: result.path } }),
    );
    onClose();
  }

  if (!query.trim()) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-text-muted gap-1">
        <p className="text-sm">Search FlintTrade docs</p>
        <p className="text-xs opacity-60">Use ? prefix — e.g. ?order placement</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-text-muted gap-2">
        <Loader2 size={14} className="animate-spin" />
        <span className="text-sm">Searching docs…</span>
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="flex items-center justify-center py-10 text-text-muted">
        <p className="text-sm">No docs found for &ldquo;{query}&rdquo;</p>
      </div>
    );
  }

  return (
    <ul role="listbox" aria-label="Documentation results" className="overflow-y-auto max-h-80 py-1">
      {results.map((result, i) => (
        <li
          key={result.path}
          role="option"
          aria-selected={i === activeIndex}
          onMouseEnter={() => onActiveIndexChange(i)}
          onClick={() => handleSelect(result)}
          className={cn(
            "flex items-start gap-3 px-4 py-2.5 cursor-pointer select-none transition-colors",
            i === activeIndex ? "bg-glass-l3" : "hover:bg-glass-l2",
          )}
        >
          <FileText
            size={13}
            className={cn("shrink-0 mt-0.5", i === activeIndex ? "text-accent" : "text-text-muted")}
            aria-hidden="true"
          />
          <div className="flex-1 min-w-0">
            <span className="block text-sm text-text-primary leading-snug truncate">
              {result.title}
            </span>
            <span className="block text-xs text-text-muted leading-snug truncate mt-0.5">
              {result.snippet}
            </span>
            <span className="block text-[10px] text-text-muted/60 font-mono mt-0.5 truncate">
              docs/{result.path}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
