/**
 * WebSocket client for OpenAlgo real-time data (ws://localhost:8765).
 * Supports subscribe/unsubscribe for LTP, Quote, and Depth modes.
 * Auto-reconnects with exponential backoff.
 * Dispatches tick updates via custom DOM events.
 */

const WS_URL = import.meta.env.VITE_WS_URL || "ws://127.0.0.1:8765";

class WebSocketService {
  constructor() {
    this._ws = null;
    this._reconnectDelay = 1000;
    this._maxDelay = 30000;
    this._subscriptions = { ltp: [], quote: [], depth: [] };
    this._connected = false;
    this._shouldConnect = false;
  }

  get connected() {
    return this._connected;
  }

  connect() {
    this._shouldConnect = true;
    this._doConnect();
  }

  _doConnect() {
    if (!this._shouldConnect) return;
    try {
      this._ws = new WebSocket(WS_URL);
    } catch {
      this._scheduleReconnect();
      return;
    }

    this._ws.onopen = () => {
      this._connected = true;
      this._reconnectDelay = 1000;
      window.dispatchEvent(new CustomEvent("ws:status", { detail: { connected: true } }));
      this._resubscribeAll();
    };

    this._ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        window.dispatchEvent(new CustomEvent("ws:tick", { detail: data }));
      } catch { /* ignore non-JSON */ }
    };

    this._ws.onclose = () => {
      this._connected = false;
      window.dispatchEvent(new CustomEvent("ws:status", { detail: { connected: false } }));
      this._scheduleReconnect();
    };

    this._ws.onerror = () => {
      this._ws?.close();
    };
  }

  _scheduleReconnect() {
    if (!this._shouldConnect) return;
    setTimeout(() => this._doConnect(), this._reconnectDelay);
    this._reconnectDelay = Math.min(this._reconnectDelay * 2, this._maxDelay);
  }

  _send(payload) {
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(payload));
    }
  }

  subscribe(instruments, mode = "ltp") {
    const actionMap = { ltp: "subscribe_ltp", quote: "subscribe_quote", depth: "subscribe_depth" };
    const action = actionMap[mode] || "subscribe_ltp";
    const newInsts = instruments.filter(
      (i) => !this._subscriptions[mode]?.some((s) => s.symbol === i.symbol && s.exchange === i.exchange)
    );
    if (newInsts.length === 0) return;
    this._subscriptions[mode] = [...(this._subscriptions[mode] || []), ...newInsts];
    this._send({ action, instruments: newInsts });
  }

  unsubscribe(instruments, mode = "ltp") {
    const actionMap = { ltp: "unsubscribe_ltp", quote: "unsubscribe_quote", depth: "unsubscribe_depth" };
    this._subscriptions[mode] = (this._subscriptions[mode] || []).filter(
      (s) => !instruments.some((i) => i.symbol === s.symbol && i.exchange === s.exchange)
    );
    this._send({ action: actionMap[mode] || "unsubscribe_ltp", instruments });
  }

  _resubscribeAll() {
    for (const [mode, instruments] of Object.entries(this._subscriptions)) {
      if (instruments.length > 0) {
        const actionMap = { ltp: "subscribe_ltp", quote: "subscribe_quote", depth: "subscribe_depth" };
        this._send({ action: actionMap[mode], instruments });
      }
    }
  }

  disconnect() {
    this._shouldConnect = false;
    this._ws?.close();
  }
}

export const wsService = new WebSocketService();
export default wsService;
