import type { WsTick, WsMode, WsInstrument, WsAction } from "@/types/api";

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
  private statusCallbacks = new Set<StatusCallback>();

  constructor(private url: string) {}

  get isConnected(): boolean { return this.connected; }

  onTick(cb: TickCallback): () => void {
    this.tickCallbacks.add(cb);
    return () => this.tickCallbacks.delete(cb);
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
    const action: WsAction = `subscribe_${mode}` as WsAction;
    this.send({ action, instruments: newInsts });
  }

  unsubscribe(instruments: WsInstrument[], mode: WsMode = "ltp"): void {
    this.subscriptions[mode] = this.subscriptions[mode].filter(
      (s) => !instruments.some(
        (inst) => s.symbol === inst.symbol && s.exchange === inst.exchange
      )
    );
    const action: WsAction = `unsubscribe_${mode}` as WsAction;
    this.send({ action, instruments });
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
      this.setConnected(true);
      this.startHeartbeat();
      this.resubscribeAll();
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
        const data = JSON.parse(event.data);
        if (data.action === "pong") return;
        const tick: WsTick = {
          symbol: data.symbol || "",
          exchange: data.exchange || "",
          ltp: data.ltp ?? 0,
          open: data.open,
          high: data.high,
          low: data.low,
          close: data.close,
          volume: data.volume,
          change: data.change,
          pct: data.pct,
        };
        this.tickCallbacks.forEach((cb) => cb(tick));
      } catch {
        // ignore malformed messages
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
        const action: WsAction = `subscribe_${mode}` as WsAction;
        this.send({ action, instruments: this.subscriptions[mode] });
      }
    }
  }

  private setConnected(value: boolean): void {
    this.connected = value;
    this.statusCallbacks.forEach((cb) => cb(value));
  }
}

let instance: WebSocketService | null = null;

export function getWsService(url?: string): WebSocketService {
  if (!instance && url) {
    instance = new WebSocketService(url);
  }
  return instance!;
}

export function resetWsService(): void {
  instance?.disconnect();
  instance = null;
}
