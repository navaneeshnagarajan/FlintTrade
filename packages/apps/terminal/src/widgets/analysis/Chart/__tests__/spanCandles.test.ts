import { describe, expect, it, vi } from "vitest";
import { applyCandleSpan, candleSpanOptions, seriesOccupiesPlot } from "../spanCandles";

describe("candle span", () => {
  it("stretches a short series across a 2560-class plot", () => {
    const options = candleSpanOptions(1700, 96, { from: -140, to: 104 });
    expect(options).not.toBeNull();
    expect(options?.barSpacing).toBeCloseTo(1700 / 98, 5);
    expect(options?.rightOffset).toBe(2);
    expect(options?.maxBarSpacing).toBeGreaterThanOrEqual(options?.barSpacing ?? 0);
  });

  it("leaves a zoomed-in range that is already all candles", () => {
    expect(candleSpanOptions(1700, 96, { from: 40, to: 70 })).toBeNull();
  });

  it("waits until the plot has a real width", () => {
    expect(candleSpanOptions(0, 96, null)).toBeNull();
    expect(candleSpanOptions(20, 96, null)).toBeNull();
  });

  it("treats the 40% desk as unfilled and a fitted range as filled", () => {
    expect(seriesOccupiesPlot(-140, 104, 96)).toBe(false);
    expect(seriesOccupiesPlot(0, 98, 96)).toBe(true);
  });

  it("applies the span through the time scale", () => {
    const applyOptions = vi.fn();
    applyCandleSpan({
      width: () => 1700,
      getVisibleLogicalRange: () => ({ from: -140, to: 104 }),
      applyOptions,
    }, 96);
    expect(applyOptions).toHaveBeenCalledWith(expect.objectContaining({
      barSpacing: expect.closeTo(1700 / 98, 5),
      rightOffset: 2,
    }));
  });

  it("does nothing when the time scale cannot report a width", () => {
    const applyOptions = vi.fn();
    applyCandleSpan({ applyOptions }, 96);
    expect(applyOptions).not.toHaveBeenCalled();
  });
});
