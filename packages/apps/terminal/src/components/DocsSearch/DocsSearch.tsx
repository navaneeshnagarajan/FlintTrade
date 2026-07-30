/**
 * DocsSearch — In-app documentation search modal.
 *
 * Searches FlintTrade's docs/ markdown files via the backend full-text index.
 * Backend: GET /ft-api/v1/docs/search?q=<query>
 *
 * Command Palette integration: triggered by "?" prefix in Ctrl+K.
 * Also accessible directly as a standalone modal.
 *
 * Results show the document title, a snippet with highlighted terms,
 * and the file path. Clicking a result opens the doc in the DocReader pane.
 */

import {
  useState,
  useEffect,
  useCallback,
  useRef,
} from "react";
import { DocsSearchResponseSchema } from "@/lib/schemas/ftApi";
import {
  Book,
  FileText,
  Loader2,
  Search,
  X,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DocSearchResult {
  /** Relative path within docs/ e.g. "guides/order-placement.md" */
  path: string;
  /** Document title (first # heading or filename) */
  title: string;
  /** Short snippet with matched terms */
  snippet: string;
  /** TF-IDF relevance score (0–1) */
  score: number;
}

export interface DocsSearchResponse {
  query: string;
  results: DocSearchResult[];
  total: number;
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

export async function searchDocs(
  query: string,
  signal?: AbortSignal,
): Promise<DocSearchResult[]> {
  if (!query.trim()) return [];
  try {
    const params = new URLSearchParams({ q: query.trim() });
    const res = await fetch(`/ft-api/v1/docs/search?${params.toString()}`, {
      signal,
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) return [];
    const raw: unknown = await res.json();
    const result = DocsSearchResponseSchema.safeParse(raw);
    if (!result.success) {
      console.error("[DocsSearch] /docs/search shape mismatch:", result.error.issues);
      return [];
    }
    return result.data.results as DocSearchResult[];
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return [];
    return [];
  }
}

// ---------------------------------------------------------------------------
// Snippet highlighter
// ---------------------------------------------------------------------------

function highlightSnippet(snippet: string, query: string): React.ReactNode {
  if (!query.trim()) return <>{snippet}</>;
  const terms = query
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (terms.length === 0) return <>{snippet}</>;

  const pattern = new RegExp(`(${terms.join("|")})`, "gi");
  const parts = snippet.split(pattern);

  return (
    <>
      {parts.map((part, i) =>
        pattern.test(part) ? (
          <mark
            key={i}
            className="bg-accent/20 text-accent rounded-sm not-italic font-medium"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Result item
// ---------------------------------------------------------------------------

interface ResultItemProps {
  id: string;
  result: DocSearchResult;
  isActive: boolean;
  query: string;
  onSelect: (result: DocSearchResult) => void;
  onMouseEnter: () => void;
}

function ResultItem({
  id,
  result,
  isActive,
  query,
  onSelect,
  onMouseEnter,
}: ResultItemProps) {
  return (
    <li
      id={id}
      role="option"
      aria-selected={isActive}
      onClick={() => onSelect(result)}
      onMouseEnter={onMouseEnter}
      className={cn(
        "flex items-start gap-3 px-4 py-3 cursor-pointer select-none transition-colors",
        isActive ? "bg-glass-l3" : "hover:bg-glass-l2",
      )}
    >
      <FileText
        size={14}
        className={cn(
          "shrink-0 mt-0.5",
          isActive ? "text-accent" : "text-text-muted",
        )}
        aria-hidden="true"
      />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-text-primary font-medium leading-snug truncate">
          {result.title}
        </p>
        <p className="text-xs text-text-muted leading-relaxed mt-0.5 line-clamp-2">
          {highlightSnippet(result.snippet, query)}
        </p>
        <p className="text-[10px] text-text-muted/60 mt-1 font-mono truncate">
          docs/{result.path}
        </p>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

export interface DocsSearchProps {
  isOpen: boolean;
  onClose: () => void;
  /** Initial query, e.g. passed from Command Palette "?" prefix */
  initialQuery?: string;
  /** Called when user selects a result — consumer opens the doc */
  onSelectDoc?: (result: DocSearchResult) => void;
}

export default function DocsSearch({
  isOpen,
  onClose,
  initialQuery = "",
  onSelectDoc,
}: DocsSearchProps) {
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<DocSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Reset and focus on open
  useEffect(() => {
    if (isOpen) {
      setQuery(initialQuery);
      setResults([]);
      setActiveIndex(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [isOpen, initialQuery]);

  // Debounced search
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setLoading(false);
      return;
    }

    const timer = setTimeout(async () => {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setLoading(true);
      const found = await searchDocs(query, abortRef.current.signal);
      setResults(found);
      setActiveIndex(0);
      setLoading(false);
    }, 250);

    return () => {
      clearTimeout(timer);
    };
  }, [query]);

  // Declared before the keyboard handler that calls it, so that handler can
  // name it as a dependency: with `handleSelect` omitted, an `onSelectDoc`
  // change alone left Enter dispatching to the previous selection handler.
  const handleSelect = useCallback(
    (result: DocSearchResult) => {
      if (onSelectDoc) {
        onSelectDoc(result);
      } else {
        // Default: open docs in a new tab or dispatch event
        window.dispatchEvent(
          new CustomEvent("flinttrade:openDoc", { detail: { path: result.path } }),
        );
      }
      onClose();
    },
    [onSelectDoc, onClose],
  );

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((p) => Math.min(p + 1, results.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((p) => Math.max(0, p - 1));
        return;
      }
      if (e.key === "Enter" && results[activeIndex]) {
        e.preventDefault();
        handleSelect(results[activeIndex]);
      }
    },
    [results, activeIndex, onClose, handleSelect],
  );

  const handleClear = useCallback(() => {
    setQuery("");
    setResults([]);
    inputRef.current?.focus();
  }, []);

  const showEmpty = !loading && query.trim() && results.length === 0;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        className="sm:max-w-xl max-h-[80vh] flex flex-col bg-surface-card border-border-default p-0 animate-fade-in-scale"
        aria-describedby="docs-search-desc"
      >
        <DialogHeader className="px-4 pt-4 pb-0 border-b border-border-default">
          <div className="flex items-center gap-2 pb-3">
            <Book
              className="w-4 h-4 text-text-muted shrink-0"
              aria-hidden="true"
            />
            <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
              Search Docs
            </DialogTitle>
          </div>
          <p id="docs-search-desc" className="sr-only">
            Search FlintTrade documentation. Use arrow keys to navigate results.
          </p>

          {/* Search input */}
          <div className="relative pb-3">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted pointer-events-none"
              aria-hidden="true"
            />
            <Input
              ref={inputRef}
              type="search"
              role="combobox"
              aria-expanded={results.length > 0}
              aria-controls="docs-search-listbox"
              aria-activedescendant={
                results[activeIndex]
                  ? `docs-result-${activeIndex}`
                  : undefined
              }
              aria-label="Search documentation"
              placeholder="Search docs… (e.g. order placement, backtesting)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              className="pl-9 h-9 text-sm bg-surface-base border-border-default placeholder:text-text-muted focus-visible:ring-accent/40"
              autoComplete="off"
              spellCheck={false}
            />
            {loading && (
              <Loader2
                className="absolute right-8 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted animate-spin"
                aria-hidden="true"
              />
            )}
            {query && !loading && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={handleClear}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </DialogHeader>

        {/* Results */}
        <div className="overflow-y-auto flex-1 min-h-0">
          {/* Empty state — no query */}
          {!query.trim() && !loading && (
            <div className="flex flex-col items-center justify-center py-12 gap-2 text-text-muted">
              <Book className="w-8 h-8 opacity-30" aria-hidden="true" />
              <p className="text-sm">Type to search FlintTrade docs</p>
              <p className="text-xs opacity-60">
                Try &ldquo;order placement&rdquo;, &ldquo;backtesting&rdquo;,
                &ldquo;options chain&rdquo;
              </p>
            </div>
          )}

          {/* No results */}
          {showEmpty && (
            <div className="flex flex-col items-center justify-center py-12 gap-2 text-text-muted">
              <Search className="w-8 h-8 opacity-30" aria-hidden="true" />
              <p className="text-sm">
                No docs found for &ldquo;{query.trim()}&rdquo;
              </p>
            </div>
          )}

          {/* Results list */}
          {results.length > 0 && (
            <ul
              id="docs-search-listbox"
              role="listbox"
              aria-label="Documentation search results"
              className="py-1"
            >
              {results.map((result, i) => (
                <ResultItem
                  key={`${result.path}-${i}`}
                  id={`docs-result-${i}`}
                  result={result}
                  isActive={i === activeIndex}
                  query={query}
                  onSelect={handleSelect}
                  onMouseEnter={() => setActiveIndex(i)}
                />
              ))}
            </ul>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-4 px-4 py-2 border-t border-border-default bg-glass-l1">
          <div className="flex items-center gap-4">
            <FooterHint keys="↑↓" label="Navigate" />
            <FooterHint keys="↵" label="Open doc" />
            <FooterHint keys="Esc" label="Close" />
          </div>
          {results.length > 0 && (
            <span className="text-[10px] text-text-muted">
              {results.length} result{results.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Footer hint
// ---------------------------------------------------------------------------

function FooterHint({ keys, label }: { keys: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-text-muted">
      <kbd className="font-mono text-[10px] bg-glass-l2 border border-glass-l1 rounded px-1 py-0.5 leading-none">
        {keys}
      </kbd>
      <span>{label}</span>
    </span>
  );
}
