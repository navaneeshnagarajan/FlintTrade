/**
 * SymbolRow — individual watchlist entry with price, change, and sparkline.
 */

import { Sparkline } from "./Sparkline";
import { evaluateFormula, fmtCompact, fmtPrice, fmtPct, formulaLabel } from "./types";
import type { PartialQuote, WatchlistColumnId, WatchlistCustomFormula, WatchlistItem } from "./types";

export interface SymbolRowProps {
  item:        WatchlistItem;
  quote:       PartialQuote | null;
  sparkPrices: number[];
  visibleColumns: WatchlistColumnId[];
  formula: string;
  customFormulas?: WatchlistCustomFormula[];
  onSelect:    (item: WatchlistItem) => void;
  onRemove:    (e: React.MouseEvent, item: WatchlistItem) => void;
}

export function SymbolRow({
  item,
  quote,
  sparkPrices,
  visibleColumns,
  formula,
  customFormulas = [],
  onSelect,
  onRemove,
}: SymbolRowProps) {
  const ltp       = quote?.ltp    ?? quote?.close ?? null;
  const prevClose = quote?.prev_close ?? quote?.close ?? null;
  const chgAbs    = ltp != null && prevClose != null ? ltp - prevClose : null;
  const chgPct    = chgAbs != null && prevClose ? (chgAbs / prevClose) * 100 : null;
  const isUp      = chgAbs == null ? null : chgAbs >= 0;
  const changeColor = isUp === true ? "text-profit" : isUp === false ? "text-loss" : "text-text-muted";
  const visible = new Set(visibleColumns);
  const formulaValue = evaluateFormula(quote, formula, customFormulas);

  return (
    <button
      type="button"
      aria-label={item.symbol}
      className="w-full text-left flex items-center gap-2 px-2 py-1.5 hover:bg-surface-hover cursor-pointer border-b border-border-subtle transition-colors group"
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
      {visible.has("sparkline") && <Sparkline prices={sparkPrices} positive={isUp} />}

      {visible.has("volume") && (
        <div className="hidden min-w-12 shrink-0 flex-col items-end sm:flex">
          <span className="text-xxs text-text-muted leading-tight">Vol</span>
          <span className="text-xxs font-mono tabular-nums text-text-secondary leading-tight">
            {fmtCompact(quote?.volume)}
          </span>
        </div>
      )}

      {visible.has("changeAbs") && (
        <div className="hidden min-w-14 shrink-0 flex-col items-end md:flex">
          <span className="text-xxs text-text-muted leading-tight">Net</span>
          <span className={`text-xxs font-mono tabular-nums leading-tight ${changeColor}`}>
            {chgAbs != null ? fmtPrice(chgAbs) : "—"}
          </span>
        </div>
      )}

      {visible.has("formula") && (
        <div className="hidden min-w-16 shrink-0 flex-col items-end lg:flex">
          <span className="text-xxs text-text-muted leading-tight">{formulaLabel(formula, customFormulas)}</span>
          <span className="text-xxs font-mono tabular-nums text-text-secondary leading-tight">
            {formulaValue != null ? fmtPct(formulaValue) : "—"}
          </span>
        </div>
      )}

      {(visible.has("price") || visible.has("changePct")) && (
        <div className="flex min-w-16 shrink-0 flex-col items-end">
          {visible.has("price") && (
            <span className="text-xs font-mono tabular-nums font-semibold text-text-primary leading-tight">
              {fmtPrice(ltp)}
            </span>
          )}
          {visible.has("changePct") && (
            <span className={`text-xxs font-mono tabular-nums leading-tight ${changeColor}`}>
              {chgPct != null ? fmtPct(chgPct) : "—"}
            </span>
          )}
        </div>
      )}
    </button>
  );
}
