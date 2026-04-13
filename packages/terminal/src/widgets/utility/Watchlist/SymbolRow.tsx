/**
 * SymbolRow — individual watchlist entry with price, change, and sparkline.
 */

import { Sparkline } from "./Sparkline";
import { fmtPrice, fmtPct } from "./types";
import type { WatchlistItem, PartialQuote } from "./types";

export interface SymbolRowProps {
  item:        WatchlistItem;
  quote:       PartialQuote | null;
  sparkPrices: number[];
  onSelect:    (item: WatchlistItem) => void;
  onRemove:    (e: React.MouseEvent, item: WatchlistItem) => void;
}

export function SymbolRow({ item, quote, sparkPrices, onSelect, onRemove }: SymbolRowProps) {
  const ltp       = quote?.ltp    ?? quote?.close ?? null;
  const prevClose = quote?.prev_close ?? quote?.close ?? null;
  const chgAbs    = ltp != null && prevClose != null ? ltp - prevClose : null;
  const chgPct    = chgAbs != null && prevClose ? (chgAbs / prevClose) * 100 : null;
  const isUp      = chgAbs == null ? null : chgAbs >= 0;
  const changeColor = isUp === true ? "text-profit" : isUp === false ? "text-loss" : "text-text-muted";

  return (
    <button
      type="button"
      aria-label={item.symbol}
      className="w-full text-left flex items-center gap-1.5 px-2 py-1.5 hover:bg-surface-hover cursor-pointer border-b border-border-subtle transition-colors group"
      onClick={() => onSelect(item)}
      onContextMenu={(e) => {
        e.preventDefault();
        onRemove(e, item);
      }}
      onKeyDown={(e) => {
        if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
          e.preventDefault();
          const rect = e.currentTarget.getBoundingClientRect();
          onRemove(
            {
              clientX: rect.left + rect.width / 2,
              clientY: rect.top + rect.height / 2,
              preventDefault: () => {},
            } as React.MouseEvent,
            item,
          );
        }
      }}
      title={`${item.symbol} · ${item.exchange} — right-click or Shift+F10 to remove`}
    >
      {/* Symbol + Exchange */}
      <div className="flex flex-col min-w-0 flex-1">
        <span className="text-xs font-medium text-text-primary font-mono leading-tight truncate">
          {item.symbol}
        </span>
        <span className="text-xxs text-text-muted leading-tight">{item.exchange}</span>
      </div>

      {/* Sparkline */}
      <Sparkline prices={sparkPrices} positive={isUp} />

      {/* Price block */}
      <div className="flex flex-col items-end shrink-0 min-w-16">
        <span className="text-xs font-mono tabular-nums font-semibold text-text-primary leading-tight">
          {fmtPrice(ltp)}
        </span>
        <span className={`text-xxs font-mono tabular-nums leading-tight ${changeColor}`}>
          {chgPct != null ? fmtPct(chgPct) : "—"}
        </span>
      </div>
    </button>
  );
}
