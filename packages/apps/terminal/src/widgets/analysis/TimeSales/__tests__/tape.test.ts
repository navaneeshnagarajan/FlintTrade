import { describe, it, expect } from "vitest";
import {
  computeTapeStats,
  foldTick,
  initialTapeState,
  pushPrint,
  VELOCITY_BUCKETS,
  type TapePrint,
  type TapeSide,
} from "../tape";

const NOW = new Date("2026-07-06T10:42:00");

describe("tape foldTick", () => {
  it("first tick prints neutral with no volume delta", () => {
    const { print, state } = foldTick(initialTapeState(), { ltp: 100, volume: 1000 }, NOW);
    expect(print).not.toBeNull();
    expect(print?.side).toBe("neutral");
    expect(print?.qty).toBe(0); // no prior cumulative volume to delta against
    expect(state.lastPrice).toBe(100);
    expect(state.lastVolume).toBe(1000);
  });

  it("uptick infers buy with the volume delta", () => {
    let s = initialTapeState();
    ({ state: s } = foldTick(s, { ltp: 100, volume: 1000 }, NOW));
    const { print } = foldTick(s, { ltp: 100.5, volume: 1250 }, NOW);
    expect(print?.side).toBe("buy");
    expect(print?.qty).toBe(250);
  });

  it("downtick infers sell", () => {
    let s = initialTapeState();
    ({ state: s } = foldTick(s, { ltp: 100, volume: 1000 }, NOW));
    const { print } = foldTick(s, { ltp: 99.5, volume: 1100 }, NOW);
    expect(print?.side).toBe("sell");
    expect(print?.qty).toBe(100);
  });

  it("flat price with volume carries the previous side (tick rule)", () => {
    let s = initialTapeState();
    ({ state: s } = foldTick(s, { ltp: 100, volume: 1000 }, NOW));
    ({ state: s } = foldTick(s, { ltp: 100.5, volume: 1200 }, NOW)); // buy
    const { print } = foldTick(s, { ltp: 100.5, volume: 1300 }, NOW);
    expect(print?.side).toBe("buy");
    expect(print?.qty).toBe(100);
  });

  it("no price move and no volume → no print", () => {
    let s = initialTapeState();
    ({ state: s } = foldTick(s, { ltp: 100, volume: 1000 }, NOW));
    const { print } = foldTick(s, { ltp: 100, volume: 1000 }, NOW);
    expect(print).toBeNull();
  });

  it("volume decreasing (feed reset) clamps delta to zero, never negative", () => {
    let s = initialTapeState();
    ({ state: s } = foldTick(s, { ltp: 100, volume: 5000 }, NOW));
    const { print } = foldTick(s, { ltp: 100.5, volume: 100 }, NOW);
    expect(print?.qty).toBe(0);
  });

  it("invalid price is ignored", () => {
    const { print } = foldTick(initialTapeState(), { ltp: 0 }, NOW);
    expect(print).toBeNull();
  });

  it("stamps the print with the epoch clock the statistics window uses", () => {
    const { print } = foldTick(initialTapeState(), { ltp: 100, volume: 1000 }, NOW);
    expect(print?.ts).toBe(NOW.getTime());
    expect(print?.time).toBe(NOW.toTimeString().slice(0, 8));
  });
});

describe("pushPrint", () => {
  it("prepends newest-first and caps the tape", () => {
    let tape: TapePrint[] = [];
    for (let i = 1; i <= 205; i++) {
      tape = pushPrint(tape, { id: i, ts: i, time: "10:00:00", price: 100, qty: 1, side: "buy" });
    }
    expect(tape).toHaveLength(200);
    expect(tape[0].id).toBe(205); // newest first
    expect(tape[199].id).toBe(6); // oldest retained
  });
});

// ---------------------------------------------------------------------------
// computeTapeStats — the retired Market Microstructure widget's kernel, now
// fed by real prints instead of `Math.random()`.
// ---------------------------------------------------------------------------

const T0 = new Date("2026-07-06T10:42:00").getTime();

/** Build a print `agoMs` before T0. */
function printAt(agoMs: number, qty: number, side: TapeSide, id = agoMs): TapePrint {
  return { id, ts: T0 - agoMs, time: "10:42:00", price: 100, qty, side };
}

describe("computeTapeStats", () => {
  it("an empty tape is all zeros with a full-width empty sparkline", () => {
    const stats = computeTapeStats([], T0);
    expect(stats).toEqual({
      velocity: 0,
      velocityHistory: new Array(VELOCITY_BUCKETS).fill(0),
      uptickPct: 0,
      downtickPct: 0,
      avgTradeSize: 0,
      largeOrderCount: 0,
      sizedCount: 0,
      printCount: 0,
    });
  });

  it("velocity is prints in the last 10 s divided by 10", () => {
    // 8 prints inside 10 s, 4 older (inside the 60 s window but outside 10 s).
    const prints = [
      ...Array.from({ length: 8 }, (_, i) => printAt(i * 1_000, 10, "buy", i)),
      ...Array.from({ length: 4 }, (_, i) => printAt(20_000 + i * 1_000, 10, "buy", 100 + i)),
    ];
    const stats = computeTapeStats(prints, T0);
    expect(stats.velocity).toBe(0.8);
    expect(stats.printCount).toBe(12);
  });

  it("prints older than the 60 s window are excluded entirely", () => {
    const stats = computeTapeStats(
      [printAt(1_000, 100, "buy", 1), printAt(59_999, 100, "buy", 2), printAt(60_000, 999, "sell", 3)],
      T0,
    );
    expect(stats.printCount).toBe(2);
    expect(stats.uptickPct).toBe(100);
    expect(stats.downtickPct).toBe(0);
    expect(stats.avgTradeSize).toBe(100); // the 999 print is outside the window
  });

  it("uptick/downtick percentages are the tick-rule aggressor split", () => {
    const prints = [
      printAt(1_000, 10, "buy", 1),
      printAt(2_000, 10, "buy", 2),
      printAt(3_000, 10, "buy", 3),
      printAt(4_000, 10, "sell", 4),
      printAt(5_000, 10, "neutral", 5),
    ];
    const stats = computeTapeStats(prints, T0);
    expect(stats.printCount).toBe(5);
    expect(stats.uptickPct).toBe(60);
    expect(stats.downtickPct).toBe(20);
    // The remaining 20% is the neutral carry-forward side.
    expect(100 - stats.uptickPct - stats.downtickPct).toBe(20);
  });

  it("average trade size ignores prints the feed gave no size for", () => {
    // A zero volume delta means "size unknown", not "a zero-sized trade";
    // averaging it in would report a fictitiously small trade size.
    const prints = [
      printAt(1_000, 100, "buy", 1),
      printAt(2_000, 300, "sell", 2),
      printAt(3_000, 0, "buy", 3),
      printAt(4_000, 0, "sell", 4),
    ];
    const stats = computeTapeStats(prints, T0);
    expect(stats.printCount).toBe(4);
    expect(stats.sizedCount).toBe(2);
    expect(stats.avgTradeSize).toBe(200); // (100 + 300) / 2, not / 4
  });

  it("an LTP-only feed reports no sizes rather than an average of zero", () => {
    const prints = [printAt(1_000, 0, "buy", 1), printAt(2_000, 0, "sell", 2)];
    const stats = computeTapeStats(prints, T0);
    expect(stats.printCount).toBe(2);
    expect(stats.sizedCount).toBe(0);
    expect(stats.avgTradeSize).toBe(0);
    expect(stats.largeOrderCount).toBe(0);
  });

  it("large prints are strictly larger than twice the average size", () => {
    // Sizes 100, 100, 100, 500 → avg 200, threshold 400 → only the 500 counts.
    const prints = [
      printAt(1_000, 100, "buy", 1),
      printAt(2_000, 100, "buy", 2),
      printAt(3_000, 100, "sell", 3),
      printAt(4_000, 500, "buy", 4),
    ];
    const stats = computeTapeStats(prints, T0);
    expect(stats.avgTradeSize).toBe(200);
    expect(stats.largeOrderCount).toBe(1);
  });

  it("exactly twice the average is not a large print", () => {
    // Sizes 100, 100, 400 → avg 200, threshold 400; the 400 print sits exactly
    // on the threshold and must not count (the test is the strict `>`).
    const stats = computeTapeStats(
      [printAt(1_000, 100, "buy", 1), printAt(2_000, 100, "buy", 2), printAt(3_000, 400, "buy", 3)],
      T0,
    );
    expect(stats.avgTradeSize).toBe(200);
    expect(stats.largeOrderCount).toBe(0);
  });

  it("the sparkline buckets prints by second, newest at the last bucket", () => {
    const prints = [
      printAt(0, 10, "buy", 1),
      printAt(500, 10, "buy", 2),      // same 0–1 s bucket
      printAt(1_500, 10, "buy", 3),    // one second back
      printAt(59_500, 10, "buy", 4),   // oldest bucket still inside the window
    ];
    const stats = computeTapeStats(prints, T0);
    expect(stats.velocityHistory).toHaveLength(VELOCITY_BUCKETS);
    expect(stats.velocityHistory[59]).toBe(2);
    expect(stats.velocityHistory[58]).toBe(1);
    expect(stats.velocityHistory[0]).toBe(1);
    expect(stats.velocityHistory.reduce((a, b) => a + b, 0)).toBe(4);
  });

  it("a print stamped in the future lands in the newest bucket, not dropped", () => {
    // Clock skew between the tick arriving and the stats being computed.
    const stats = computeTapeStats([printAt(-250, 50, "buy", 1)], T0);
    expect(stats.printCount).toBe(1);
    expect(stats.velocityHistory[59]).toBe(1);
    expect(stats.velocity).toBe(0.1);
  });

  it("carries no bid/ask imbalance — the tape cannot source one", () => {
    // The retired widget fabricated bid/ask sizes because the quote feed has
    // none. Imbalance must come from the depth book, so it is deliberately
    // absent from the tape kernel's output.
    const stats = computeTapeStats([printAt(1_000, 100, "buy", 1)], T0);
    expect(stats).not.toHaveProperty("imbalance");
  });
});
