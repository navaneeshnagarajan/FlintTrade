/**
 * NewsWidget — live financial news feed for FlintTrade terminal.
 *
 * Fetches real RSS feeds via rss2json public service (no CORS issues, no API key).
 * Sources: MoneyControl, Economic Times Markets, LiveMint Markets.
 * Sentiment tagging is rule-based (keyword scan on title) — no AI API key needed.
 * Auto-refreshes every 5 minutes. Handles errors gracefully.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  Search,
  Newspaper,
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  AlertCircle,
  ExternalLink,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

/** CORS proxy + RSS-to-JSON conversion */
const CORS_PROXY = "https://api.allorigins.win/raw?url=";

interface FeedSource {
  name: string;
  url: string;
}

const FEEDS: FeedSource[] = [
  {
    name: "MoneyControl",
    url: "https://www.moneycontrol.com/rss/latestnews.xml",
  },
  {
    name: "ET Markets",
    url: "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
  },
  {
    name: "LiveMint",
    url: "https://www.livemint.com/rss/markets",
  },
];

// ---------------------------------------------------------------------------
// Sentiment rules (rule-based, no API key)
// ---------------------------------------------------------------------------

const BULLISH_KEYWORDS = [
  "rally",
  "surge",
  "gain",
  "gains",
  "buy",
  "bullish",
  "record high",
  "upgrade",
  "rise",
  "rises",
  "rose",
  "high",
  "highs",
  "soar",
  "soars",
  "jump",
  "jumps",
  "positive",
  "growth",
  "profit",
  "strong",
  "outperform",
  "beat",
  "beats",
  "boost",
  "boosts",
  "upside",
  "recovery",
  "recovers",
  "rebound",
];

const BEARISH_KEYWORDS = [
  "crash",
  "fall",
  "falls",
  "fell",
  "drop",
  "drops",
  "sell",
  "bearish",
  "downgrade",
  "slump",
  "slumps",
  "decline",
  "declines",
  "loss",
  "losses",
  "weak",
  "weakness",
  "underperform",
  "miss",
  "misses",
  "concern",
  "risk",
  "risks",
  "plunge",
  "plunges",
  "tumble",
  "tumbles",
  "down",
  "negative",
  "warning",
];

export type NewsSentiment = "bullish" | "bearish" | "neutral";

function classifySentiment(title: string): NewsSentiment {
  const lower = title.toLowerCase();
  let bullishScore = 0;
  let bearishScore = 0;

  for (const word of BULLISH_KEYWORDS) {
    if (lower.includes(word)) bullishScore++;
  }
  for (const word of BEARISH_KEYWORDS) {
    if (lower.includes(word)) bearishScore++;
  }

  if (bullishScore > bearishScore) return "bullish";
  if (bearishScore > bullishScore) return "bearish";
  return "neutral";
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NewsItem {
  id: string;
  headline: string;
  link: string;
  source: string;
  /** Unix timestamp in ms */
  timestamp: number;
  sentiment: NewsSentiment;
}

type SentimentFilter = "all" | NewsSentiment;


// ---------------------------------------------------------------------------
// RSS fetch helpers
// ---------------------------------------------------------------------------

function buildFeedUrl(rssUrl: string): string {
  return `${CORS_PROXY}${encodeURIComponent(rssUrl)}`;
}

/** Parse RSS XML items from raw text */
function parseRssXml(xml: string): Array<{ title: string; link: string; pubDate: string }> {
  const items: Array<{ title: string; link: string; pubDate: string }> = [];
  const itemRegex = /<item>([\s\S]*?)<\/item>/gi;
  let match: RegExpExecArray | null;
  while ((match = itemRegex.exec(xml)) !== null) {
    const block = match[1];
    const title = block.match(/<title><!\[CDATA\[(.*?)\]\]>|<title>(.*?)<\/title>/)?.[1] ?? block.match(/<title>(.*?)<\/title>/)?.[1] ?? "";
    const link = block.match(/<link>(.*?)<\/link>/)?.[1] ?? "";
    const pubDate = block.match(/<pubDate>(.*?)<\/pubDate>/)?.[1] ?? "";
    if (title && link) items.push({ title, link, pubDate });
  }
  return items;
}

async function fetchFeed(source: FeedSource): Promise<NewsItem[]> {
  const url = buildFeedUrl(source.url);
  const res = await fetch(url, { signal: AbortSignal.timeout(10_000) });

  if (!res.ok) {
    throw new Error(`HTTP ${res.status} for ${source.name}`);
  }

  const xml = await res.text();
  const parsed = parseRssXml(xml);

  return parsed.slice(0, 20).map((item) => {
    const ts = item.pubDate ? new Date(item.pubDate).getTime() : Date.now();
    return {
      id: `${source.name}-${item.link}`,
      headline: item.title.trim(),
      link: item.link,
      source: source.name,
      timestamp: isNaN(ts) ? Date.now() : ts,
      sentiment: classifySentiment(item.title),
    };
  });
}

async function fetchAllFeeds(): Promise<NewsItem[]> {
  const results = await Promise.allSettled(FEEDS.map(fetchFeed));

  const items: NewsItem[] = [];
  for (const r of results) {
    if (r.status === "fulfilled") {
      items.push(...r.value);
    }
  }

  // De-duplicate by headline text (same story across sources)
  const seen = new Set<string>();
  const deduped: NewsItem[] = [];
  for (const item of items) {
    const key = item.headline.toLowerCase().slice(0, 60);
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(item);
    }
  }

  // Sort newest first
  deduped.sort((a, b) => b.timestamp - a.timestamp);
  return deduped;
}

// ---------------------------------------------------------------------------
// Time formatting (IST-aware)
// ---------------------------------------------------------------------------

function fmtTimeAgo(ts: number): string {
  const now = Date.now();
  const diff = Math.floor((now - ts) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(ts).toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
  });
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface SentimentBadgeProps {
  sentiment: NewsSentiment;
}

function SentimentBadge({ sentiment }: SentimentBadgeProps) {
  if (sentiment === "bullish") {
    return (
      <Badge
        className="flex items-center gap-0.5 px-1.5 py-0 text-[9px] font-medium bg-profit/15 text-profit border-profit/30 rounded shrink-0"
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
        className="flex items-center gap-0.5 px-1.5 py-0 text-[9px] font-medium bg-loss/15 text-loss border-loss/30 rounded shrink-0"
        variant="outline"
      >
        <TrendingDown size={8} />
        Bearish
      </Badge>
    );
  }
  return (
    <Badge
      className="flex items-center gap-0.5 px-1.5 py-0 text-[9px] font-medium bg-text-muted/10 text-text-muted border-border-default rounded shrink-0"
      variant="outline"
    >
      <Minus size={8} />
      Neutral
    </Badge>
  );
}

interface SourceBadgeProps {
  source: string;
}

function SourceBadge({ source }: SourceBadgeProps) {
  return (
    <Badge
      className="px-1.5 py-0 text-[8px] font-medium bg-surface-hover border-border-subtle text-text-muted rounded shrink-0"
      variant="outline"
    >
      {source}
    </Badge>
  );
}

interface NewsRowProps {
  item: NewsItem;
}

function NewsRow({ item }: NewsRowProps) {
  return (
    <div className="flex flex-col gap-1 px-2 py-2 border-b border-border-subtle hover:bg-surface-hover transition-colors group">
      <div className="flex items-start justify-between gap-2">
        <a
          href={item.link}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-text-primary leading-snug flex-1 min-w-0 hover:text-primary transition-colors cursor-pointer group-hover:underline underline-offset-2 decoration-border-subtle"
        >
          {item.headline}
        </a>
        <div className="flex items-center gap-1 shrink-0 mt-0.5">
          <SentimentBadge sentiment={item.sentiment} />
          <a
            href={item.link}
            target="_blank"
            rel="noopener noreferrer"
            className="opacity-0 group-hover:opacity-100 transition-opacity text-text-muted hover:text-text-secondary"
            aria-label="Open article"
          >
            <ExternalLink size={9} />
          </a>
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <SourceBadge source={item.source} />
        <span className="ml-auto text-[9px] text-text-muted">
          {fmtTimeAgo(item.timestamp)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sentiment filter tab config
// ---------------------------------------------------------------------------

const SENTIMENT_FILTERS: { label: string; value: SentimentFilter }[] = [
  { label: "All", value: "all" },
  { label: "Bullish", value: "bullish" },
  { label: "Bearish", value: "bearish" },
  { label: "Neutral", value: "neutral" },
];

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface NewsWidgetProps {
  /** Injected by widget host — unused directly */
  node?: unknown;
}

type FetchStatus = "idle" | "loading" | "success" | "error";

export default function NewsWidget({ node: _node }: NewsWidgetProps) {
  const [filter, setFilter] = useState<SentimentFilter>("all");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<NewsItem[]>([]);
  const [status, setStatus] = useState<FetchStatus>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const data = await fetchAllFeeds();
      setItems(data);
      setLastUpdated(Date.now());
      setStatus(data.length > 0 ? "success" : "error");
      if (data.length === 0) {
        setErrorMsg("No articles returned from feeds.");
      } else {
        setErrorMsg("");
      }
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Unknown error");
    }
  }, []);

  // Initial load + auto-refresh
  useEffect(() => {
    void load();

    timerRef.current = setInterval(() => {
      void load();
    }, REFRESH_INTERVAL_MS);

    return () => {
      if (timerRef.current !== null) {
        clearInterval(timerRef.current);
      }
    };
  }, [load]);

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
          n.source.toLowerCase().includes(q),
      );
    }

    return result;
  }, [items, filter, query]);

  // Sentiment counts for badge
  const counts = useMemo(() => {
    const c = { bullish: 0, bearish: 0, neutral: 0 };
    for (const item of items) {
      c[item.sentiment]++;
    }
    return c;
  }, [items]);

  const isLoading = status === "loading";
  const hasError = status === "error" && items.length === 0;

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">

      {/* HEADER */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <Newspaper size={11} className="text-text-muted shrink-0" />
        <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider">
          News
        </span>

        {/* Auto-refresh spinner */}
        {isLoading && (
          <RefreshCw size={10} className="text-primary animate-spin shrink-0" />
        )}

        {lastUpdated !== null && !isLoading && (
          <span className="text-[9px] text-text-muted">
            {fmtTimeAgo(lastUpdated)}
          </span>
        )}

        <div className="flex-1" />

        {/* Manual refresh */}
        <Button
          variant="ghost"
          size="icon-xs"
          onClick={() => void load()}
          disabled={isLoading}
          title="Refresh news"
          className="h-5 w-5 text-text-muted hover:text-text-secondary"
        >
          <RefreshCw size={9} className={isLoading ? "animate-spin" : ""} />
        </Button>
      </div>

      {/* SENTIMENT FILTER TABS */}
      <div className="flex items-center gap-0.5 px-2 py-1 border-b border-border-subtle bg-surface-card shrink-0">
        {SENTIMENT_FILTERS.map((f) => {
          const count =
            f.value === "all"
              ? items.length
              : counts[f.value as NewsSentiment];
          return (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={[
                "flex items-center gap-1 px-2 py-0.5 text-[9px] font-medium rounded transition-colors",
                filter === f.value
                  ? "bg-primary/20 text-primary border border-primary/40"
                  : "text-text-muted hover:text-text-secondary hover:bg-surface-hover border border-transparent",
              ].join(" ")}
            >
              {f.label}
              {items.length > 0 && (
                <span className="opacity-60">{count}</span>
              )}
            </button>
          );
        })}
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
            placeholder="Search headlines, sources..."
            className="h-6 pl-6 pr-2 text-[10px] bg-surface-hover border-border-default text-text-primary placeholder-text-muted rounded focus-visible:ring-1 focus-visible:ring-primary/50"
          />
        </div>
      </div>

      {/* CONTENT AREA */}
      {hasError ? (
        // Error state — feeds unreachable or returned nothing
        <div className="flex-1 flex flex-col items-center justify-center gap-3 px-4 text-center">
          <AlertCircle size={24} className="text-loss" />
          <div>
            <p className="text-xs text-text-secondary">Unable to fetch news</p>
            <p className="text-[10px] text-text-muted mt-1 leading-relaxed max-w-52">
              {errorMsg || "Could not reach RSS feeds. Check your internet connection."}
            </p>
          </div>
          <Button
            variant="outline"
            size="xs"
            onClick={() => void load()}
            disabled={isLoading}
            className="text-[10px] h-6"
          >
            <RefreshCw size={9} className={isLoading ? "animate-spin" : ""} />
            Retry
          </Button>
        </div>
      ) : isLoading && items.length === 0 ? (
        // First-load skeleton
        <div className="flex-1 flex flex-col items-center justify-center gap-2">
          <RefreshCw size={20} className="text-text-muted animate-spin" />
          <p className="text-[10px] text-text-muted">Loading news...</p>
        </div>
      ) : filtered.length === 0 ? (
        // Empty filtered state
        <div className="flex-1 flex flex-col items-center justify-center gap-3 px-4 text-center">
          <Newspaper size={24} className="text-text-muted" />
          <div>
            <p className="text-xs text-text-secondary">No news to display</p>
            <p className="text-[10px] text-text-muted mt-1 max-w-48 leading-relaxed">
              {query.trim()
                ? `No results for "${query}"`
                : "No articles match the selected filter"}
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
