/**
 * mockDataEngine.ts
 *
 * Produces realistic Indian market mock data for Demo mode.
 * No network calls — fully self-contained. Safe to use with no broker.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MockTick {
  symbol: string;
  exchange: string;
  ltp: number;
  change: number;
  changePct: number;
  volume: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface MockPosition {
  symbol: string;
  exchange: string;
  product: string;
  quantity: number;
  avgPrice: number;
  ltp: number;
  pnl: number;
  side: "BUY" | "SELL";
}

export interface MockOrder {
  orderId: string;
  symbol: string;
  exchange: string;
  side: "BUY" | "SELL";
  product: string;
  orderType: "MARKET" | "LIMIT";
  quantity: number;
  price: number;
  status: "COMPLETE" | "OPEN" | "REJECTED" | "CANCELLED";
  timestamp: string;
}

export interface MockHolding {
  symbol: string;
  exchange: string;
  quantity: number;
  avgPrice: number;
  ltp: number;
  currentValue: number;
  pnl: number;
  pnlPct: number;
}

// ---------------------------------------------------------------------------
// Base prices — realistic Indian market instruments
// ---------------------------------------------------------------------------

const BASE_PRICES: Record<string, number> = {
  NIFTY:    24150,
  BANKNIFTY: 51200,
  SENSEX:   79800,
  // India VIX + the full MCX commodity set the ticker bar requests, so
  // SILVER/CRUDEOIL/NATURALGAS also show sample prices in Explore/demo mode
  // instead of a "no data" chip (they previously sat empty — only GOLD ticked).
  INDIAVIX:  13.5,
  GOLD:     72000,
  SILVER:   90000,
  CRUDEOIL:  6400,
  NATURALGAS: 250,
  RELIANCE:  2850,
  TCS:       3720,
  HDFCBANK:  1680,
  INFY:      1520,
  ICICIBANK: 1290,
  SBIN:       780,
  ITC:        440,
};

// Exchange mapping per symbol
const EXCHANGES: Record<string, string> = {
  NIFTY:    "NSE_INDEX",
  BANKNIFTY: "NSE_INDEX",
  SENSEX:   "BSE_INDEX",
  INDIAVIX: "NSE_INDEX",
  GOLD:     "MCX",
  SILVER:   "MCX",
  CRUDEOIL: "MCX",
  NATURALGAS: "MCX",
  RELIANCE:  "NSE",
  TCS:       "NSE",
  HDFCBANK:  "NSE",
  INFY:      "NSE",
  ICICIBANK: "NSE",
  SBIN:      "NSE",
  ITC:       "NSE",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Box-Muller transform — normally distributed noise with mean 0, std 1.
 */
function gaussianNoise(): number {
  let u = 0;
  let v = 0;
  // Avoid exact 0 in Math.log
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
}

/** Clamp `value` within [min, max]. */
function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/** Round to 2 decimal places (standard price precision). */
function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Generate a simple numeric order id string. */
function fakeOrderId(index: number): string {
  return `OA${Date.now().toString().slice(-8)}${String(index).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// MockDataEngine
// ---------------------------------------------------------------------------

export class MockDataEngine {
  private prices: Map<string, number>;
  private volumes: Map<string, number>;
  private opens: Map<string, number>;
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private listeners: Set<(ticks: MockTick[]) => void> = new Set();

  constructor() {
    this.prices = new Map(Object.entries(BASE_PRICES));
    // Starting open prices equal base prices
    this.opens = new Map(Object.entries(BASE_PRICES));
    // Seed volumes in a realistic range per instrument
    this.volumes = new Map(
      Object.keys(BASE_PRICES).map((sym) => [sym, Math.floor(Math.random() * 500_000) + 100_000])
    );
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /** Start generating ticks every `intervalMs` milliseconds (default 1 000 ms). */
  start(intervalMs = 1000): void {
    if (this.intervalId !== null) return; // already running
    this.intervalId = setInterval(() => {
      this._step();
      const snapshot = this.getSnapshot();
      this.listeners.forEach((cb) => cb(snapshot));
    }, intervalMs);
  }

  /** Stop generating ticks and clear the interval. */
  stop(): void {
    if (this.intervalId !== null) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  /** Returns true when the engine is currently running. */
  get isRunning(): boolean {
    return this.intervalId !== null;
  }

  // ---------------------------------------------------------------------------
  // Subscriptions
  // ---------------------------------------------------------------------------

  /**
   * Subscribe to tick updates.
   * @returns Unsubscribe function.
   */
  onTick(cb: (ticks: MockTick[]) => void): () => void {
    this.listeners.add(cb);
    return () => {
      this.listeners.delete(cb);
    };
  }

  // ---------------------------------------------------------------------------
  // Data
  // ---------------------------------------------------------------------------

  /** Get current price snapshot for all instruments. */
  getSnapshot(): MockTick[] {
    const ticks: MockTick[] = [];
    for (const [symbol, ltp] of this.prices) {
      const base = BASE_PRICES[symbol] ?? ltp;
      const open = this.opens.get(symbol) ?? base;
      const change = round2(ltp - open);
      const changePct = round2((change / open) * 100);
      const vol = this.volumes.get(symbol) ?? 0;
      // Derive high/low lazily from base ±3%
      const high = round2(Math.max(open, ltp, base * 1.015));
      const low  = round2(Math.min(open, ltp, base * 0.985));
      ticks.push({
        symbol,
        exchange: EXCHANGES[symbol] ?? "NSE",
        ltp:       round2(ltp),
        change,
        changePct,
        volume:    vol,
        open:      round2(open),
        high,
        low,
        close:     round2(open), // prev close = open for mock purposes
      });
    }
    return ticks;
  }

  /** Generate 5 mock open positions. */
  getMockPositions(): MockPosition[] {
    const symbols = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "ICICIBANK"] as const;
    return symbols.map((symbol, i) => {
      const ltp   = round2(this.prices.get(symbol) ?? BASE_PRICES[symbol]);
      const side: "BUY" | "SELL" = i % 2 === 0 ? "BUY" : "SELL";
      const qty   = (i + 1) * 25;
      const drift = (Math.random() - 0.5) * 0.02; // ±1% from current price
      const avg   = round2(ltp * (1 + drift));
      const pnl   = round2(side === "BUY" ? (ltp - avg) * qty : (avg - ltp) * qty);
      return {
        symbol,
        exchange: EXCHANGES[symbol] ?? "NSE",
        product: symbol.startsWith("NIFTY") || symbol === "BANKNIFTY" ? "MIS" : "MIS",
        quantity: qty,
        avgPrice: avg,
        ltp,
        pnl,
        side,
      };
    });
  }

  /** Generate 8 mock orders placed today. */
  getMockOrders(): MockOrder[] {
    const configs: Array<{
      symbol: string;
      side: "BUY" | "SELL";
      status: MockOrder["status"];
    }> = [
      { symbol: "NIFTY",    side: "BUY",  status: "COMPLETE"  },
      { symbol: "BANKNIFTY",side: "SELL", status: "COMPLETE"  },
      { symbol: "RELIANCE", side: "BUY",  status: "COMPLETE"  },
      { symbol: "TCS",      side: "BUY",  status: "OPEN"      },
      { symbol: "HDFCBANK", side: "SELL", status: "COMPLETE"  },
      { symbol: "INFY",     side: "BUY",  status: "CANCELLED" },
      { symbol: "ICICIBANK",side: "SELL", status: "COMPLETE"  },
      { symbol: "SBIN",     side: "BUY",  status: "REJECTED"  },
    ];

    return configs.map(({ symbol, side, status }, i) => {
      const base  = BASE_PRICES[symbol] ?? 1000;
      const price = round2(base * (1 + (Math.random() - 0.5) * 0.01));
      const qty   = (i + 1) * 10;
      const now   = new Date();
      now.setMinutes(now.getMinutes() - i * 15); // stagger by 15 min
      return {
        orderId:   fakeOrderId(i),
        symbol,
        exchange:  EXCHANGES[symbol] ?? "NSE",
        side,
        product:   "MIS",
        orderType: i % 3 === 0 ? "LIMIT" : "MARKET",
        quantity:  qty,
        price,
        status,
        timestamp: now.toISOString(),
      };
    });
  }

  /** Generate 10 mock equity holdings. */
  getMockHoldings(): MockHolding[] {
    const symbols = [
      "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
      "SBIN", "ITC", "NIFTY", "BANKNIFTY", "SENSEX",
    ] as const;

    return symbols.map((symbol) => {
      const ltp  = round2(this.prices.get(symbol) ?? BASE_PRICES[symbol]);
      const qty  = Math.floor(Math.random() * 50) + 5;
      const drift = (Math.random() - 0.5) * 0.15; // ±7.5% buy price spread
      const avg  = round2(ltp / (1 + drift));
      const cv   = round2(ltp * qty);
      const pnl  = round2((ltp - avg) * qty);
      const pnlPct = round2(((ltp - avg) / avg) * 100);
      return {
        symbol,
        exchange: EXCHANGES[symbol] ?? "NSE",
        quantity: qty,
        avgPrice: avg,
        ltp,
        currentValue: cv,
        pnl,
        pnlPct,
      };
    });
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  /** Advance prices by one random-walk step. */
  private _step(): void {
    for (const [symbol, price] of this.prices) {
      const base    = BASE_PRICES[symbol] ?? price;
      const noise   = gaussianNoise() * 0.001; // σ = 0.1% per tick
      const rawNext = price * (1 + noise);
      // Keep within ±5% of base price
      const bounded = clamp(rawNext, base * 0.95, base * 1.05);
      this.prices.set(symbol, bounded);

      // Increment volume by a small random amount
      const prevVol = this.volumes.get(symbol) ?? 0;
      this.volumes.set(symbol, prevVol + Math.floor(Math.random() * 1000) + 50);
    }
  }
}

// ---------------------------------------------------------------------------
// Singleton export — shared across the app
// ---------------------------------------------------------------------------

export const mockDataEngine = new MockDataEngine();
