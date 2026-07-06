import { describe, it, expect } from "vitest";
import { foldTick, initialTapeState, pushPrint, type TapePrint } from "../tape";

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
});

describe("pushPrint", () => {
  it("prepends newest-first and caps the tape", () => {
    let tape: TapePrint[] = [];
    for (let i = 1; i <= 205; i++) {
      tape = pushPrint(tape, { id: i, time: "10:00:00", price: 100, qty: 1, side: "buy" });
    }
    expect(tape).toHaveLength(200);
    expect(tape[0].id).toBe(205); // newest first
    expect(tape[199].id).toBe(6); // oldest retained
  });
});
