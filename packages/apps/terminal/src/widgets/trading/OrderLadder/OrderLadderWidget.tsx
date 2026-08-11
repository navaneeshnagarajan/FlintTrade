/**
 * OrderLadderWidget — DOM / Ladder: the level-2 book and the order ladder as
 * one surface.
 *
 * This widget is the union of the old Order Ladder and the old Depth widget,
 * which were a broken split rather than a duplication: Depth held the real
 * level-2 book (five levels a side, with order counts) and could not trade,
 * while the ladder could trade but had no depth feed at all — its live-mode
 * bid/ask quantities were hardcoded to zero, so it showed an empty book beside
 * a live price. The merged widget shows the real resting book on the same rows
 * the operator clicks to trade.
 *
 * Features:
 *   - ±20 price ticks centred on the live LTP for the selected instrument
 *   - Follows the FDC3 user channel from its panel params (no `channel` key
 *     means red; `channel: "none"` joins nothing); an explicit symbol
 *     prop/param pins the ladder and ignores broadcasts entirely
 *   - Real resting bid/ask quantities and order counts keyed onto those rows
 *   - Exchange picker (absorbed from Depth; the ladder took a prop only)
 *   - Bid/ask dominance footer computed with the shared `bookImbalance` kernel
 *   - Your pending orders highlighted with a cancel button
 *   - Click bid side → SELL LIMIT, click ask side → BUY LIMIT
 *   - Configurable tick size and quantity
 *   - Blocks order entry in explore mode
 *
 * Data sourcing & safety:
 *   - The ladder centre is taken from the live LTP (Jotai tick atom). When no
 *     live price is available the rows are disabled so a click can never submit
 *     a LIMIT order at a made-up price.
 *   - The book comes from the shared `useDepthData` query, so opening this
 *     beside the DOM Heatmap costs no extra polling — both dedupe on the same
 *     ["depth", symbol, exchange] key. Depth's hand-rolled 2 s interval is gone.
 *   - Quantities are never fabricated alongside a real price. In Explore mode
 *     the ladder shows a clearly-labelled deterministic sample book so the
 *     layout can be previewed without a broker connection.
 */

import { useState, useMemo, useCallback, useEffect, memo } from "react";
import { useAtomValue } from "jotai";
import type { WidgetProps } from "@/types/widgets";
import { ArrowUpDown, X, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { isMarketHours, tickKeyFor } from "@/lib/market";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useChannelInstrument, useChannelMembership } from "@/services/fdc3/hooks";
import useWebSocket from "@/hooks/useWebSocket";
import { useOrders } from "@/hooks/useOrders";
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import type { AccountAuthorityIdentity } from "@/hooks/useDataScope";
import { useDepthData } from "@/hooks/useDepthData";
import { useModeStore } from "@/stores/modeStore";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { placeOrder, cancelOrder, getSymbol } from "@/services/api";
import {
  checkLotMultiple,
  checkOrderEntryMode,
  extractBrokerOrderId,
  isTerminalOrderStatus,
} from "@/lib/orderGuards";
import { bookImbalance, normaliseDepth, type NormalisedDepth } from "@/lib/depth";
import type { Order, WsInstrument } from "@/types/api";

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

type Side = "buy" | "sell";
export interface PendingOrder {
  /** Local row key — NEVER sent to the broker. */
  localId: string;
  /** Real broker order id from the placeOrder response; null until known. */
  brokerOrderId: string | null;
  /** Exact account/query provenance captured before this order was placed. */
  authority: AccountAuthorityIdentity;
  side: Side;
  price: number;
  qty: number;
  status: "placing" | "open" | "cancelling";
}
interface LadderLevel {
  price: number;
  bidQty: number;
  askQty: number;
  /** Resting bid orders at this row — 0 when the book does not report them. */
  bidOrders: number;
  /** Resting ask orders at this row — 0 when the book does not report them. */
  askOrders: number;
}

/**
 * Extract the broker order id from a placeOrder response. The gated backend
 * returns the id under `orderId`/`orderid`/`order_id` (or as a bare string
 * for lenient bridges); anything else yields null so the caller can fail
 * closed rather than fabricate an id.
 */
// Both helpers now live in @/lib/orderGuards so every surface that reads a
// broker order id or classifies an order status agrees. Re-exported here
// because the ladder's own tests and reconciliation logic are their
// long-standing home.
export { extractBrokerOrderId, isTerminalOrderStatus };

/**
 * Reconcile the ladder's local pending rows against the live orderbook.
 *
 * Returns the rows that are still live. A row is dropped only when its REAL
 * broker order id is found in the book with a terminal status — fills,
 * rejections and cancellations done elsewhere (Orders widget, broker app) no
 * longer leave stale rows on the ladder. Fail-safe by design:
 *
 *   - rows without a confirmed broker id are kept (the book cannot vouch for
 *     them yet), and
 *   - rows whose id is absent from the book are kept (a partial/erroneous
 *     book response must never silently discard a live order's row).
 */
export function reconcilePendingOrders(
  pending: PendingOrder[],
  book: Order[],
): PendingOrder[] {
  if (pending.length === 0 || book.length === 0) return pending;
  return pending.filter((row) => {
    if (row.brokerOrderId == null) return true;
    // The typed field is orderId, but broker bridges also emit orderid /
    // order_id — extractBrokerOrderId handles all three aliases.
    const match = book.find((o) => extractBrokerOrderId(o) === row.brokerOrderId);
    if (!match || typeof match.status !== "string") return true;
    return !isTerminalOrderStatus(match.status);
  });
}

const TICK_OPTIONS = [0.05, 0.25, 0.5, 1, 5] as const;
type TickSize = (typeof TICK_OPTIONS)[number];

/**
 * Exchanges the book can be requested for. Absorbed from the Depth widget,
 * which was the only depth surface that let the operator pick one — the ladder
 * took the exchange as a panel prop and could not be pointed at, say, the
 * NSE_INDEX feed that a bare index name actually ticks under.
 */
export const KNOWN_EXCHANGES = [
  "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX", "NCO",
  "NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX",
] as const;

const LEVELS_ABOVE = 20;
const LEVELS_BELOW = 20;
const DEFAULT_QTY   = 25;
const SAMPLE_PRICE  = 22150.25;

/**
 * Deterministic Explore book — Depth's sample quantities and order counts,
 * re-priced onto the ladder's demo centre so the levels land on real rows.
 * Never shown outside Explore mode.
 */
const SAMPLE_DEPTH: NormalisedDepth = {
  bids: [
    { price: 22150.25, qty: 14850, orders: 46 },
    { price: 22150.0,  qty: 11275, orders: 39 },
    { price: 22149.75, qty: 9150,  orders: 31 },
    { price: 22149.5,  qty: 7625,  orders: 26 },
    { price: 22149.25, qty: 5840,  orders: 19 },
  ],
  asks: [
    { price: 22150.5,  qty: 13200, orders: 42 },
    { price: 22150.75, qty: 10450, orders: 34 },
    { price: 22151.0,  qty: 8860,  orders: 29 },
    { price: 22151.25, qty: 7210,  orders: 23 },
    { price: 22151.5,  qty: 5685,  orders: 18 },
  ],
};

// ---------------------------------------------------------------------------
// Ladder construction
// ---------------------------------------------------------------------------

/**
 * Build the ±20-tick price ladder around a centre price.
 *
 * Quantities start at zero on every row: the ladder itself never invents
 * depth. Resting quantities are keyed on afterwards by {@link applyBookToLevels}
 * from the real (or, in Explore, the labelled sample) book.
 *
 * @param centerPrice - Centre of the ladder (the live LTP, or the demo price in Explore mode).
 * @param tickSize    - Spacing between adjacent price levels.
 */
export function generateLadderLevels(centerPrice: number, tickSize: number): LadderLevel[] {
  const levels: LadderLevel[] = [];
  for (let i = LEVELS_ABOVE; i >= -LEVELS_BELOW; i--) {
    const price = parseFloat((centerPrice + i * tickSize).toFixed(2));
    levels.push({ price, bidQty: 0, askQty: 0, bidOrders: 0, askOrders: 0 });
  }
  return levels;
}

/**
 * Key a normalised level-2 book onto the ladder's price rows.
 *
 * The book's prices sit on the instrument's own tick, which is finer than the
 * ladder grid whenever the operator widens the tick size, so each level is
 * snapped to the nearest row and quantities/order counts accumulate there. A
 * level further than half a tick from its row, or outside the ±20-tick window,
 * is dropped rather than dragged onto a row it does not belong to.
 *
 * @param levels   - Ladder rows from {@link generateLadderLevels}, top price first.
 * @param book     - Normalised book (see `@/lib/depth`).
 * @param tickSize - The ladder grid spacing the rows were built with.
 * @returns A new row array; the input is not mutated.
 */
export function applyBookToLevels(
  levels: LadderLevel[],
  book: NormalisedDepth,
  tickSize: number,
): LadderLevel[] {
  if (levels.length === 0 || tickSize <= 0) return levels;
  const rows = levels.map((l) => ({ ...l }));
  const topPrice = rows[0].price;
  const tolerance = tickSize / 2 + 1e-9;

  const place = (side: Side, price: number, qty: number, orders: number): void => {
    if (!Number.isFinite(price) || price <= 0 || !(qty > 0)) return;
    const idx = Math.round((topPrice - price) / tickSize);
    if (idx < 0 || idx >= rows.length) return;
    const row = rows[idx];
    if (Math.abs(row.price - price) > tolerance) return;
    if (side === "buy") {
      row.bidQty += qty;
      row.bidOrders += orders;
    } else {
      row.askQty += qty;
      row.askOrders += orders;
    }
  };

  for (const level of book.bids) place("buy", level.price, level.qty, level.orders);
  for (const level of book.asks) place("sell", level.price, level.qty, level.orders);
  return rows;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fmtQty    = (q: number) => !q ? "" : q >= 1000 ? `${(q / 1000).toFixed(1)}K` : String(q);
const fmtOrders = (n: number) => !n ? "" : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n);
const fmtPrice  = (p: number) => p.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const barW      = (qty: number, max: number) => !qty || !max ? "0%" : `${Math.min(100, (qty / max) * 100).toFixed(1)}%`;

/** Coerce a panel param to one of the offered tick sizes; 0.25 otherwise. */
function resolveTickSize(value: unknown): TickSize {
  const n = Number(value);
  return TICK_OPTIONS.find((t) => t === n) ?? 0.25;
}

/** Best (highest) resting bid price with size, or null. */
function bestBidPrice(book: NormalisedDepth): number | null {
  const prices = book.bids.filter((l) => l.qty > 0 && l.price > 0).map((l) => l.price);
  return prices.length > 0 ? Math.max(...prices) : null;
}

/** Best (lowest) resting ask price with size, or null. */
function bestAskPrice(book: NormalisedDepth): number | null {
  const prices = book.asks.filter((l) => l.qty > 0 && l.price > 0).map((l) => l.price);
  return prices.length > 0 ? Math.min(...prices) : null;
}

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
      <div className="w-9 shrink-0 pr-1 text-right text-xxs font-mono tabular-nums text-text-muted select-none"
        title={level.bidOrders ? `${level.bidOrders} bid orders at ${fmtPrice(level.price)}` : undefined}>
        {fmtOrders(level.bidOrders)}
      </div>

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
              onClick={() => onCancel(order.localId)}
              disabled={order.status !== "open" || order.brokerOrderId == null}
              title={
                order.brokerOrderId == null
                  ? "Broker order id not confirmed yet — cancel from the Orders widget if needed"
                  : `Cancel ${order.side} order at ${fmtPrice(level.price)}`
              }
              className="h-auto w-auto p-0 text-text-muted hover:text-loss disabled:opacity-40 transition-colors"
              aria-label={`Cancel ${order.side} order at ${fmtPrice(level.price)}`}
            >
              {order.status === "cancelling" || order.status === "placing"
                ? <Loader2 size={9} className="animate-spin" />
                : <X size={9} />}
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

      <div className="w-9 shrink-0 pl-1 text-left text-xxs font-mono tabular-nums text-text-muted select-none"
        title={level.askOrders ? `${level.askOrders} ask orders at ${fmtPrice(level.price)}` : undefined}>
        {fmtOrders(level.askOrders)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

/** Panel parameters (workspace `params`) this widget understands. */
interface OrderLadderPanelParams {
  symbol?: string;
  exchange?: string;
  /** Initial ladder grid spacing; one of TICK_OPTIONS, else 0.25. */
  tick?: number;
  /**
   * FDC3 user-channel membership (resolved by `channelFromParams`): absent
   * means the default red channel; "none" means joined to nothing.
   */
  channel?: string;
}

type Props = Partial<WidgetProps> & OrderLadderPanelParams;

function OrderLadderWidget(props: Props) {
  const panelParams = props.params as OrderLadderPanelParams | undefined;

  // FDC3 channel membership: no `channel` param means the default red
  // channel; `channel: "none"` (or an unknown value) joins nothing. A ladder
  // pinned by an explicit symbol prop/param keeps ignoring channels, exactly
  // as it ignored the global selection before the bus existed.
  const channelId = useChannelMembership(props.api?.id ?? "orderladder-detached", props.params);
  const channelInstrument = useChannelInstrument(channelId);
  const pinnedSymbol = props.symbol ?? panelParams?.symbol;
  // A broadcast travels as a (symbol, exchange) pair — an unpinned ladder
  // follows the venue with the symbol, so the depth query, the WS feed and
  // the lot lookup all point at the book the broadcast actually meant.
  const followedInstrument = pinnedSymbol == null ? channelInstrument : null;

  const symbol = pinnedSymbol ?? followedInstrument?.symbol ?? "NIFTY";
  // When following, the broadcast's venue is ATOMIC with its symbol — it
  // outranks a previously persisted exchange param, which would otherwise
  // freeze the venue while the symbol keeps moving and leave the ladder on
  // a mismatched (symbol, exchange) book (Phase 2 audit finding). A manual
  // exchange pick below is a local override that yields on the next
  // broadcast that carries a different venue.
  const initialExchange =
    followedInstrument?.exchange ?? props.exchange ?? panelParams?.exchange ?? "NSE";
  const initialTick = resolveTickSize(props.tick ?? panelParams?.tick);

  const mode  = useModeStore((s) => s.mode);
  const { identity: accountIdentity } = useAccountReadContext();
  const isExplore = mode === "explore";
  const track = useTrackBehavior();

  // Exchange is operator-selectable (absorbed from Depth); the prop/param is
  // the starting point, and a later param change still wins.
  const [exchange, setExchange] = useState(initialExchange);
  useEffect(() => { setExchange(initialExchange); }, [initialExchange]);
  const exchangeOptions = useMemo(
    () => (KNOWN_EXCHANGES.includes(exchange as (typeof KNOWN_EXCHANGES)[number])
      ? [...KNOWN_EXCHANGES]
      : [exchange, ...KNOWN_EXCHANGES]),
    [exchange],
  );

  // Live LTP for the selected instrument — drives the ladder centre.
  // The ladder subscribes its own instrument to the WS feed (nothing else is
  // guaranteed to), and falls back to the shared tick atom in case another
  // widget already streams the same instrument.
  const wsInstruments = useMemo<WsInstrument[]>(
    () => (isExplore ? [] : [{ symbol, exchange }]),
    [isExplore, symbol, exchange],
  );
  const { ticks: wsTicks } = useWebSocket(wsInstruments, "quote", !isExplore);
  const wsTick = wsTicks[`${exchange}:${symbol}`];
  // Shared-atom fallback: bare index names tick under their *_INDEX exchange
  // (the default NIFTY/NSE otherwise read an atom nothing writes → no centre).
  const atomTick = useAtomValue(tickAtomFamily(tickKeyFor(symbol, exchange)));
  const tick = wsTick ?? atomTick;
  const liveLtp = tick?.ltp && tick.ltp > 0 ? tick.ltp : null;

  const [tickSize, setTickSize] = useState<TickSize>(initialTick);
  useEffect(() => { setTickSize(initialTick); }, [initialTick]);
  const [qty, setQty] = useState(DEFAULT_QTY);
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([]);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  // The resting book. Shares the ["depth", symbol, exchange] query key with
  // every other depth surface, so a ladder open beside the DOM Heatmap adds no
  // polling of its own — Depth's hand-rolled 2 s setInterval is gone.
  const depthQuery = useDepthData(symbol, exchange, !isExplore);
  const book = useMemo<NormalisedDepth>(
    () => (isExplore ? SAMPLE_DEPTH : normaliseDepth(depthQuery.data)),
    [isExplore, depthQuery.data],
  );
  const depthError = !isExplore && depthQuery.isError
    ? (depthQuery.error instanceof Error ? depthQuery.error.message : "Depth feed unavailable")
    : null;

  // Real lot size for the contract. The ladder previously placed a free
  // integer quantity on any exchange; on a derivative that is exactly the
  // non-lot-multiple order every other ticket refuses. Reset before each
  // lookup so a failed fetch never reuses the previous instrument's lot.
  const [lotSize, setLotSize] = useState(0);
  const [lotSizeKnown, setLotSizeKnown] = useState(false);
  useEffect(() => {
    if (!symbol || !exchange) return;
    let cancelled = false;
    setLotSize(0);
    setLotSizeKnown(false);
    getSymbol(symbol, exchange)
      .then((info) => {
        if (cancelled) return;
        const ls = Number(info?.lotsize ?? 0);
        if (Number.isFinite(ls) && ls > 0) {
          setLotSize(ls);
          setLotSizeKnown(true);
        }
      })
      .catch(() => {
        // Stays unknown — derivative orders remain blocked (fail closed).
      });
    return () => { cancelled = true; };
  }, [symbol, exchange]);

  useEffect(() => { track("trade", "widget_view_order_ladder"); }, [track]);

  const showMsg = useCallback((msg: string) => { setStatusMsg(msg); setTimeout(() => setStatusMsg(null), 3000); }, []);

  // Persist the operator's exchange/tick into the panel params so a saved
  // layout reopens on the same book (this is also how the retired `depth` id
  // reproduces its 5-level view: params { tick: 0.05 }).
  const persistParams = useCallback((patch: Record<string, unknown>) => {
    props.api?.updateParameters({ ...patch });
  }, [props.api]);

  const handleExchangeChange = useCallback((next: string) => {
    setExchange(next);
    persistParams({ exchange: next });
  }, [persistParams]);

  const handleTickChange = useCallback((next: TickSize) => {
    setTickSize(next);
    persistParams({ tick: next });
  }, [persistParams]);

  // Reconcile ladder rows against the live orderbook (the same TanStack Query
  // feed the Orders widget polls). Fills, rejections and cancellations done
  // outside this widget would otherwise leave stale rows with live-looking
  // cancel affordances.
  const { data: brokerOrders } = useOrders({ enabled: !isExplore && pendingOrders.length > 0 });
  useEffect(() => {
    if (!brokerOrders || pendingOrders.length === 0) return;
    const live = reconcilePendingOrders(pendingOrders, brokerOrders);
    const removed = pendingOrders.length - live.length;
    if (removed === 0) return;
    const liveIds = new Set(live.map((o) => o.localId));
    setPendingOrders((prev) => prev.filter((o) => liveIds.has(o.localId)));
    showMsg(
      removed === 1
        ? "1 order left the book (filled/rejected/cancelled) — removed from ladder"
        : `${removed} orders left the book (filled/rejected/cancelled) — removed from ladder`,
    );
  }, [brokerOrders, pendingOrders, showMsg]);

  // The ladder is only safe to trade on when we have a real centre price:
  // either a live LTP, or the labelled demo price shown in Explore mode.
  const centrePrice  = isExplore ? SAMPLE_PRICE : liveLtp;
  const hasUsablePrice = centrePrice != null;

  // Rows carry REAL resting quantities: the ladder grid supplies the prices,
  // the depth feed supplies the sizes. Nothing is fabricated in live mode —
  // an absent book simply leaves the quantity columns blank.
  const levels = useMemo(
    () => centrePrice != null
      ? applyBookToLevels(generateLadderLevels(centrePrice, tickSize), book, tickSize)
      : [],
    [centrePrice, tickSize, book],
  );
  const maxQty  = useMemo(() => Math.max(...levels.map((l) => Math.max(l.bidQty, l.askQty)), 1), [levels]);
  const orderMap = useMemo(() => { const m = new Map<number, PendingOrder>(); for (const o of pendingOrders) m.set(o.price, o); return m; }, [pendingOrders]);

  // Dominance uses the shared signed kernel rather than a fourth percentage of
  // its own, and reads the book itself (not the mapped rows) so a level that
  // falls outside the ±20-tick window cannot skew it.
  const restingQty = useMemo(
    () => book.bids.reduce((s, l) => s + l.qty, 0) + book.asks.reduce((s, l) => s + l.qty, 0),
    [book],
  );
  const hasBook = restingQty > 0;
  const bidDomPct = ((bookImbalance(book.bids, book.asks) + 1) / 2) * 100;

  const bestBid = bestBidPrice(book);
  const bestAsk = bestAskPrice(book);
  const spread = bestBid != null && bestAsk != null && bestAsk >= bestBid ? bestAsk - bestBid : null;

  const feedLabel = isExplore
    ? "Explore · sample"
    : isMarketHours({ symbol, exchange }) ? "Live · 1s" : "Closed · snapshot";
  const updatedLabel = !isExplore && depthQuery.dataUpdatedAt
    ? `Book updated ${new Date(depthQuery.dataUpdatedAt).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}`
    : undefined;

  const sendOrder = useCallback(async (action: "BUY" | "SELL", price: number) => {
    const modeRefusal = checkOrderEntryMode(mode);
    if (modeRefusal) { showMsg(modeRefusal); return; }
    // Defence in depth: rows are disabled without a live price, but guard the
    // submit path too so a stale click can never place an order at a made-up price.
    if (liveLtp == null) { showMsg("Waiting for a live price before orders can be placed"); return; }
    // The ladder ships a free integer quantity and a hardcoded default. On a
    // derivative that is a non-lot-multiple order every other ticket refuses —
    // the ladder used to send it.
    const lotRefusal = checkLotMultiple(
      exchange,
      qty,
      { lotSize, verified: lotSizeKnown },
      symbol,
    );
    if (lotRefusal) { showMsg(lotRefusal); return; }
    const localId = `lo_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const authority = accountIdentity;
    const order: PendingOrder = {
      localId,
      brokerOrderId: null,
      authority,
      side: action === "BUY" ? "buy" : "sell",
      price,
      qty,
      status: "placing",
    };
    setPendingOrders((p) => [...p, order]);
    try {
      const result = await placeOrder(
        { symbol, exchange, action, quantity: qty, price, triggerPrice: 0, product: "MIS", orderType: "LIMIT", strategy: "orderladder" },
        authority,
      );
      // Store the REAL broker order id — cancel is disabled until it is known,
      // so the ladder can never send a fabricated id to the broker.
      const brokerOrderId = extractBrokerOrderId(result);
      setPendingOrders((p) => p.map((o) => o.localId === localId ? { ...o, brokerOrderId, status: "open" } : o));
      showMsg(
        brokerOrderId != null
          ? `${action} ${qty} @ ${fmtPrice(price)} placed · ID ${brokerOrderId}`
          : `${action} ${qty} @ ${fmtPrice(price)} placed — order id unconfirmed, manage it from the Orders widget`,
      );
      track("trade", `order_ladder_${action.toLowerCase()}`);
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Order failed");
      setPendingOrders((p) => p.filter((o) => o.localId !== localId));
    }
  }, [mode, accountIdentity, liveLtp, qty, symbol, exchange, lotSize, lotSizeKnown, track, showMsg]);

  const cancelPending = useCallback(async (localId: string) => {
    const order = pendingOrders.find((o) => o.localId === localId);
    // Fail closed: never send a locally minted id to the broker.
    if (!order || order.brokerOrderId == null) {
      showMsg("Broker order id not confirmed yet — cancel from the Orders widget");
      return;
    }
    const brokerOrderId = order.brokerOrderId;
    setPendingOrders((p) => p.map((o) => o.localId === localId ? { ...o, status: "cancelling" } : o));
    try {
      await cancelOrder(brokerOrderId, "orderladder", order.authority);
      setPendingOrders((p) => p.filter((o) => o.localId !== localId));
      showMsg("Order cancelled");
    } catch (err) {
      showMsg(err instanceof Error ? err.message : "Cancel failed");
      setPendingOrders((p) => p.map((o) => o.localId === localId ? { ...o, status: "open" } : o));
    }
  }, [pendingOrders, showMsg]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="DOM Ladder widget">
      <div className="flex-none flex items-center gap-2 px-2.5 py-1.5 bg-surface-card border-b border-border-default">
        <ArrowUpDown size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">DOM / Ladder</span>
        <span className="px-1.5 py-0.5 text-xs font-mono font-semibold text-text-primary">{symbol}</span>
        <Select value={exchange} onValueChange={handleExchangeChange}>
          <SelectTrigger
            aria-label="Exchange"
            className="h-5 w-auto gap-1 rounded border border-border-default bg-transparent px-1 py-0 text-xxs font-mono text-text-muted shadow-none data-[size=default]:h-5 focus-visible:ring-0"
          >
            {exchange}
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default">
            {exchangeOptions.map((ex) => (
              <SelectItem key={ex} value={ex} className="text-xs font-mono text-text-primary focus:bg-surface-hover">
                {ex}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {isExplore && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            aria-label="Showing sample data">
            Sample data
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
        {spread != null && (
          <div className="flex items-center gap-1" aria-label="Book spread">
            <span className="text-xxs text-text-muted uppercase tracking-wide">Spread</span>
            <span className="text-xxs font-mono tabular-nums text-warning">{fmtPrice(spread)}</span>
          </div>
        )}
        <div className="flex items-center gap-1.5 ml-auto">
          <span className="text-xxs text-text-muted uppercase tracking-wide">Tick</span>
          <div className="flex gap-0.5" role="group" aria-label="Tick size">
            {TICK_OPTIONS.map((t) => (
              <Button key={t} variant="ghost" onClick={() => handleTickChange(t)} aria-pressed={tickSize === t}
                className={cn("px-1.5 py-0.5 h-auto text-xxs rounded border transition-colors",
                  tickSize === t ? "bg-accent/15 text-accent border-accent/30" : "text-text-muted border-border-default hover:bg-surface-hover")}>
                {t}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-none flex items-center h-5 border-b border-border-default text-xxs font-medium uppercase tracking-wide bg-surface-card">
        <div className="w-9 shrink-0 pr-1 text-right text-text-muted">Ord</div>
        <div className="flex-1 text-right pr-2 text-profit">Bid</div>
        <div className="w-24 text-center text-text-muted">Price</div>
        <div className="flex-1 pl-2 text-loss">Ask</div>
        <div className="w-9 shrink-0 pl-1 text-left text-text-muted">Ord</div>
      </div>

      {depthError && (
        <div className="flex-none flex items-center gap-1.5 px-2.5 py-1 text-xxs text-loss bg-loss/10 border-b border-loss/20"
          role="status">
          <AlertCircle size={10} aria-hidden="true" />
          <span>Depth unavailable — resting sizes hidden ({depthError})</span>
        </div>
      )}

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

      {hasBook && (
        <div className="flex-none border-t border-border-default px-2.5 py-1.5 bg-surface-card space-y-1"
          aria-label="Bid/ask dominance">
          <div className="h-1.5 rounded-full overflow-hidden flex bg-loss/20" role="img"
            aria-label={`Resting book dominance: ${bidDomPct.toFixed(1)} percent bid`}>
            <div className="h-full bg-profit/60 rounded-l-full transition-[width] duration-500"
              style={{ width: `${bidDomPct}%` }} />
          </div>
          <div className="flex items-center justify-between text-xxs">
            <span className="font-mono tabular-nums text-profit font-semibold">{bidDomPct.toFixed(1)}% bid</span>
            <span className="text-text-muted" title={updatedLabel}>{feedLabel}</span>
            <span className="font-mono tabular-nums text-loss font-semibold">{(100 - bidDomPct).toFixed(1)}% ask</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(OrderLadderWidget);
