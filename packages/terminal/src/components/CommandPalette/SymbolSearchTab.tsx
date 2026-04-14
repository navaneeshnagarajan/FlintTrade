import { useEffect } from "react";
import { useAtomValue } from "jotai";
import { Search, BarChart3, ShoppingCart, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useSymbolSearch } from "./useSymbolSearch";

interface SymbolSearchTabProps {
  query: string;
  activeIndex: number;
  onSelectSymbol: (
    symbol: string,
    exchange: string,
    action: "chart" | "buy" | "sell" | "ai",
  ) => void;
  onActiveIndexChange: (index: number) => void;
}

function SymbolPrice({
  symbol,
  exchange,
}: {
  symbol: string;
  exchange: string;
}) {
  const tick = useAtomValue(tickAtomFamily(`${exchange}:${symbol}`));
  if (!tick) return <span className="text-xs text-text-muted">&mdash;</span>;

  const change = tick.change ?? 0;
  const pct = tick.pct ?? 0;
  const isPositive = change >= 0;

  return (
    <span
      className={cn(
        "text-right font-data text-xs tabular-nums",
        isPositive ? "text-profit" : "text-loss",
      )}
    >
      <span className="block">
        {(tick.ltp ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
      </span>
      <span className="block text-[10px]">
        {isPositive ? "+" : ""}
        {pct.toFixed(2)}%
      </span>
    </span>
  );
}

export function SymbolSearchTab({
  query,
  activeIndex,
  onSelectSymbol,
  onActiveIndexChange,
}: SymbolSearchTabProps) {
  const { results, isLoading } = useSymbolSearch(query);

  // Clamp activeIndex to list bounds
  useEffect(() => {
    if (results.length > 0 && activeIndex >= results.length) {
      onActiveIndexChange(results.length - 1);
    }
  }, [activeIndex, results.length, onActiveIndexChange]);

  if (!query || query.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-text-muted gap-2">
        <Search size={24} className="text-text-muted/50" />
        <p className="text-sm">
          Type to search stocks, ETFs, futures, options&hellip;
        </p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-text-muted">
        <p className="text-sm">Searching&hellip;</p>
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-text-muted gap-2">
        <Search size={24} className="text-text-muted/50" />
        <p className="text-sm">No symbols match &ldquo;{query}&rdquo;</p>
      </div>
    );
  }

  return (
    <ul role="listbox" aria-label="Symbol results" className="overflow-y-auto max-h-80 py-1">
      {results.map((r, i) => (
        <li
          key={`${r.exchange}:${r.symbol}`}
          role="option"
          aria-selected={i === activeIndex}
          onMouseEnter={() => onActiveIndexChange(i)}
          className={cn(
            "group flex items-center gap-3 px-4 py-2.5 cursor-pointer select-none transition-colors",
            i === activeIndex ? "bg-glass-l3" : "hover:bg-glass-l2",
          )}
        >
          <span
            className="flex-1 min-w-0"
            onClick={() => onSelectSymbol(r.symbol, r.exchange, "chart")}
          >
            <span className="block text-sm text-text-primary font-medium truncate">
              {r.symbol}
            </span>
            <span className="block text-[10px] text-text-muted uppercase">
              {r.exchange}
            </span>
          </span>

          <SymbolPrice symbol={r.symbol} exchange={r.exchange} />

          {/* Quick actions — visible on hover / active */}
          <span
            className={cn(
              "flex items-center gap-1 transition-opacity",
              i === activeIndex
                ? "opacity-100"
                : "opacity-0 group-hover:opacity-100",
            )}
          >
            <button
              type="button"
              aria-label={`Open ${r.symbol} chart`}
              onClick={() => onSelectSymbol(r.symbol, r.exchange, "chart")}
              className="p-1 rounded hover:bg-glass-l3 text-text-muted hover:text-text-primary"
            >
              <BarChart3 size={14} />
            </button>
            <button
              type="button"
              aria-label={`Buy ${r.symbol}`}
              onClick={() => onSelectSymbol(r.symbol, r.exchange, "buy")}
              className="p-1 rounded hover:bg-glass-l3 text-text-muted hover:text-profit"
            >
              <ShoppingCart size={14} />
            </button>
            <button
              type="button"
              aria-label={`Ask AI about ${r.symbol}`}
              onClick={() => onSelectSymbol(r.symbol, r.exchange, "ai")}
              className="p-1 rounded hover:bg-glass-l3 text-text-muted hover:text-[#8b5cf6]"
            >
              <MessageSquare size={14} />
            </button>
          </span>
        </li>
      ))}
    </ul>
  );
}
