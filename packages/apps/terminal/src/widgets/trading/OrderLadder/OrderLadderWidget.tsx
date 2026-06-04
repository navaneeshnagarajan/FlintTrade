/**
 * OrderLadderWidget — DOM-style price ladder for rapid order entry.
 *
 * Features:
 *   - ±20 price ticks centred on the live LTP for the selected instrument
 *   - Bid qty | Price | Ask qty columns
 *   - Your pending orders highlighted with cancel button
 *   - Click bid side → SELL LIMIT, click ask side → BUY LIMIT
 *   - Configurable tick size and quantity
 *   - Blocks order entry in explore mode
 *
 * Data sourcing & safety:
 *   - The ladder centre is taken from the live LTP (Jotai tick atom). When no
 *     live price is available the rows are disabled so a click can never submit
 *     a LIMIT order at a made-up price.
 *   - In Explore mode the ladder shows clearly-labelled demo data so the layout
 *     can be previewed without a broker connection. Demo bid/ask volumes are
 *     never shown outside Explore mode.
 */

import { useState, useMemo, useCallback, useEffect, memo } from "react";
import { useAtomValue } from "jotai";
import { ArrowUpDown, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useModeStore } from "@/stores/modeStore";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { placeOrder, cancelOrder } from "@/services/api";

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

type Side = "buy" | "sell";
interface PendingOrder { orderId: string; side: Side; price: number; qty: number; status: "pending" | "cancelling" }
interface LadderLevel  { price: number; bidQty: number; askQty: number }

const TICK_OPTIONS = [0.05, 0.25, 0.5, 1, 5] as const;
type TickSize = (typeof TICK_OPTIONS)[number];

const LEVELS_ABOVE = 20;
const LEVELS_BELOW = 20;
const DEFAULT_QTY   = 25;
const SAMPLE_PRICE  = 22150.25;

// ---------------------------------------------------------------------------
// Ladder construction
// ---------------------------------------------------------------------------

/**
 * Build the ±20-tick price ladder around a centre price.
 *
 * @param centerPrice - Centre of the ladder (the live LTP, or the demo price in Explore mode).
 * @param tickSize    - Spacing between adjacent price levels.
 * @param demoVolumes - When true, populate fabricated bid/ask volumes for the Explore
 *                      preview. When false (live mode) volumes are left at zero so no
 *                      made-up depth is ever shown alongside real prices.
 */
export function generateLadderLevels(centerPrice: number, tickSize: number, demoVolumes = true): LadderLevel[] {
  const levels: LadderLevel[] = [];
  for (let i = LEVELS_ABOVE; i >= -LEVELS_BELOW; i--) {
    const price = parseFloat((centerPrice + i * tickSize).toFixed(2));
    levels.push({
      price,
      bidQty: demoVolumes && i < 0 ? Math.round(Math.random() * 800 + 100) : 0,
      askQty: demoVolumes && i > 0 ? Math.round(Math.random() * 800 + 100) : 0,
    });
  }
  return levels;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fmtQty   = (q: number) => !q ? "" : q >= 1000 ? `${(q / 1000).toFixed(1)}K` : String(q);
const fmtPrice = (p: number) => p.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const barW     = (qty: number, max: number) => !qty || !max ? "0%" : `${Math.min(100, (qty / max) * 100).toFixed(1)}%`;

// ---------------------------------------------------------------------------
// Level row
// ---------------------------------------------------------------------------

function LevelRow({ level, isCenter, order, maxQty, qty, disabled, onBid, onAsk, onCancel }: {
  level: LadderLevel; isCenter: boolean; order?: PendingOrder;
  maxQty: number; qty: number; disabled: boolean;
  onBid: (p: number) => void; onAsk: (p: number) => void; onCancel: (id: string) => void;
}) {
  return (
    <div className={cn("flex items-center h-6 border-b border-border-subtle last:border-0",
      isCenter && "bg-accent/8", order && "bg-warning/5")}
      aria-label={`Price level ${fmtPrice(level.price)}`}>
      <Button variant="ghost" onClick={() => onBid(level.price)} disabled={disabled}
        className={cn("relative flex items-center justify-end h-full flex-1 px-1.5 text-xxs font-mono transition-colors select-none rounded-none",
          disabled ? "cursor-not-allowed" : "hover:bg-loss/15",
          level.bidQty ? "text-profit" : "text-transparent")}
        title={disabled ? "Connect a broker to place orders" : `SELL ${qty} @ ${fmtPrice(level.price)}`}
        aria-label={level.bidQty ? `Sell ${qty} at ${fmtPrice(level.price)}: ${level.bidQty} bids` : `Place sell at ${fmtPrice(level.price)}`}>
        {!!level.bidQty && <div className="absolute right-0 inset-y-0 bg-profit/15" style={{ width: barW(level.bidQty, maxQty) }} aria-hidden="true" />}
        <span className="relative z-10">{fmtQty(level.bidQty)}</span>
      </Button>

      <div className={cn("w-24 shrink-0 flex items-center justify-center gap-1 text-xxs font-mono font-semibold tabular-nums",
        isCenter ? "text-warning" : "text-text-primary")}>
        {fmtPrice(level.price)}
        {order && (
          <span className="flex items-center gap-0.5">
            <span className={cn("text-xxs font-bold", order.side === "buy" ? "text-profit" : "text-loss")}>
              {order.side === "buy" ? "B" : "S"}{order.qty}
            </span>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onCancel(order.orderId)}
              disabled={order.status === "cancelling"}
              className="h-auto w-auto p-0 text-text-muted hover:text-loss disabled:opacity-40 transition-colors"
              aria-label={`Cancel ${order.side} order at ${fmtPrice(level.price)}`}
            >
              {order.status === "cancelling" ? <Loader2 size={9} className="animate-spin" /> : <X size={9} />}
            </Button>
          </span>
        )}
      </div>

      <Button variant="ghost" onClick={() => onAsk(level.price)} disabled={disabled}
        className={cn("relative flex items-center h-full flex-1 px-1.5 text-xxs font-mono transition-colors select-none rounded-none",
          disabled ? "cursor-not-allowed" : "hover:bg-profit/15",
          level.askQty ? "text-loss" : "text-transparent")}
        title={disabled ? "Connect a broker to place orders" : `BUY ${qty} @ ${fmtPrice(level.price)}`}
        aria-label={level.askQty ? `Buy ${qty} at ${fmtPrice(level.price)}: ${level.askQty} asks` : `Place buy at ${fmtPrice(level.price)}`}>
        {!!level.askQty && <div className="absolute left-0 inset-y-0 bg-loss/15" style={{ width: barW(level.askQty, maxQty) }} aria-hidden="true" />}
        <span className="relative z-10">{fmtQty(level.askQty)}</span>
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

interface Props { symbol?: string; exchange?: string }

function OrderLadderWidget({ symbol = "NIFTY", exchange = "NSE" }: Props) {
  const mode  = useModeStore((s) => s.mode);
  const isExplore = mode === "explore";
  const track = useTrackBehavior();

  // Live LTP for the selected instrument — drives the ladder centre.
  // Key format: "{exchange}:{symbol}" — matches the WS bridge and REST fallback atom keys.
  const tick = useAtomValue(tickAtomFamily(`${exchange}:${symbol}`));
  const liveLtp = tick?.ltp && tick.ltp > 0 ? tick.ltp : null;

  const [tickSize, setTickSize] = useState<TickSize>(0.25);
  const [qty, setQty] = useState(DEFAULT_QTY);
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([]);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  useEffect(() => { track("trade", "widget_view_order_ladder"); }, [track]);

  // The ladder is only safe to trade on when we have a real centre price:
  // either a live LTP, or the labelled demo price shown in Explore mode.
  const centrePrice  = isExplore ? SAMPLE_PRICE : liveLtp;
  const hasUsablePrice = centrePrice != null;

  // Demo volumes are populated for the Explore preview only — never alongside
  // a real live price, where fabricated depth would be misleading.
  const levels  = useMemo(
    () => centrePrice != null ? generateLadderLevels(centrePrice, tickSize, isExplore) : [],
    [centrePrice, tickSize, isExplore],
  );
  const maxQty  = useMemo(() => Math.max(...levels.map((l) => Math.max(l.bidQty, l.askQty)), 1), [levels]);
  const orderMap = useMemo(() => { const m = new Map<number, PendingOrder>(); for (const o of pendingOrders) m.set(o.price, o); return m; }, [pendingOrders]);

  const showMsg = useCallback((msg: string) => { setStatusMsg(msg); setTimeout(() => setStatusMsg(null), 3000); }, []);

  const sendOrder = useCallback(async (action: "BUY" | "SELL", price: number) => {
    if (mode === "explore") { showMsg("Connect a broker to place orders"); return; }
    // Defence in depth: rows are disabled without a live price, but guard the
    // submit path too so a stale click can never place an order at a made-up price.
    if (liveLtp == null) { showMsg("Waiting for a live price before orders can be placed"); return; }
    const order: PendingOrder = { orderId: `lo_${Date.now()}`, side: action === "BUY" ? "buy" : "sell", price, qty, status: "pending" };
    setPendingOrders((p) => [...p, order]);
    try {
      await placeOrder({ symbol, exchange, action, quantity: qty, price, triggerPrice: 0, product: "MIS", orderType: "LIMIT", strategy: "orderladder" });
      showMsg(`${action} ${qty} @ ${fmtPrice(price)} placed`);
      track("trade", `order_ladder_${action.toLowerCase()}`);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Order failed");
      setPendingOrders((p) => p.filter((o) => o.orderId !== order.orderId));
    }
  }, [mode, liveLtp, qty, symbol, exchange, track, showMsg]);

  const cancelPending = useCallback(async (orderId: string) => {
    setPendingOrders((p) => p.map((o) => o.orderId === orderId ? { ...o, status: "cancelling" } : o));
    try {
      await cancelOrder(orderId, "orderladder");
      setPendingOrders((p) => p.filter((o) => o.orderId !== orderId));
      showMsg("Order cancelled");
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Cancel failed");
      setPendingOrders((p) => p.map((o) => o.orderId === orderId ? { ...o, status: "pending" } : o));
    }
  }, [showMsg]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Order Ladder widget">
      <div className="flex-none flex items-center gap-2 px-2.5 py-1.5 bg-surface-card border-b border-border-default">
        <ArrowUpDown size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Order Ladder</span>
        <span className="px-1.5 py-0.5 text-xs font-mono font-semibold text-text-primary">{symbol}</span>
        <span className="text-xxs text-text-muted border border-border-default rounded px-1">{exchange}</span>
        {isExplore && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            aria-label="Showing demo data">
            Demo data
          </span>
        )}
        <div className="flex-1" />
        {pendingOrders.length > 0 && <span className="text-xxs text-warning font-mono">{pendingOrders.length} open</span>}
      </div>

      <div className="flex-none flex items-center gap-3 px-2.5 py-1.5 bg-surface-elevated border-b border-border-subtle">
        <div className="flex items-center gap-1.5">
          <label htmlFor="ol-qty" className="text-xxs text-text-muted uppercase tracking-wide">Qty</label>
          <Input id="ol-qty" type="number" value={qty} min={1}
            onChange={(e) => setQty(Math.max(1, parseInt(e.target.value, 10) || 1))}
            className="w-16 px-1.5 py-0.5 text-xs font-mono bg-surface-hover border border-border-default rounded text-text-primary focus-visible:ring-0 focus-visible:border-accent/50 h-auto"
            aria-label="Order quantity" />
        </div>
        <div className="flex items-center gap-1.5 ml-auto">
          <span className="text-xxs text-text-muted uppercase tracking-wide">Tick</span>
          <div className="flex gap-0.5" role="group" aria-label="Tick size">
            {TICK_OPTIONS.map((t) => (
              <Button key={t} variant="ghost" onClick={() => setTickSize(t)} aria-pressed={tickSize === t}
                className={cn("px-1.5 py-0.5 h-auto text-xxs rounded border transition-colors",
                  tickSize === t ? "bg-accent/15 text-accent border-accent/30" : "text-text-muted border-border-default hover:bg-surface-hover")}>
                {t}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-none flex items-center h-5 border-b border-border-default text-xxs font-medium uppercase tracking-wide bg-surface-card">
        <div className="flex-1 text-right pr-2 text-profit">Bid</div>
        <div className="w-24 text-center text-text-muted">Price</div>
        <div className="flex-1 pl-2 text-loss">Ask</div>
      </div>

      {statusMsg && (
        <div role="status" aria-live="polite"
          className="flex-none px-2.5 py-1 text-xxs text-center text-text-secondary bg-surface-elevated border-b border-border-subtle">
          {statusMsg}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto" aria-label="Price ladder">
        {hasUsablePrice ? (
          levels.map((level, idx) => (
            <LevelRow key={level.price} level={level} isCenter={idx === LEVELS_ABOVE}
              order={orderMap.get(level.price)} maxQty={maxQty} qty={qty}
              disabled={!hasUsablePrice}
              onBid={(p) => { void sendOrder("SELL", p); }}
              onAsk={(p) => { void sendOrder("BUY", p); }}
              onCancel={cancelPending} />
          ))
        ) : (
          <div className="h-full flex flex-col items-center justify-center gap-1.5 px-4 text-center text-text-muted">
            <ArrowUpDown size={26} className="opacity-20" aria-hidden="true" />
            <span className="text-xs">Waiting for a live price</span>
            <span className="text-xxs opacity-70">
              Connect a broker to stream {symbol} before placing orders on the ladder.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(OrderLadderWidget);
