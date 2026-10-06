import type { WsTick, WsMode, WsInstrument } from "@/types/api";

export type TickHandler = (tick: WsTick) => void;
export type DepthTickHandler = (data: Record<string, unknown>) => void;
export type ModeTickHandler = TickHandler | DepthTickHandler;
export interface SubscribeRequest { instrument: WsInstrument; mode: WsMode }
export interface WsFailure { kind: "auth" | "network"; reason: string; attempts: number; fatal: boolean }

/** Local interest registry for native REST polling. It never opens a socket. */
export class WebSocketService {
  private interests = new Map<string, { instrument: WsInstrument; mode: WsMode; count: number }>();
  private tickHandlers = new Set<TickHandler>();
  private depthHandlers = new Set<DepthTickHandler>();
  private modeHandlers: Record<WsMode, Set<ModeTickHandler>> = { ltp: new Set(), quote: new Set(), depth: new Set() };
  private lastTickTimestamp = 0;
  get isConnected(): boolean { return false; }
  get diagnostics() {
    return { reconnectCount: 0, lastTickTimestamp: this.lastTickTimestamp,
      tickAgeMs: this.lastTickTimestamp ? Date.now() - this.lastTickTimestamp : -1 };
  }
  onTick(handler: TickHandler): () => void { this.tickHandlers.add(handler); return () => { this.tickHandlers.delete(handler); }; }
  onDepth(handler: DepthTickHandler): () => void { this.depthHandlers.add(handler); return () => { this.depthHandlers.delete(handler); }; }
  registerHandler(mode: WsMode, handler: ModeTickHandler): () => void {
    this.modeHandlers[mode].add(handler); return () => { this.modeHandlers[mode].delete(handler); };
  }
  subscribe(instruments: WsInstrument[], mode: WsMode = "ltp"): void {
    for (const instrument of instruments) {
      const key = `${instrument.exchange}:${instrument.symbol}:${mode}`;
      const existing = this.interests.get(key);
      if (existing) existing.count += 1;
      else this.interests.set(key, { instrument, mode, count: 1 });
    }
  }
  unsubscribe(instruments: WsInstrument[], mode: WsMode = "ltp"): void {
    for (const instrument of instruments) {
      const key = `${instrument.exchange}:${instrument.symbol}:${mode}`;
      const existing = this.interests.get(key);
      if (existing && --existing.count <= 0) this.interests.delete(key);
    }
  }
  batchSubscribe(requests: SubscribeRequest[]): void { for (const request of requests) this.subscribe([request.instrument], request.mode); }
  getSubscriptions(mode: WsMode): WsInstrument[] { return [...this.interests.values()].filter((row) => row.mode === mode).map((row) => row.instrument); }
  getAllSubscriptions(): SubscribeRequest[] { return [...this.interests.values()].map(({ instrument, mode }) => ({ instrument, mode })); }
  publishTick(tick: WsTick): void {
    this.lastTickTimestamp = Date.now();
    this.tickHandlers.forEach((handler) => handler(tick));
    for (const mode of ["ltp", "quote"] as const) this.modeHandlers[mode].forEach((handler) => (handler as TickHandler)(tick));
  }
}
const instance = new WebSocketService();
export function getWsService(): WebSocketService { return instance; }
