/**
 * BasketPanel — multi-leg basket management panel.
 * Displays selected strikes, allows removal, and fires Buy All / Sell All.
 */

import { ShoppingBasket, X } from "lucide-react";
import type { BasketItem, OrderParams } from "./types";
import { NUM0, fmtLtp } from "./formatters";
import { DisabledReason } from "@/components/DisabledActionButton";
import { OrderStatusUnknownLine } from "@/components/orders/OrderStatusUnknownLine";
import { ORDER_SENT_WAITING, ORDER_STATUS_UNKNOWN } from "@/lib/operatorIncident";

interface BasketPanelProps {
  basket: BasketItem[];
  onRemove: (item: BasketItem) => void;
  onClear: () => void;
  onOrder: (params: OrderParams) => void;
  /** A place request is in flight, or a lost one is not settled yet. */
  locked?: boolean;
  /** A lost place request in this basket is not settled yet. */
  statusUnknown?: boolean;
}

export default function BasketPanel({
  basket,
  onRemove,
  onClear,
  onOrder,
  locked = false,
  statusUnknown = false,
}: BasketPanelProps) {
  const disabledReason = statusUnknown ? ORDER_STATUS_UNKNOWN : locked ? ORDER_SENT_WAITING : null;
  return (
    <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5">
      <div className="flex items-center gap-2 mb-1">
        <ShoppingBasket size={11} className="text-accent" />
        <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">
          Basket ({basket.length})
        </span>
        {basket.length > 0 && (
          <button
            onClick={onClear}
            className="ml-auto text-xxs text-text-muted hover:text-loss transition-colors"
          >
            Clear all
          </button>
        )}
      </div>

      {basket.length === 0 ? (
        <p className="text-xs text-text-muted">
          Click +B on any strike to add it here.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1 mb-1.5">
            {basket.map((item) => (
              <div
                key={`${item.symbol}-${item.exchange}-${item.expiry}-${item.strike}-${item.optionType}`}
                className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs font-mono ${
                  item.optionType === "CE"
                    ? "bg-loss/10 border-loss/30 text-loss"
                    : "bg-profit/10 border-profit/30 text-profit"
                }`}
              >
                <span className="font-semibold">{item.symbol} {NUM0.format(item.strike)} {item.optionType}</span>
                {item.ltp != null && (
                  <span className="text-text-muted">@ {fmtLtp(item.ltp)}</span>
                )}
                <button
                  onClick={() => onRemove(item)}
                  className="ml-0.5 text-text-muted hover:text-text-primary transition-colors"
                  aria-label="Remove"
                >
                  <X size={9} />
                </button>
              </div>
            ))}
          </div>

          <div className="flex gap-1.5 pt-1 border-t border-border-default">
            <DisabledReason reason={disabledReason}>
              <button
                disabled={locked}
                onClick={() =>
                  basket.forEach((item) =>
                    onOrder({
                      symbol: item.symbol,
                      exchange: item.exchange,
                      strike: item.strike,
                      optionType: item.optionType,
                      expiry: item.expiry,
                      action: "B",
                      ltp: item.ltp,
                    })
                  )
                }
                className="px-3 py-0.5 text-xs font-semibold rounded disabled:pointer-events-none bg-profit/10 text-profit hover:bg-profit/20 border border-profit/30 hover:border-profit/60 transition-colors"
              >
                Buy All
              </button>
            </DisabledReason>
            <DisabledReason reason={disabledReason}>
              <button
                disabled={locked}
                onClick={() =>
                  basket.forEach((item) =>
                    onOrder({
                      symbol: item.symbol,
                      exchange: item.exchange,
                      strike: item.strike,
                      optionType: item.optionType,
                      expiry: item.expiry,
                      action: "S",
                      ltp: item.ltp,
                    })
                  )
                }
                className="px-3 py-0.5 text-xs font-semibold rounded disabled:pointer-events-none bg-loss/10 text-loss hover:bg-loss/20 border border-loss/30 hover:border-loss/60 transition-colors"
              >
                Sell All
              </button>
            </DisabledReason>
          </div>
          {/* Reserved, so Buy All and the chain below never move when the line appears. */}
          <div data-testid="basket-status-slot" className="min-h-9 pt-1">
            {statusUnknown ? <OrderStatusUnknownLine /> : null}
          </div>
        </>
      )}
    </div>
  );
}
