// Migrated to TSX — Phase 4 Batch 1
// Direct API calls (placeOrder, cancelAllOrders, closePosition, getExpiry, getQuotes)
// are intentional here: Scalper requires interactive one-click orders, not cached REST data.
import { useState, useEffect, useCallback, useMemo, useRef, memo } from "react";
import {
  placeOrder,
  cancelAllOrders,
  closePosition,
  getExpiry,
  getQuotes,
  getSymbol,
} from "@/services/api";
import { getLotSize, placeBracketOrder } from "@/services/ftApi";
import useWebSocket from "@/hooks/useWebSocket";
import { useVoiceAlert } from "@/hooks/useVoiceAlert";
import { useModeStore } from "@/stores/modeStore";
import type { PlaceOrderParams, WsInstrument } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";
import { ScalperControls } from "./ScalperControls";
import { ScalperChartPanel } from "./ScalperChartPanel";
import { CancelAllDialog, CloseAllDialog, OrderConfirmModal } from "./ScalperDialogs";
import { buildOptionSymbol, roundToStrike } from "./helpers";
import {
  DEFAULT_SYMBOL,
  INDEX_CONFIG,
  type IntervalValue,
  type OrderAction,
  type OrderTypeValue,
  type PendingOrder,
  type ProductType,
  type StatusState,
  type StatusType,
} from "./types";

const DEMO_SPOT_BY_SYMBOL: Record<string, number> = {
  NIFTY: 25062,
  BANKNIFTY: 56240,
  FINNIFTY: 23980,
  MIDCPNIFTY: 12920,
  SENSEX: 82460,
  BANKEX: 63850,
};

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function formatDateInputValue(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function getDemoExpiries(referenceDate = new Date()): string[] {
  const daysUntilThursday = (4 - referenceDate.getDay() + 7) % 7 || 7;
  const weeklyExpiry = addDays(referenceDate, daysUntilThursday);
  return [
    weeklyExpiry,
    addDays(weeklyExpiry, 7),
    addDays(weeklyExpiry, 28),
  ].map(formatDateInputValue);
}

/**
 * Backend-confirmed lot size and where it came from. "symbol-info" is the
 * broker symbol master (`getSymbol`, the same API QuickTrade uses) probed on
 * a concrete option contract; "resolver" is the backend lot-size resolver
 * route, accepted only when it is NOT flagged as sample data.
 */
interface ResolvedLot {
  size: number;
  source: "symbol-info" | "resolver";
}

/** Snap a computed leg price to the exchange tick (₹0.05). */
function snapToTick(price: number): number {
  return Math.round(price * 20) / 20;
}

function ScalperWidget(_props: WidgetProps) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [lots, setLots] = useState(1);
  const [product, setProduct] = useState<ProductType>("MIS");
  const [orderType, setOrderType] = useState<OrderTypeValue>("MARKET");
  // SL/Target points (blank = off). RESTORED now that they place a real
  // protective exit leg through the gated bracket endpoint — an earlier
  // incarnation displayed them without sending anything (silent-risk bug),
  // which is why they were removed until this wiring existed.
  const [slPoints, setSlPoints] = useState("");
  const [targetPoints, setTargetPoints] = useState("");
  const [limitPrice, setLimitPrice] = useState("");
  const [oneClick, setOneClick] = useState(false);
  const [interval, setInterval_] = useState<IntervalValue>("5m");

  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiriesError, setExpiriesError] = useState(false);
  const [expiry, setExpiry] = useState("");
  const [atmStrike, setAtmStrike] = useState<number | null>(null);
  const [ceOffset, setCeOffset] = useState(0);
  const [peOffset, setPeOffset] = useState(0);

  const [status, setStatus] = useState<StatusState>({ message: "", type: "idle" });
  const [pendingOrder, setPendingOrder] = useState<PendingOrder | null>(null);
  const [closeAllOpen, setCloseAllOpen] = useState(false);
  const [cancelAllOpen, setCancelAllOpen] = useState(false);
  const [focused, setFocused] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const { announceOrder } = useVoiceAlert();

  const cfg = INDEX_CONFIG[symbol] ?? INDEX_CONFIG[DEFAULT_SYMBOL];
  const step = cfg.step;
  const spotExch = cfg.exchange;
  const optExch = cfg.optExchange;

  // Dynamic lot size — resolved at runtime. Primary source: the broker
  // symbol master via getSymbol (the same symbol-info API QuickTrade uses),
  // probed on the concrete CE contract once it resolves. Secondary: the
  // backend lot-size resolver route, accepted only when NOT flagged as
  // sample data. The built-in INDEX_CONFIG value is an explicitly-marked
  // LAST-RESORT display fallback; real (non-explore) orders are blocked
  // until a backend source confirms, because lot sizes change over time and
  // a stale hardcoded value mis-sizes every order.
  const [resolvedLot, setResolvedLot] = useState<ResolvedLot | null>(null);
  const lotSize = resolvedLot?.size ?? cfg.lotSize;
  const lotSizeVerified = resolvedLot != null;
  const symbolInfoProbeRef = useRef<string | null>(null);

  const refreshLotSize = useCallback((signal?: { cancelled: boolean }) => {
    getLotSize(symbol, optExch)
      .then((res) => {
        if (signal?.cancelled || res.lot_size <= 0 || res.is_sample_data === true) return;
        // The symbol master is the audited source — never override it with
        // the resolver route.
        setResolvedLot((prev) =>
          prev?.source === "symbol-info" ? prev : { size: res.lot_size, source: "resolver" },
        );
      })
      .catch(() => {
        // Stays unverified — executeOrder fails closed and retries the fetch.
      });
  }, [symbol, optExch]);

  useEffect(() => {
    const signal = { cancelled: false };
    setResolvedLot(null); // reset on symbol change
    symbolInfoProbeRef.current = null;
    refreshLotSize(signal);
    return () => { signal.cancelled = true; };
  }, [refreshLotSize]);

  const ceStrike = atmStrike != null ? atmStrike + ceOffset * step : null;
  const peStrike = atmStrike != null ? atmStrike + peOffset * step : null;

  const ceSymbol = ceStrike != null ? buildOptionSymbol(symbol, expiry, ceStrike, "CE") : null;
  const peSymbol = peStrike != null ? buildOptionSymbol(symbol, expiry, peStrike, "PE") : null;

  // Primary lot-size source — probe the broker symbol master with the
  // concrete CE contract once it resolves (QuickTrade's getSymbol pattern).
  // Every contract of one underlying+expiry shares a lot size, so probe once
  // per pair rather than on every strike step.
  useEffect(() => {
    if (!ceSymbol || isExplore) return;
    const probeKey = `${symbol}|${expiry}|${optExch}`;
    if (symbolInfoProbeRef.current === probeKey) return;
    symbolInfoProbeRef.current = probeKey;
    let cancelled = false;
    getSymbol(ceSymbol, optExch)
      .then((info) => {
        if (!cancelled && info.lotsize > 0) {
          setResolvedLot({ size: info.lotsize, source: "symbol-info" });
        }
      })
      .catch(() => {
        // Allow a later retry (deps change or the fail-closed re-probe) —
        // the resolver-route fallback may still verify meanwhile.
        if (!cancelled && symbolInfoProbeRef.current === probeKey) {
          symbolInfoProbeRef.current = null;
        }
      });
    return () => { cancelled = true; };
  }, [ceSymbol, symbol, expiry, optExch, isExplore]);

  const instruments = useMemo<WsInstrument[]>(() => {
    const list: WsInstrument[] = [{ symbol, exchange: spotExch }];
    if (ceSymbol) list.push({ symbol: ceSymbol, exchange: optExch });
    if (peSymbol) list.push({ symbol: peSymbol, exchange: optExch });
    return list;
  }, [symbol, spotExch, ceSymbol, peSymbol, optExch]);

  const { ticks } = useWebSocket(instruments, "quote");

  // Read ticks at click time without recreating executeOrder on every tick.
  const ticksRef = useRef(ticks);
  useEffect(() => {
    ticksRef.current = ticks;
  }, [ticks]);

  const spotKey = `${spotExch}:${symbol}`;
  const spotTick = ticks[spotKey];
  const spotLtp = spotTick?.ltp ?? spotTick?.close ?? null;

  // Fetch expiries on symbol change
  const fetchExpiries = useCallback(
    async (signal?: { cancelled: boolean }) => {
      setExpiriesError(false);
      setExpiries([]);
      setExpiry("");
      if (isExplore) {
        const demoExpiries = getDemoExpiries();
        if (signal?.cancelled) return;
        setExpiries(demoExpiries);
        setExpiry(demoExpiries[0] ?? "");
        return;
      }
      try {
        const data = await getExpiry(symbol, optExch);
        if (signal?.cancelled) return;
        const list = Array.isArray(data) ? data : (data?.expiry ?? []);
        setExpiries(list);
        if (list.length > 0) setExpiry(list[0]);
      } catch {
        if (signal?.cancelled) return;
        setExpiriesError(true);
      }
    },
    [symbol, optExch, isExplore],
  );

  useEffect(() => {
    const signal = { cancelled: false };
    setAtmStrike(null);
    void fetchExpiries(signal);
    return () => {
      signal.cancelled = true;
    };
  }, [fetchExpiries]);

  // Resolve ATM from spot tick (fast path)
  useEffect(() => {
    if (spotLtp != null) {
      setAtmStrike(roundToStrike(spotLtp, step));
    } else if (isExplore) {
      setAtmStrike(roundToStrike(DEMO_SPOT_BY_SYMBOL[symbol] ?? DEMO_SPOT_BY_SYMBOL[DEFAULT_SYMBOL], step));
    }
  }, [spotLtp, step, isExplore, symbol]);

  // Fallback: fetch from API once if tick not yet available
  useEffect(() => {
    if (spotLtp != null || !symbol || isExplore) return;
    let cancelled = false;

    async function fetchSpot() {
      try {
        const q = await getQuotes(symbol, spotExch);
        if (cancelled) return;
        const ltp = q?.ltp ?? q?.close ?? null;
        if (ltp) setAtmStrike(roundToStrike(ltp, step));
      } catch {
        // silently ignore
      }
    }

    void fetchSpot();
    return () => {
      cancelled = true;
    };
  }, [symbol, spotExch, spotLtp, step]);

  const showStatus = useCallback((message: string, type: StatusType = "success", ms = 3000) => {
    setStatus({ message, type });
    if (ms) setTimeout(() => setStatus({ message: "", type: "idle" }), ms);
  }, []);

  const executeOrder = useCallback(
    async (sym: string | null, exch: string, action: OrderAction) => {
      if (!sym) {
        showStatus("Strike not resolved", "error");
        return;
      }
      if (isExplore) {
        showStatus("Connect a broker to place orders", "error");
        return;
      }
      // Fail closed: never size a real order from the hardcoded fallback lot
      // table — lot sizes change and a stale value mis-sizes every order.
      if (!lotSizeVerified) {
        showStatus("Lot size not confirmed from the backend yet — order not sent", "error");
        refreshLotSize();
        // Re-probe the symbol master with the exact contract being traded.
        getSymbol(sym, exch)
          .then((info) => {
            if (info.lotsize > 0) setResolvedLot({ size: info.lotsize, source: "symbol-info" });
          })
          .catch(() => {
            // Stays unverified — orders remain blocked.
          });
        return;
      }
      // A LIMIT order must carry a real price — ₹0 is a guaranteed rejection
      // (or worse, a lenient bridge could treat it as marketable).
      const price = orderType === "LIMIT" ? parseFloat(limitPrice) : 0;
      if (orderType === "LIMIT" && (!Number.isFinite(price) || price <= 0)) {
        showStatus("Enter a limit price before placing a LIMIT order", "error");
        return;
      }
      const qty = lots * lotSize;

      // Optional protective exit leg (points from entry). Validated before
      // anything is sent — a malformed value must never degrade to a silent
      // plain order.
      const slPts = slPoints.trim() === "" ? null : Number(slPoints);
      const tgtPts = targetPoints.trim() === "" ? null : Number(targetPoints);
      if (slPts != null && (!Number.isFinite(slPts) || slPts <= 0)) {
        showStatus("SL points must be a positive number — order not sent", "error");
        return;
      }
      if (tgtPts != null && (!Number.isFinite(tgtPts) || tgtPts <= 0)) {
        showStatus("Target points must be a positive number — order not sent", "error");
        return;
      }
      if (slPts != null && tgtPts != null) {
        // Mirrors the backend's oco_unsupported refusal — no fill monitor
        // exists to cancel the sibling leg, so refuse before sending.
        showStatus(
          "SL and Target together are not supported yet — enter exactly one",
          "error",
          6000,
        );
        return;
      }

      if (slPts != null || tgtPts != null) {
        // Bracket path — entry + ONE protective exit leg through the gated
        // bracket endpoint. Points are anchored to the LIMIT price, or to
        // the option's live LTP for MARKET entries; without an anchor the
        // exit price cannot be computed honestly, so fail closed.
        const tick = ticksRef.current[`${exch}:${sym}`];
        const anchor = orderType === "LIMIT" ? price : tick?.ltp ?? tick?.close ?? null;
        if (anchor == null || anchor <= 0) {
          showStatus("Live price unavailable to anchor SL/Target — bracket not sent", "error");
          return;
        }
        const direction = action === "BUY" ? 1 : -1;
        const stoploss = slPts != null ? snapToTick(anchor - direction * slPts) : undefined;
        const target = tgtPts != null ? snapToTick(anchor + direction * tgtPts) : undefined;
        if ((stoploss !== undefined && stoploss <= 0) || (target !== undefined && target <= 0)) {
          showStatus("SL/Target points exceed the option price — bracket not sent", "error");
          return;
        }
        showStatus(`${action} ${sym} × ${qty} bracket…`, "pending", 0);
        try {
          await placeBracketOrder({
            entry: {
              symbol: sym,
              exchange: exch,
              action,
              quantity: qty,
              price: orderType === "LIMIT" ? price : 0,
              product,
              strategy: "FlintScalper",
            },
            ...(stoploss !== undefined ? { stoploss } : {}),
            ...(target !== undefined ? { target } : {}),
          });
          // Placement ≠ fill — both legs are merely accepted by the broker.
          showStatus(`${action} ${sym} bracket placed — legs pending, not filled`, "success", 5000);
          announceOrder(action, sym, qty);
        } catch (err) {
          const message = err instanceof Error ? err.message : "Bracket order failed";
          const code =
            typeof err === "object" && err !== null && "code" in err
              ? String((err as { code?: unknown }).code ?? "")
              : "";
          // Practice/Explore JWTs are refused server-side — tell the user
          // why, alongside the backend's own message.
          if (code === "practice_unsupported" || code === "mode_blocked") {
            showStatus(`${message} — brackets need Live mode`, "error", 8000);
          } else {
            showStatus(message, "error", 8000);
          }
        }
        return;
      }

      const params: PlaceOrderParams = {
        symbol: sym,
        exchange: exch,
        action,
        quantity: qty,
        orderType,
        product,
        price: orderType === "LIMIT" ? price : 0,
        strategy: "FlintScalper",
      };
      showStatus(`${action} ${sym} × ${qty}…`, "pending", 0);
      try {
        await placeOrder(params);
        // Placement ≠ fill — report what actually happened.
        showStatus(`${action} ${sym} placed`, "success");
        announceOrder(action, sym, qty);
      } catch (err) {
        showStatus(err instanceof Error ? err.message : "Order failed", "error");
      }
    },
    [lots, lotSize, lotSizeVerified, refreshLotSize, orderType, limitPrice, slPoints, targetPoints, product, showStatus, announceOrder, isExplore],
  );

  const handleOrder = useCallback(
    (sym: string | null, exch: string, action: OrderAction) => {
      if (oneClick) {
        void executeOrder(sym, exch, action);
      } else {
        if (sym) setPendingOrder({ sym, exch, action });
      }
    },
    [oneClick, executeOrder],
  );

  const confirmOrder = useCallback(() => {
    if (pendingOrder) {
      void executeOrder(pendingOrder.sym, pendingOrder.exch, pendingOrder.action);
      setPendingOrder(null);
    }
  }, [pendingOrder, executeOrder]);

  const confirmCloseAll = useCallback(async () => {
    setCloseAllOpen(false);
    if (isExplore) {
      showStatus("Connect a broker to manage live orders", "error");
      return;
    }
    showStatus("Closing all…", "pending", 0);
    try {
      await closePosition("FlintScalper");
      showStatus("All positions closed", "success");
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Close failed", "error");
    }
  }, [showStatus, isExplore]);

  const confirmCancelAll = useCallback(async () => {
    setCancelAllOpen(false);
    if (isExplore) {
      showStatus("Connect a broker to manage live orders", "error");
      return;
    }
    showStatus("Cancelling…", "pending", 0);
    try {
      await cancelAllOrders("FlintScalper");
      showStatus("All orders cancelled", "success");
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Cancel failed", "error");
    }
  }, [showStatus, isExplore]);

  // Keyboard shortcuts — only when focused
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!focused || !e.shiftKey) return;
      switch (e.key) {
        case "ArrowLeft":
          e.preventDefault();
          handleOrder(ceSymbol, optExch, "SELL");
          break;
        case "ArrowUp":
          e.preventDefault();
          handleOrder(ceSymbol, optExch, "BUY");
          break;
        case "ArrowRight":
          e.preventDefault();
          handleOrder(peSymbol, optExch, "SELL");
          break;
        case "ArrowDown":
          e.preventDefault();
          handleOrder(peSymbol, optExch, "BUY");
          break;
        case "Escape":
          e.preventDefault();
          setPendingOrder(null);
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focused, ceSymbol, peSymbol, optExch, handleOrder]);

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        if (!containerRef.current?.contains(e.relatedTarget as Node)) setFocused(false);
      }}
      className="h-full flex flex-col bg-surface-base text-text-primary focus:outline-none overflow-hidden"
    >
      <ScalperControls
        symbol={symbol}
        onSymbolChange={setSymbol}
        expiries={expiries}
        expiriesError={expiriesError}
        expiry={expiry}
        onExpiryChange={setExpiry}
        onRetryExpiries={() => void fetchExpiries()}
        ceStrike={ceStrike}
        onCeOffsetDec={() => setCeOffset((o) => o - 1)}
        onCeOffsetInc={() => setCeOffset((o) => o + 1)}
        peStrike={peStrike}
        onPeOffsetDec={() => setPeOffset((o) => o - 1)}
        onPeOffsetInc={() => setPeOffset((o) => o + 1)}
        status={status}
        focused={focused}
        lots={lots}
        lotSize={lotSize}
        lotSizeVerified={lotSizeVerified}
        onLotsDec={() => setLots((l) => Math.max(1, l - 1))}
        onLotsInc={() => setLots((l) => l + 1)}
        product={product}
        onProductChange={setProduct}
        orderType={orderType}
        onOrderTypeChange={setOrderType}
        limitPrice={limitPrice}
        onLimitPriceChange={setLimitPrice}
        slPoints={slPoints}
        onSlPointsChange={setSlPoints}
        targetPoints={targetPoints}
        onTargetPointsChange={setTargetPoints}
        interval={interval}
        onIntervalChange={setInterval_}
        oneClick={oneClick}
        onOneClickToggle={() => setOneClick((v) => !v)}
      />

      <ScalperChartPanel
        symbol={symbol}
        spotExch={spotExch}
        optExch={optExch}
        ceSymbol={ceSymbol}
        peSymbol={peSymbol}
        ceStrike={ceStrike}
        peStrike={peStrike}
        atmStrike={atmStrike}
        lots={lots}
        interval={interval}
        ticks={ticks}
        onOrder={handleOrder}
        onCloseAll={() => setCloseAllOpen(true)}
        onCancelAll={() => setCancelAllOpen(true)}
      />

      <OrderConfirmModal
        pendingOrder={pendingOrder}
        lots={lots}
        lotSize={lotSize}
        product={product}
        orderType={orderType}
        limitPrice={limitPrice}
        slPoints={slPoints}
        targetPoints={targetPoints}
        onConfirm={confirmOrder}
        onCancel={() => setPendingOrder(null)}
      />

      <CloseAllDialog
        open={closeAllOpen}
        onOpenChange={setCloseAllOpen}
        onConfirm={() => void confirmCloseAll()}
      />

      <CancelAllDialog
        open={cancelAllOpen}
        onOpenChange={setCancelAllOpen}
        onConfirm={() => void confirmCancelAll()}
      />
    </div>
  );
}

export default memo(ScalperWidget);
