import type { WsTick, WsMode, WsInstrument } from "@/types/api";

type TickCallback = (tick: WsTick) => void;
type StatusCallback = (connected: boolean) => void;

export class WebSocketService {
  private ws: WebSocket | null = null;
  private reconnectDelay = 1000;
  private readonly maxDelay = 30000;
  private readonly heartbeatInterval = 30000;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private subscriptions: Record<WsMode, WsInstrument[]> = {
    ltp: [], quote: [], depth: [],
  };
  private connected = false;
  private shouldConnect = false;
  private tickCallbacks = new Set<TickCallback>();
  private depthCallbacks = new Set<(data: Record<string, unknown>) => void>();
  private statusCallbacks = new Set<StatusCallback>();

  constructor(private url: string, private apiKey: string = "") {}

  get isConnected(): boolean { return this.connected; }

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

  subscribe(instruments: WsInstrument[], mode: WsMode = "ltp"): void {
    const newInsts = instruments.filter(
      (inst) => !this.subscriptions[mode].some(
        (s) => s.symbol === inst.symbol && s.exchange === inst.exchange
      )
    );
    if (newInsts.length === 0) return;
    this.subscriptions[mode] = [...this.subscriptions[mode], ...newInsts];
    // OpenAlgo v2 WS protocol: { action: "subscribe", symbols: [...], mode: "LTP" }
    this.send({
      action: "subscribe",
      symbols: newInsts.map((i) => ({ symbol: i.symbol, exchange: i.exchange })),
      mode: mode.toUpperCase(),
    });
  }

  unsubscribe(instruments: WsInstrument[], mode: WsMode = "ltp"): void {
    this.subscriptions[mode] = this.subscriptions[mode].filter(
      (s) => !instruments.some(
        (inst) => s.symbol === inst.symbol && s.exchange === inst.exchange
      )
    );
    this.send({
      action: "unsubscribe",
      symbols: instruments.map((i) => ({ symbol: i.symbol, exchange: i.exchange })),
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
        const msg = JSON.parse(event.data) as Record<string, unknown>;

        // Auth response: { type: "auth", status: "success", message: "Authentication successful" }
        if (msg["type"] === "auth" && msg["status"] === "success") {
          if (!this.connected) {
            this.setConnected(true);
            this.resubscribeAll();
          }
          return;
        }

        // Subscription ack: { type: "subscribe", status: "success", subscriptions: [...] }
        if (msg["type"] === "subscribe" || msg["type"] === "unsubscribe") {
          return;
        }

        // Control/system messages (action field: pong, etc.)
        if (typeof msg["action"] === "string") {
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

        // Depth mode (mode 3) sends bids/asks without ltp
        if (Array.isArray(tickData["bids"]) || Array.isArray(tickData["asks"])) {
          this.depthCallbacks.forEach((cb) => cb(tickData));
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
        this.tickCallbacks.forEach((cb) => cb(tick));
      } catch {
        console.warn("[WS] Failed to parse message", event.data);
      }
    };
  }

  private send(payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.send({ action: "ping" });
    }, this.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (!this.shouldConnect) return;
    this.reconnectTimer = setTimeout(() => {
      this.doConnect();
    }, this.reconnectDelay);
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
}

let instance: WebSocketService | null = null;

export function getWsService(url?: string, apiKey?: string): WebSocketService {
  if (!instance && url) {
    instance = new WebSocketService(url, apiKey || "");
  }
  return instance!;
}

export function resetWsService(): void {
  instance?.disconnect();
  instance = null;
}
