import type { WsTick, WsMode, WsInstrument } from "@/types/api";
import { safeParse, wsMessageSchema } from "@/lib/safeParse";

// ---------------------------------------------------------------------------
// Public handler types
// ---------------------------------------------------------------------------

/** Handler for LTP and quote-mode ticks. */
export type TickHandler = (tick: WsTick) => void;
/** Handler for depth-mode ticks (raw map, bids/asks arrays present). */
export type DepthTickHandler = (data: Record<string, unknown>) => void;
/** Unified per-mode handler — depth mode receives the raw depth map. */
export type ModeTickHandler = TickHandler | DepthTickHandler;

/** Shape used by batchSubscribe — an instrument with its target mode. */
export interface SubscribeRequest {
  instrument: WsInstrument;
  mode: WsMode;
}

/** Metadata stored per subscribed symbol (keyed by "EXCHANGE:SYMBOL:mode"). */
interface SubscriptionInfo {
  instrument: WsInstrument;
  mode: WsMode;
  /** Number of active callers holding this subscription. */
  refCount: number;
}

type TickCallback = (tick: WsTick) => void;
type StatusCallback = (connected: boolean) => void;

export class WebSocketService {
  private ws: WebSocket | null = null;
  private reconnectDelay = 1000;
  private readonly maxDelay = 30000;
  private readonly heartbeatInterval = 30000;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly pongTimeout = 10000; // 10s to receive pong before treating as dead
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingMessages: Record<string, unknown>[] = [];
  private subscriptions: Record<WsMode, WsInstrument[]> = {
    ltp: [], quote: [], depth: [],
  };
  private connected = false;
  private shouldConnect = false;

  /** Cumulative count of reconnection attempts since the service was created. */
  private reconnectCount = 0;
  /** `Date.now()` timestamp of the last tick received (0 = no ticks yet). */
  private lastTickTimestamp = 0;

  // Legacy broadcast callbacks — kept for backward compatibility.
  private tickCallbacks = new Set<TickCallback>();
  private depthCallbacks = new Set<(data: Record<string, unknown>) => void>();
  private statusCallbacks = new Set<StatusCallback>();

  // Per-mode handler sets (new in v2). Each set holds handlers registered via
  // registerHandler(). Ticks are dispatched to the matching mode's set AND to
  // the legacy tickCallbacks/depthCallbacks for backward compat.
  private modeHandlers: Record<WsMode, Set<ModeTickHandler>> = {
    ltp: new Set(),
    quote: new Set(),
    depth: new Set(),
  };

  // Reference-counted subscription map.
  // Key: "<EXCHANGE>:<SYMBOL>:<mode>", value: SubscriptionInfo.
  private subscriptionMap = new Map<string, SubscriptionInfo>();

  constructor(private url: string, private apiKey: string = "") {}

  get isConnected(): boolean { return this.connected; }

  /**
   * Diagnostic snapshot useful for health panels and debugging.
   *
   * - `reconnectCount` — number of reconnection attempts since service creation.
   * - `lastTickTimestamp` — `Date.now()` value of the last tick received (0 = none yet).
   * - `tickAgeMs` — milliseconds since the last tick (-1 if no ticks ever received).
   */
  get diagnostics(): { reconnectCount: number; lastTickTimestamp: number; tickAgeMs: number } {
    return {
      reconnectCount: this.reconnectCount,
      lastTickTimestamp: this.lastTickTimestamp,
      tickAgeMs: this.lastTickTimestamp > 0 ? Date.now() - this.lastTickTimestamp : -1,
    };
  }

  onTick(cb: TickCallback): () => void {
    this.tickCallbacks.add(cb);
    return () => this.tickCallbacks.delete(cb);
  }

  onDepth(cb: (data: Record<string, unknown>) => void): () => void {
    this.depthCallbacks.add(cb);
    return () => this.depthCallbacks.delete(cb);
  }

  onStatus(cb: StatusCallback): () => void {
    this.statusCallbacks.add(cb);
    return () => this.statusCallbacks.delete(cb);
  }

  // ---------------------------------------------------------------------------
  // Mode-specific handler registration (new API)
  // ---------------------------------------------------------------------------

  /**
   * Register a handler that receives ticks only for the given mode.
   *
   * - `"ltp"` / `"quote"` handlers receive `WsTick` objects.
   * - `"depth"` handlers receive a raw `Record<string, unknown>` (bids/asks present).
   *
   * Returns an unregister function — call it when the component unmounts.
   *
   * @example
   * const off = wsService.registerHandler("ltp", (tick) => { ... });
   * // on cleanup:
   * off();
   */
  registerHandler(mode: WsMode, handler: ModeTickHandler): () => void {
    this.modeHandlers[mode].add(handler);
    return () => {
      this.modeHandlers[mode].delete(handler);
    };
  }

  // ---------------------------------------------------------------------------
  // Batch subscribe with optional delay between messages
  // ---------------------------------------------------------------------------

  /**
   * Subscribe to multiple instruments, optionally sending each subscription
   * message `delayMs` milliseconds apart. Useful when loading a large option
   * chain (80+ symbols) to avoid overwhelming the WS server.
   *
   * Default delay is 50 ms. Pass 0 for immediate batching.
   *
   * Reference counts each subscription — if a symbol is already subscribed by
   * another caller the ref count is incremented and no duplicate wire message
   * is sent.
   */
  batchSubscribe(requests: SubscribeRequest[], delayMs = 50): Promise<void> {
    return new Promise((resolve) => {
      // Group by mode so we can send one subscribe message per mode per batch.
      const byMode = new Map<WsMode, WsInstrument[]>();
      for (const req of requests) {
        const key = `${req.instrument.exchange}:${req.instrument.symbol}:${req.mode}`;
        const existing = this.subscriptionMap.get(key);
        if (existing) {
          // Already subscribed — just increment ref count, skip wire message.
          existing.refCount += 1;
          continue;
        }
        this.subscriptionMap.set(key, {
          instrument: req.instrument,
          mode: req.mode,
          refCount: 1,
        });
        const group = byMode.get(req.mode) ?? [];
        group.push(req.instrument);
        byMode.set(req.mode, group);
      }

      // Also update the plain subscriptions record (used by resubscribeAll).
      for (const [mode, instruments] of byMode) {
        this.subscriptions[mode] = [
          ...this.subscriptions[mode],
          ...instruments.filter(
            (inst) =>
              !this.subscriptions[mode].some(
                (s) => s.symbol === inst.symbol && s.exchange === inst.exchange,
              ),
          ),
        ];
      }

      if (byMode.size === 0) {
        resolve();
        return;
      }

      const modes = [...byMode.entries()];
      let i = 0;

      const sendNext = (): void => {
        if (i >= modes.length) {
          resolve();
          return;
        }
        const [mode, instruments] = modes[i++];
        this.send({
          action: "subscribe",
          symbols: instruments.map((inst) => ({
            symbol: inst.symbol,
            exchange: inst.exchange,
          })),
          mode: mode.toUpperCase(),
        });
        if (delayMs > 0) {
          setTimeout(sendNext, delayMs);
        } else {
          sendNext();
        }
      };

      sendNext();
    });
  }

  /**
   * Release a reference-counted subscription. The WS unsubscribe message is
   * only sent when the ref count drops to zero (i.e. no other caller is still
   * using this subscription).
   *
   * Since `unsubscribe()` itself became reference-counted, this is a thin
   * single-instrument delegate — kept for API compatibility — whose one
   * difference is that releasing a never-subscribed instrument is a no-op
   * (a direct `unsubscribe()` would still send the wire message).
   */
  releaseSubscription(instrument: WsInstrument, mode: WsMode): void {
    const key = `${instrument.exchange}:${instrument.symbol}:${mode}`;
    if (!this.subscriptionMap.has(key)) return;
    this.unsubscribe([instrument], mode);
  }

  // ---------------------------------------------------------------------------
  // Diagnostic helpers
  // ---------------------------------------------------------------------------

  /** Total number of actively reference-counted subscription slots. */
  getSubscriptionCount(): number {
    return this.subscriptionMap.size;
  }

  /**
   * Returns a deduplicated list of "EXCHANGE:SYMBOL" strings for all currently
   * subscribed instruments (across all modes).
   */
  getSubscribedSymbols(): string[] {
    const seen = new Set<string>();
    for (const info of this.subscriptionMap.values()) {
      seen.add(`${info.instrument.exchange}:${info.instrument.symbol}`);
    }
    return [...seen];
  }

  connect(): void {
    this.shouldConnect = true;
    this.doConnect();
  }

  disconnect(): void {
    this.shouldConnect = false;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.close();
      this.ws = null;
    }
    this.setConnected(false);
  }

  /**
   * Subscribe to instruments in the given mode. Reference-counted: when
   * another consumer already holds a subscription for the same
   * instrument+mode, its ref count is incremented and no duplicate wire
   * message is sent. Every `subscribe()` call must be balanced by exactly
   * one `unsubscribe()` (or `releaseSubscription()`) so the wire
   * unsubscribe fires only when the LAST consumer releases — otherwise
   * closing one widget would silently freeze live prices in another widget
   * sharing the instrument (the Scalper/Time & Sales bug).
   */
  subscribe(instruments: WsInstrument[], mode: WsMode = "ltp"): void {
    const newInsts: WsInstrument[] = [];
    const seenInCall = new Set<string>();
    for (const inst of instruments) {
      const key = `${inst.exchange}:${inst.symbol}:${mode}`;
      // One call = one consumer = one reference per instrument, even if the
      // caller passed duplicates.
      if (seenInCall.has(key)) continue;
      seenInCall.add(key);
      const existing = this.subscriptionMap.get(key);
      if (existing) {
        // Another consumer already holds this subscription — take a
        // reference instead of sending a duplicate wire message.
        existing.refCount += 1;
        continue;
      }
      this.subscriptionMap.set(key, { instrument: inst, mode, refCount: 1 });
      newInsts.push(inst);
    }
    if (newInsts.length === 0) return;
    // Keep the plain per-mode record (used by resubscribeAll) in sync.
    this.subscriptions[mode] = [
      ...this.subscriptions[mode],
      ...newInsts.filter(
        (inst) =>
          !this.subscriptions[mode].some(
            (s) => s.symbol === inst.symbol && s.exchange === inst.exchange,
          ),
      ),
    ];
    // OpenAlgo v2 WS protocol: { action: "subscribe", symbols: [...], mode: "LTP" }
    this.send({
      action: "subscribe",
      symbols: newInsts.map((i) => ({ symbol: i.symbol, exchange: i.exchange })),
      mode: mode.toUpperCase(),
    });
  }

  /**
   * Release one reference per instrument in the given mode. Reference-
   * counted: the wire `unsubscribe` message is sent only for instruments
   * whose LAST consumer has released. While another consumer still holds a
   * reference the server subscription stays live, so per-consumer handler
   * cleanup (via `registerHandler`/`onTick` unregister functions) never
   * silences the feed for the surviving consumer.
   *
   * Instruments not tracked in the ref-count map are hard-unsubscribed
   * (wire message sent) so desync never leaves a zombie server
   * subscription.
   */
  unsubscribe(instruments: WsInstrument[], mode: WsMode = "ltp"): void {
    const dropped: WsInstrument[] = [];
    const seenInCall = new Set<string>();
    for (const inst of instruments) {
      const key = `${inst.exchange}:${inst.symbol}:${mode}`;
      if (seenInCall.has(key)) continue;
      seenInCall.add(key);
      const info = this.subscriptionMap.get(key);
      if (info && info.refCount > 1) {
        // Another consumer still holds this subscription — keep it live.
        info.refCount -= 1;
        continue;
      }
      // Last reference (or untracked hard unsubscribe) — drop it for real.
      this.subscriptionMap.delete(key);
      dropped.push(inst);
    }
    if (dropped.length === 0) return;
    this.subscriptions[mode] = this.subscriptions[mode].filter(
      (s) => !dropped.some(
        (inst) => s.symbol === inst.symbol && s.exchange === inst.exchange
      )
    );
    this.send({
      action: "unsubscribe",
      symbols: dropped.map((i) => ({ symbol: i.symbol, exchange: i.exchange })),
    });
  }

  getSubscriptions(mode: WsMode): WsInstrument[] {
    return [...this.subscriptions[mode]];
  }

  private doConnect(): void {
    if (!this.shouldConnect) return;
    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      this.startHeartbeat();
      // OpenAlgo v2: authenticate first, then subscribe after auth response
      if (this.apiKey) {
        this.send({ action: "authenticate", api_key: this.apiKey });
        // Don't set connected or resubscribe yet — wait for auth response in onmessage
      } else {
        // No auth needed — connect and subscribe immediately
        this.setConnected(true);
        this.resubscribeAll();
      }
    };

    this.ws.onclose = () => {
      this.setConnected(false);
      this.stopHeartbeat();
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = safeParse(event.data as string, wsMessageSchema);
        if (!msg) return; // Non-object frame (plain string, binary, corrupt JSON) — discard

        // Auth response: { type: "auth", status: "success", message: "Authentication successful" }
        if (msg["type"] === "auth") {
          if (msg["status"] === "success") {
            if (!this.connected) {
              this.setConnected(true);
              this.resubscribeAll();
              this.drainPendingMessages();
            }
          } else {
            // Auth failure — close the socket so the reconnect cycle kicks in.
            // This prevents the service from hanging in an unauthenticated state.
            console.warn("[WS] Auth failed:", msg["message"] ?? "unknown reason");
            this.ws?.close();
          }
          return;
        }

        // Subscription ack: { type: "subscribe", status: "success", subscriptions: [...] }
        if (msg["type"] === "subscribe" || msg["type"] === "unsubscribe") {
          return;
        }

        // Control/system messages (action field: pong, etc.)
        if (typeof msg["action"] === "string") {
          if (msg["action"] === "pong" && this.pongTimer) {
            clearTimeout(this.pongTimer);
            this.pongTimer = null;
          }
          return;
        }

        // OpenAlgo v2 market data: { type: "market_data", mode: 1|2|3, topic: "SYMBOL.EXCHANGE", data: {...} }
        const tickData = (msg["data"] && typeof msg["data"] === "object")
          ? msg["data"] as Record<string, unknown>
          : msg; // Fallback: try root level for backwards compatibility

        const symbol = tickData["symbol"];
        if (typeof symbol !== "string" || symbol.length === 0) {
          // Silently ignore system messages without symbol (auth responses, etc.)
          if (msg["type"] || msg["status"] || msg["message"]) return;
          console.warn("[WS] Malformed tick: missing symbol", msg);
          return;
        }

        const exchange = typeof tickData["exchange"] === "string" ? tickData["exchange"] : "";

        // Record the arrival time of every confirmed market-data tick.
        // Used by diagnostics.tickAgeMs to detect stale/frozen data feeds.
        this.lastTickTimestamp = Date.now();

        // Depth mode (mode 3) sends bids/asks without ltp
        if (Array.isArray(tickData["bids"]) || Array.isArray(tickData["asks"])) {
          // Legacy broadcast
          this.depthCallbacks.forEach((cb) => cb(tickData));
          // Mode-specific handlers
          this.modeHandlers["depth"].forEach((cb) =>
            (cb as DepthTickHandler)(tickData),
          );
          return;
        }

        const ltp = tickData["ltp"];
        if (typeof ltp !== "number") return; // Quote/other mode without LTP — skip silently

        const tick: WsTick = {
          symbol,
          exchange,
          ltp,
          open: typeof tickData["open"] === "number" ? tickData["open"] : undefined,
          high: typeof tickData["high"] === "number" ? tickData["high"] : undefined,
          low: typeof tickData["low"] === "number" ? tickData["low"] : undefined,
          close: typeof tickData["close"] === "number" ? tickData["close"] : undefined,
          volume: typeof tickData["volume"] === "number" ? tickData["volume"] : undefined,
          change: typeof tickData["change"] === "number" ? tickData["change"] : undefined,
          pct: typeof tickData["pct"] === "number" ? tickData["pct"] : undefined,
        };

        // Legacy broadcast — all tick callbacks receive every LTP/quote tick.
        this.tickCallbacks.forEach((cb) => cb(tick));

        // Mode-specific dispatch. The incoming WS message carries a numeric mode
        // field (1 = LTP, 2 = Quote). Map that to the string mode key. If absent,
        // dispatch to both "ltp" and "quote" handlers for safety.
        const wsMode = msg["mode"];
        if (wsMode === 2) {
          this.modeHandlers["quote"].forEach((cb) => (cb as TickHandler)(tick));
        } else if (wsMode === 1) {
          this.modeHandlers["ltp"].forEach((cb) => (cb as TickHandler)(tick));
        } else if (wsMode === 4) {
          // Mode 4 = Depth (OpenAlgo v2 wire format). The bids/asks check above
          // already handles depth messages that carry explicit bids/asks arrays.
          // This branch handles depth ticks where the broker adapter also sends
          // an ltp field alongside the depth payload (tick is already assembled).
          this.modeHandlers["depth"].forEach((handler) => (handler as DepthTickHandler)(tickData));
        } else {
          // Unknown or missing mode — dispatch to all non-depth mode handlers.
          this.modeHandlers["ltp"].forEach((cb) => (cb as TickHandler)(tick));
          this.modeHandlers["quote"].forEach((cb) => (cb as TickHandler)(tick));
        }
      } catch {
        console.warn("[WS] Failed to process message", event.data);
      }
    };
  }

  private static readonly MAX_PENDING = 50;

  private send(payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    } else if (payload.action === "subscribe") {
      // Buffer subscription requests to replay after reconnect.
      // Deduplicate by symbol+exchange+mode — avoid redundant entries when the
      // same instrument is subscribed multiple times before a connection is up.
      const incomingSymbols = Array.isArray(payload.symbols)
        ? (payload.symbols as Array<{ symbol: string; exchange: string }>)
        : [];
      const incomingMode = typeof payload.mode === "string" ? payload.mode : "";

      // Remove any existing pending entry that overlaps with these symbols+mode.
      this.pendingMessages = this.pendingMessages.filter((pending) => {
        if (pending.mode !== incomingMode) return true;
        const ps = Array.isArray(pending.symbols)
          ? (pending.symbols as Array<{ symbol: string; exchange: string }>)
          : [];
        // Keep if there is NO overlap with incoming symbols.
        return !ps.some((p) =>
          incomingSymbols.some(
            (n) => n.symbol === p.symbol && n.exchange === p.exchange,
          ),
        );
      });

      this.pendingMessages.push(payload);

      // Hard cap — drop oldest entries to stay within budget.
      if (this.pendingMessages.length > WebSocketService.MAX_PENDING) {
        this.pendingMessages = this.pendingMessages.slice(
          this.pendingMessages.length - WebSocketService.MAX_PENDING,
        );
      }
    }
  }

  private drainPendingMessages(): void {
    // Only replay messages that are still relevant — i.e. the symbol is still
    // in our subscriptionMap (user hasn't unsubscribed during the outage).
    const msgs = this.pendingMessages.splice(0);
    for (const msg of msgs) {
      const symbols = Array.isArray(msg.symbols)
        ? (msg.symbols as Array<{ symbol: string; exchange: string }>)
        : [];
      const mode = typeof msg.mode === "string" ? (msg.mode.toLowerCase() as WsMode) : "ltp";
      const fresh = symbols.filter((s) =>
        this.subscriptionMap.has(`${s.exchange}:${s.symbol}:${mode}`),
      );
      if (fresh.length > 0) {
        this.send({ ...msg, symbols: fresh });
      }
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.send({ action: "ping" });
      // Start pong timeout — if no pong within 10s, connection is dead
      this.pongTimer = setTimeout(() => {
        console.warn("[WS] Pong timeout — connection appears dead, reconnecting");
        this.ws?.close();
      }, this.pongTimeout);
    }, this.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.pongTimer) {
      clearTimeout(this.pongTimer);
      this.pongTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (!this.shouldConnect) return;
    this.reconnectCount++;
    // Exponential backoff with jitter: base 1s, multiplier 2, max 30s, jitter +/-500ms
    const jitter = Math.round((Math.random() - 0.5) * 1000); // -500ms to +500ms
    const delay = Math.max(0, Math.min(this.reconnectDelay + jitter, this.maxDelay));
    console.info(`[WS] Scheduling reconnect in ${delay}ms (base=${this.reconnectDelay}ms, jitter=${jitter}ms)`);
    this.reconnectTimer = setTimeout(() => {
      this.doConnect();
    }, delay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxDelay);
  }

  private resubscribeAll(): void {
    for (const mode of ["ltp", "quote", "depth"] as WsMode[]) {
      if (this.subscriptions[mode].length > 0) {
        this.send({
          action: "subscribe",
          symbols: this.subscriptions[mode].map((i) => ({ symbol: i.symbol, exchange: i.exchange })),
          mode: mode.toUpperCase(),
        });
      }
    }
  }

  private setConnected(value: boolean): void {
    this.connected = value;
    this.statusCallbacks.forEach((cb) => cb(value));
  }

  /**
   * Update the WS URL and API key without losing existing subscriptions.
   * If the service is currently connected, it disconnects and reconnects
   * immediately so the new credentials take effect.
   */
  updateCredentials(url: string, apiKey: string): void {
    const credentialsChanged = this.url !== url || this.apiKey !== apiKey;
    if (!credentialsChanged) return;
    this.url = url;
    this.apiKey = apiKey;
    if (this.shouldConnect) {
      // Tear down the existing connection — doConnect will be called by
      // scheduleReconnect → but we want immediate reconnection, so call
      // disconnect (clears shouldConnect) then connect() again.
      this.disconnect();
      this.connect();
    }
  }
}

let instance: WebSocketService | null = null;

export function getWsService(url?: string, apiKey?: string): WebSocketService | null {
  if (!instance && url) {
    instance = new WebSocketService(url, apiKey || "");
  } else if (instance && url && apiKey !== undefined) {
    instance.updateCredentials(url, apiKey);
  }
  return instance;
}

export function resetWsService(): void {
  instance?.disconnect();
  instance = null;
}
