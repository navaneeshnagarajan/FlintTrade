/**
 * Sample order book snapshots for OrderBookReplayWidget — explore mode.
 * Values are illustrative only. Simulates order book evolution over time.
 */

export interface DepthLevel {
  price: number;
  quantity: number;
  orders: number;
}

export interface OrderBookSnapshot {
  timestamp: string;    // ISO datetime
  buy: DepthLevel[];    // Best 5 bid levels (descending by price)
  sell: DepthLevel[];   // Best 5 ask levels (ascending by price)
}

function snap(
  minuteOffset: number,
  mid: number,
  spread: number,
  bidBias: number,  // 0=neutral, positive=more bids
): OrderBookSnapshot {
  const ts = new Date();
  ts.setMinutes(ts.getMinutes() - 60 + minuteOffset, 0, 0);

  const tick = 0.05;
  const buy: DepthLevel[] = [];
  const sell: DepthLevel[] = [];

  for (let i = 0; i < 5; i++) {
    const bidPrice = mid - spread / 2 - i * tick;
    const askPrice = mid + spread / 2 + i * tick;
    const base = 200 + Math.round(Math.random() * 800);
    buy.push({
      price: Math.round(bidPrice * 20) / 20,
      quantity: Math.max(10, base + Math.round(bidBias * 100)),
      orders: 1 + Math.round(Math.random() * 8),
    });
    sell.push({
      price: Math.round(askPrice * 20) / 20,
      quantity: Math.max(10, base - Math.round(bidBias * 50)),
      orders: 1 + Math.round(Math.random() * 6),
    });
  }

  return { timestamp: ts.toISOString(), buy, sell };
}

export const SAMPLE_SNAPSHOTS: OrderBookSnapshot[] = Array.from({ length: 60 }, (_, i) => {
  const phase = i / 59;
  const mid = 22450 + phase * 80;            // price drifts up
  const spread = 0.1 + (phase < 0.3 ? 0.15 : phase > 0.7 ? 0.05 : 0.10);
  const bias = Math.sin(phase * Math.PI * 3); // oscillating bid/ask imbalance
  return snap(i, mid, spread, bias);
});
