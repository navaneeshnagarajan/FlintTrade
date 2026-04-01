/**
 * DepthWidget — market depth (Level 2) visualisation for FlintTrade terminal.
 *
 * Features:
 *   - Symbol + Exchange input at top (default NIFTY, NSE)
 *   - 5-level depth table: Bid side (left, green tints) | Price col | Ask side (right, red tints)
 *   - Columns: Orders, Qty, Price | Price, Qty, Orders
 *   - Background bars proportional to quantity (max qty in visible rows = 100% width)
 *   - Total bid qty vs total ask qty summary row
 *   - Spread display (best ask - best bid)
 *   - Auto-refresh: 2 s market hours, 30 s off-market
 *   - Empty state when no depth data
 */

import { useState, useEffect, useCallback, useRef, memo } from "react";
import { RefreshCw, Layers, AlertCircle } from "lucide-react";
import { getDepth } from "@/services/api";
import { isMarketHours } from "@/lib/market";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DepthLevel {
  price: number;
  qty: number;
  orders: number;
}

interface NormalisedDepth {
  bids: DepthLevel[];
  asks: DepthLevel[];
}

/** Raw level shape from OpenAlgo — field names vary across brokers */
interface RawDepthLevel {
  price?: number;
  p?: number;
  quantity?: number;
  qty?: number;
  q?: number;
  orders?: number;
  num_orders?: number;
  o?: number;
}

/** Raw depth response from OpenAlgo API */
interface RawDepth {
  bids?: RawDepthLevel[];
  asks?: RawDepthLevel[];
  buy?: RawDepthLevel[];
  sell?: RawDepthLevel[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const NUM  = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const NUM0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function fmtPrice(v: number | null | undefined): string {
  if (v == null || isNaN(Number(v))) return "—";
  return NUM.format(Number(v));
}

function fmtQty(v: number | null | undefined): string {
  if (v == null || isNaN(Number(v))) return "—";
  const n = Number(v);
  if (n >= 1_00_000) return `${(n / 1_00_000).toFixed(1)}L`;
  return NUM0.format(n);
}

/**
 * Normalise depth response from OpenAlgo.
 * The API may return arrays directly, or wrapped inside { bids, asks }.
 * Each level may be { price, orders, quantity } or { price, qty, num_orders }.
 */
function normaliseDepth(raw: RawDepth | null | undefined): NormalisedDepth {
  if (!raw) return { bids: [], asks: [] };

  const bids: RawDepthLevel[] = raw.bids ?? raw.buy ?? [];
  const asks: RawDepthLevel[] = raw.asks ?? raw.sell ?? [];

  const norm = (arr: RawDepthLevel[]): DepthLevel[] =>
    Array.isArray(arr)
      ? arr.map((lvl) => ({
          price:  Number(lvl.price  ?? lvl.p  ?? 0),
          qty:    Number(lvl.quantity ?? lvl.qty ?? lvl.q ?? 0),
          orders: Number(lvl.orders ?? lvl.num_orders ?? lvl.o ?? 0),
        }))
      : [];

  return { bids: norm(bids).slice(0, 5), asks: norm(asks).slice(0, 5) };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface DepthRowProps {
  bidOrders: number;
  bidQty: number;
  bidPrice: number | null;
  askPrice: number | null;
  askQty: number;
  askOrders: number;
  maxQty: number;
  isFirst: boolean;
}

function DepthRow({ bidOrders, bidQty, bidPrice, askPrice, askQty, askOrders, maxQty, isFirst }: DepthRowProps) {
  const bidPct = maxQty > 0 ? Math.min((bidQty / maxQty) * 100, 100) : 0;
  const askPct = maxQty > 0 ? Math.min((askQty / maxQty) * 100, 100) : 0;

  return (
    <tr className={`border-b border-border-subtle ${isFirst ? "border-b-border-default" : ""}`}>
      {/* Bid: Orders */}
      <td className="px-2 py-1 text-right font-mono tabular-nums text-xs text-text-secondary w-12">
        {bidOrders > 0 ? bidOrders : "—"}
      </td>

      {/* Bid: Qty with background bar */}
      <td className="px-2 py-1 text-right font-mono tabular-nums text-xs text-profit relative w-24">
        <span
          className="absolute right-0 inset-y-0 bg-profit/8 rounded-l pointer-events-none"
          style={{ width: `${bidPct}%` }}
        />
        <span className="relative z-10">{fmtQty(bidQty)}</span>
      </td>

      {/* Bid: Price */}
      <td className={`px-2 py-1 text-right font-mono tabular-nums text-xs font-semibold w-20 ${isFirst ? "text-profit" : "text-profit/80"}`}>
        {fmtPrice(bidPrice)}
      </td>

      {/* Centre divider */}
      <td className="w-2 bg-surface-card border-x border-border-default" />

      {/* Ask: Price */}
      <td className={`px-2 py-1 text-left font-mono tabular-nums text-xs font-semibold w-20 ${isFirst ? "text-loss" : "text-loss/80"}`}>
        {fmtPrice(askPrice)}
      </td>

      {/* Ask: Qty with background bar */}
      <td className="px-2 py-1 text-left font-mono tabular-nums text-xs text-loss relative w-24">
        <span
          className="absolute left-0 inset-y-0 bg-loss/8 rounded-r pointer-events-none"
          style={{ width: `${askPct}%` }}
        />
        <span className="relative z-10">{fmtQty(askQty)}</span>
      </td>

      {/* Ask: Orders */}
      <td className="px-2 py-1 text-left font-mono tabular-nums text-xs text-text-secondary w-12">
        {askOrders > 0 ? askOrders : "—"}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

const KNOWN_EXCHANGES = ["NSE", "BSE", "NFO", "BFO", "MCX", "NSE_INDEX", "BSE_INDEX"];

function DepthWidget() {
  const [symbol,   setSymbol]   = useState("NIFTY");
  const [exchange, setExchange] = useState("NSE");
  const [depth,    setDepth]    = useState<NormalisedDepth | null>(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [lastTime, setLastTime] = useState<Date | null>(null);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // fetch depth
  const fetchDepth = useCallback(async () => {
    if (!symbol || !exchange) return;
    setLoading(true);
    setError(null);
    try {
      const raw = await getDepth(symbol, exchange);
      setDepth(normaliseDepth(raw as unknown as RawDepth));
      setLastTime(new Date());
    } catch (err) {
      setError((err as Error).message || "Failed to fetch depth");
    } finally {
      setLoading(false);
    }
  }, [symbol, exchange]);

  // auto-refresh
  useEffect(() => {
    fetchDepth();
    const interval = isMarketHours() ? 2000 : 30000;
    timerRef.current = setInterval(fetchDepth, interval);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchDepth]);

  // derived values
  const bids = depth?.bids ?? [];
  const asks = depth?.asks ?? [];

  function padded(arr: DepthLevel[]): DepthLevel[] {
    const out = [...arr];
    while (out.length < 5) out.push({ price: 0, qty: 0, orders: 0 });
    return out;
  }

  const bidsRows = padded(bids);
  const asksRows = padded(asks);

  const maxQty = Math.max(
    ...bidsRows.map((b) => b.qty),
    ...asksRows.map((a) => a.qty),
    1,
  );

  const totalBidQty = bids.reduce((s, b) => s + b.qty, 0);
  const totalAskQty = asks.reduce((s, a) => s + a.qty, 0);
  const totalAll    = totalBidQty + totalAskQty;

  const bestBid  = bids[0]?.price ?? null;
  const bestAsk  = asks[0]?.price ?? null;
  const spread   = bestBid != null && bestAsk != null ? (bestAsk - bestBid) : null;

  const bidDomPct = totalAll > 0 ? (totalBidQty / totalAll) * 100 : 50;

  const hasData = bids.length > 0 || asks.length > 0;

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">

      {/* Header */}
      <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5">

        {/* Row 1 */}
        <div className="flex items-center gap-2">
          <Layers size={12} className="text-accent shrink-0" />
          <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">Depth</span>

          <div className="flex-1" />

          <button
            type="button"
            onClick={fetchDepth}
            disabled={loading}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            title="Refresh depth"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Row 2: symbol + exchange inputs */}
        <div className="flex items-center gap-1.5 mt-1.5">
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            onBlur={fetchDepth}
            onKeyDown={(e) => e.key === "Enter" && fetchDepth()}
            placeholder="Symbol"
            className="h-6 flex-1 bg-surface-hover border border-border-default rounded px-2 text-xs font-mono text-text-primary focus:outline-none focus:border-accent placeholder-text-muted"
          />

          <select
            value={exchange}
            onChange={(e) => setExchange(e.target.value)}
            className="h-6 bg-surface-hover border border-border-default rounded px-1.5 text-xs font-mono text-text-primary focus:outline-none focus:border-accent"
          >
            {KNOWN_EXCHANGES.map((ex) => (
              <option key={ex} value={ex}>{ex}</option>
            ))}
          </select>
        </div>

        {/* Row 3: spread + last update */}
        {hasData && (
          <div className="flex items-center gap-3 mt-1">
            {spread != null && (
              <div className="flex items-center gap-1">
                <span className="text-xs text-text-muted">Spread</span>
                <span className="font-mono tabular-nums text-xs text-warning">{fmtPrice(spread)}</span>
              </div>
            )}
            {bestBid != null && (
              <div className="flex items-center gap-1">
                <span className="text-xs text-text-muted">Bid</span>
                <span className="font-mono tabular-nums text-xs text-profit font-semibold">{fmtPrice(bestBid)}</span>
              </div>
            )}
            {bestAsk != null && (
              <div className="flex items-center gap-1">
                <span className="text-xs text-text-muted">Ask</span>
                <span className="font-mono tabular-nums text-xs text-loss font-semibold">{fmtPrice(bestAsk)}</span>
              </div>
            )}
            <div className="flex-1" />
            {lastTime && (
              <span className="text-xxs text-text-muted font-mono">
                {lastTime.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex-none flex items-center gap-2 px-3 py-1.5 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{error}</span>
        </div>
      )}

      {/* Depth table */}
      <div className="flex-1 overflow-auto">
        {!hasData && !loading ? (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-text-muted">
            <Layers size={28} className="opacity-20" />
            <span className="text-xs">No depth data</span>
            <span className="text-xs text-text-muted opacity-60">Enter a symbol and press Enter</span>
          </div>
        ) : loading && !hasData ? (
          <div className="h-full flex items-center justify-center gap-2 text-text-muted text-xs">
            <RefreshCw size={13} className="animate-spin" />
            Loading depth…
          </div>
        ) : (
          <table className="w-full border-separate border-spacing-0">
            <thead className="sticky top-0 z-10 bg-surface-card border-b border-border-default">
              <tr>
                <th className="px-2 py-1 text-right text-xxs text-text-muted uppercase tracking-wider font-medium">Ord</th>
                <th className="px-2 py-1 text-right text-xxs text-profit uppercase tracking-wider font-medium">Qty</th>
                <th className="px-2 py-1 text-right text-xxs text-profit uppercase tracking-wider font-medium">Bid</th>

                <th className="w-2 bg-surface-card border-x border-border-default" />

                <th className="px-2 py-1 text-left text-xxs text-loss uppercase tracking-wider font-medium">Ask</th>
                <th className="px-2 py-1 text-left text-xxs text-loss uppercase tracking-wider font-medium">Qty</th>
                <th className="px-2 py-1 text-left text-xxs text-text-muted uppercase tracking-wider font-medium">Ord</th>
              </tr>
            </thead>

            <tbody>
              {bidsRows.map((bid, i) => {
                const ask = asksRows[i];
                return (
                  <DepthRow
                    key={i}
                    bidOrders={bid.orders}
                    bidQty={bid.qty}
                    bidPrice={bid.price || null}
                    askPrice={ask.price || null}
                    askQty={ask.qty}
                    askOrders={ask.orders}
                    maxQty={maxQty}
                    isFirst={i === 0}
                  />
                );
              })}
            </tbody>

            {hasData && (
              <tfoot>
                <tr className="border-t border-border-default bg-surface-card">
                  <td colSpan={2} className="px-2 py-1 text-right">
                    <span className="font-mono tabular-nums text-xs font-semibold text-profit">{fmtQty(totalBidQty)}</span>
                  </td>
                  <td className="px-2 py-1 text-right text-xs text-text-muted uppercase tracking-wide">Total</td>

                  <td className="w-2 bg-surface-card border-x border-border-default" />

                  <td className="px-2 py-1 text-left text-xs text-text-muted uppercase tracking-wide">Total</td>
                  <td colSpan={2} className="px-2 py-1 text-left">
                    <span className="font-mono tabular-nums text-xs font-semibold text-loss">{fmtQty(totalAskQty)}</span>
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        )}
      </div>

      {/* Bid/Ask dominance bar */}
      {hasData && (
        <div className="flex-none border-t border-border-default px-3 py-2 bg-surface-card space-y-1.5">
          <div className="h-1.5 rounded-full overflow-hidden flex bg-loss/20">
            <div
              className="h-full bg-profit/60 rounded-l-full transition-all duration-500"
              style={{ width: `${bidDomPct}%` }}
            />
          </div>

          <div className="flex justify-between text-xs">
            <div className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-profit inline-block" />
              <span className="text-text-muted">Bid</span>
              <span className="font-mono tabular-nums text-profit font-semibold">{bidDomPct.toFixed(1)}%</span>
            </div>

            <div className="text-text-muted text-center">
              {isMarketHours() ? "Live · 2s" : "Closed · 30s"}
            </div>

            <div className="flex items-center gap-1">
              <span className="font-mono tabular-nums text-loss font-semibold">{(100 - bidDomPct).toFixed(1)}%</span>
              <span className="text-text-muted">Ask</span>
              <span className="w-1.5 h-1.5 rounded-full bg-loss inline-block" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(DepthWidget);
