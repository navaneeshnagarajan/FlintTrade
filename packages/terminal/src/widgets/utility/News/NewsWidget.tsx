/**
 * NewsWidget — financial news feed for FlintTrade terminal.
 *
 * UI structure ready to consume a live news API once integrated.
 * Features:
 *   - News items with headline, source, timestamp, sentiment badge
 *   - Filter by sentiment: All / Bullish / Bearish
 *   - Keyword search
 *   - Empty state with configuration guidance
 *   - Dense dark layout matching FlintTrade terminal theme
 */

import { useState, useMemo } from "react";
import { Search, Newspaper, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type NewsSentiment = "bullish" | "bearish" | "neutral";

export interface NewsItem {
  id: string;
  headline: string;
  source: string;
  timestamp: number;
  sentiment: NewsSentiment;
  symbols: string[];
}

type SentimentFilter = "all" | NewsSentiment;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SENTIMENT_FILTERS: { label: string; value: SentimentFilter }[] = [
  { label: "All", value: "all" },
  { label: "Bullish", value: "bullish" },
  { label: "Bearish", value: "bearish" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtTimestamp(ts: number): string {
  const now = Date.now();
  const diff = Math.floor((now - ts) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(ts).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

// ---------------------------------------------------------------------------
// Sentiment badge
// ---------------------------------------------------------------------------

interface SentimentBadgeProps {
  sentiment: NewsSentiment;
}

function SentimentBadge({ sentiment }: SentimentBadgeProps) {
  if (sentiment === "bullish") {
    return (
      <Badge
        className="flex items-center gap-0.5 px-1.5 py-0 text-[9px] font-medium bg-profit/15 text-profit border-profit/30 rounded"
        variant="outline"
      >
        <TrendingUp size={8} />
        Bullish
      </Badge>
    );
  }
  if (sentiment === "bearish") {
    return (
      <Badge
        className="flex items-center gap-0.5 px-1.5 py-0 text-[9px] font-medium bg-loss/15 text-loss border-loss/30 rounded"
        variant="outline"
      >
        <TrendingDown size={8} />
        Bearish
      </Badge>
    );
  }
  return (
    <Badge
      className="flex items-center gap-0.5 px-1.5 py-0 text-[9px] font-medium bg-text-muted/10 text-text-muted border-border-default rounded"
      variant="outline"
    >
      <Minus size={8} />
      Neutral
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// News item row
// ---------------------------------------------------------------------------

interface NewsRowProps {
  item: NewsItem;
}

function NewsRow({ item }: NewsRowProps) {
  return (
    <div className="flex flex-col gap-1 px-2 py-2 border-b border-border-subtle hover:bg-surface-hover transition-colors cursor-default">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-text-primary leading-snug flex-1 min-w-0">
          {item.headline}
        </p>
        <SentimentBadge sentiment={item.sentiment} />
      </div>
      <div className="flex items-center gap-2">
        <span className="text-[9px] text-text-secondary font-medium">{item.source}</span>
        {item.symbols.length > 0 && (
          <>
            <span className="text-[9px] text-text-muted">·</span>
            <span className="text-[9px] text-text-muted font-mono">
              {item.symbols.join(", ")}
            </span>
          </>
        )}
        <span className="ml-auto text-[9px] text-text-muted">
          {fmtTimestamp(item.timestamp)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface NewsWidgetProps {
  /** Injected by widget host — unused directly */
  node?: unknown;
}

export default function NewsWidget({ node: _node }: NewsWidgetProps) {
  const [filter, setFilter] = useState<SentimentFilter>("all");
  const [query, setQuery] = useState("");

  // No live data yet — will be populated once news API is wired
  const items: NewsItem[] = [];

  const filtered = useMemo(() => {
    let result = items;
    if (filter !== "all") {
      result = result.filter((n) => n.sentiment === filter);
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      result = result.filter(
        (n) =>
          n.headline.toLowerCase().includes(q) ||
          n.source.toLowerCase().includes(q) ||
          n.symbols.some((s) => s.toLowerCase().includes(q)),
      );
    }
    return result;
  }, [items, filter, query]);

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">

      {/* HEADER */}
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <Newspaper size={11} className="text-text-muted shrink-0" />
        <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider">
          News
        </span>
        <div className="flex-1" />
        {/* Sentiment filter chips */}
        <div className="flex items-center gap-0.5">
          {SENTIMENT_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={[
                "px-2 py-0.5 text-[9px] font-medium rounded transition-colors",
                filter === f.value
                  ? "bg-primary/20 text-primary border border-primary/40"
                  : "text-text-muted hover:text-text-secondary hover:bg-surface-hover border border-transparent",
              ].join(" ")}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* SEARCH */}
      <div className="px-2 py-1 border-b border-border-subtle bg-surface-card shrink-0">
        <div className="relative">
          <Search
            size={10}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
          />
          <Input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search headlines, symbols..."
            className="h-6 pl-6 pr-2 text-[10px] bg-surface-hover border-border-default text-text-primary placeholder-text-muted rounded focus-visible:ring-1 focus-visible:ring-primary/50"
          />
        </div>
      </div>

      {/* NEWS LIST */}
      {filtered.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 px-4 text-center">
          <Newspaper size={28} className="text-text-muted" />
          <div>
            <p className="text-xs text-text-secondary">No news to display</p>
            <p className="text-[10px] text-text-muted mt-1 leading-relaxed max-w-48">
              Connect a news source in Settings to see live market news
            </p>
          </div>
        </div>
      ) : (
        <ScrollArea className="flex-1">
          {filtered.map((item) => (
            <NewsRow key={item.id} item={item} />
          ))}
        </ScrollArea>
      )}
    </div>
  );
}
