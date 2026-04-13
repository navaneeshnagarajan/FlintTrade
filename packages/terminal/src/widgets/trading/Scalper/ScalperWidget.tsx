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
} from "@/services/api";
import { getLotSize } from "@/services/ftApi";
import useWebSocket from "@/hooks/useWebSocket";
import { useVoiceAlert } from "@/hooks/useVoiceAlert";
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

function ScalperWidget(_props: WidgetProps) {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [lots, setLots] = useState(1);
  const [product, setProduct] = useState<ProductType>("MIS");
  const [orderType, setOrderType] = useState<OrderTypeValue>("MARKET");
  const [sl, setSl] = useState("");
  const [target, setTarget] = useState("");
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

  // Dynamic lot size — fetch from backend, fall back to built-in config
  const [dynamicLotSize, setDynamicLotSize] = useState<number | null>(null);
  const lotSize = dynamicLotSize ?? cfg.lotSize;

  useEffect(() => {
    let cancelled = false;
    setDynamicLotSize(null); // reset on symbol change
    getLotSize(symbol, optExch)
      .then((res) => {
        if (!cancelled && res.lot_size > 0) {
          setDynamicLotSize(res.lot_size);
        }
      })
      .catch(() => {
        // Fallback to built-in config silently
      });
    return () => { cancelled = true; };
  }, [symbol, optExch]);

  const ceStrike = atmStrike != null ? atmStrike + ceOffset * step : null;
  const peStrike = atmStrike != null ? atmStrike + peOffset * step : null;

  const ceSymbol = ceStrike != null ? buildOptionSymbol(symbol, expiry, ceStrike, "CE") : null;
  const peSymbol = peStrike != null ? buildOptionSymbol(symbol, expiry, peStrike, "PE") : null;

  const instruments = useMemo<WsInstrument[]>(() => {
    const list: WsInstrument[] = [{ symbol, exchange: spotExch }];
    if (ceSymbol) list.push({ symbol: ceSymbol, exchange: optExch });
    if (peSymbol) list.push({ symbol: peSymbol, exchange: optExch });
    return list;
  }, [symbol, spotExch, ceSymbol, peSymbol, optExch]);

  const { ticks } = useWebSocket(instruments, "quote");

  const spotKey = `${spotExch}:${symbol}`;
  const spotTick = ticks[spotKey];
  const spotLtp = spotTick?.ltp ?? spotTick?.close ?? null;

  // Fetch expiries on symbol change
  const fetchExpiries = useCallback(
    async (signal?: { cancelled: boolean }) => {
      setExpiriesError(false);
      setExpiries([]);
      setExpiry("");
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
    [symbol, optExch],
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
    }
  }, [spotLtp, step]);

  // Fallback: fetch from API once if tick not yet available
  useEffect(() => {
    if (spotLtp != null || !symbol) return;
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
      const qty = lots * lotSize;
      const params: PlaceOrderParams = {
        symbol: sym,
        exchange: exch,
        action,
        quantity: qty,
        orderType,
        product,
        price: 0,
        strategy: "FlintScalper",
      };
      showStatus(`${action} ${sym} × ${qty}…`, "pending", 0);
      try {
        await placeOrder(params);
        showStatus(`${action} ${sym} filled`, "success");
        announceOrder(action, sym, qty);
      } catch (err) {
        showStatus(err instanceof Error ? err.message : "Order failed", "error");
      }
    },
    [lots, lotSize, orderType, product, showStatus, announceOrder],
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
    showStatus("Closing all…", "pending", 0);
    try {
      await closePosition("FlintScalper");
      showStatus("All positions closed", "success");
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Close failed", "error");
    }
  }, [showStatus]);

  const confirmCancelAll = useCallback(async () => {
    setCancelAllOpen(false);
    showStatus("Cancelling…", "pending", 0);
    try {
      await cancelAllOrders("FlintScalper");
      showStatus("All orders cancelled", "success");
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Cancel failed", "error");
    }
  }, [showStatus]);

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
        onLotsDec={() => setLots((l) => Math.max(1, l - 1))}
        onLotsInc={() => setLots((l) => l + 1)}
        product={product}
        onProductChange={setProduct}
        orderType={orderType}
        onOrderTypeChange={setOrderType}
        interval={interval}
        onIntervalChange={setInterval_}
        sl={sl}
        onSlChange={setSl}
        target={target}
        onTargetChange={setTarget}
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
        sl={sl}
        target={target}
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
