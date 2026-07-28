/**
 * useServerIndicators.test.tsx — the server-tier indicator data hook:
 * request-name building, fetch gating, bar mapping, and the
 * stale-response guard.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { FLINT_CHART_DEFAULT_INDICATORS, FLINT_CHART_DEFAULT_PERIODS } from "@flinttrade/design-system";
import type { FlintChartOhlcvBar } from "@flinttrade/design-system";

const mockComputeIndicators = vi.hoisted(() => vi.fn());
vi.mock("@/services/ftApi.analysis", () => ({
  computeIndicators: mockComputeIndicators,
}));

import { serverIndicatorName, useServerIndicators } from "../useServerIndicators";

const BARS: FlintChartOhlcvBar[] = [
  { timestamp: 1000, open: 1, high: 2, low: 0.5, close: 1.5, volume: 100 },
  { timestamp: 1060, open: 1.5, high: 2.5, low: 1, close: 2, volume: 150 },
];

const STABLE_BARS_REF = { current: BARS };

function options(overrides: Partial<Record<string, boolean>> = {}) {
  return {
    barsRef: STABLE_BARS_REF,
    indicators: { ...FLINT_CHART_DEFAULT_INDICATORS, ...overrides },
    periods: { ...FLINT_CHART_DEFAULT_PERIODS },
  };
}

describe("serverIndicatorName", () => {
  it("builds period-suffixed names from the current periods", () => {
    const periods = { ...FLINT_CHART_DEFAULT_PERIODS, kama: 21, mfi: 7 };
    expect(serverIndicatorName("showKAMA", periods)).toBe("kama_21");
    expect(serverIndicatorName("showMFI", periods)).toBe("mfi_7");
    expect(serverIndicatorName("showDonchian", periods)).toBe("donchian_channels_20");
  });

  it("uses exact names for fixed-parameter indicators", () => {
    expect(serverIndicatorName("showSqueeze", FLINT_CHART_DEFAULT_PERIODS)).toBe("squeeze_momentum");
    expect(serverIndicatorName("showAO", FLINT_CHART_DEFAULT_PERIODS)).toBe("awesome_oscillator");
  });
});

describe("useServerIndicators", () => {
  beforeEach(() => {
    mockComputeIndicators.mockReset().mockResolvedValue({});
  });

  it("does not fetch when no server-tier indicator is enabled", () => {
    renderHook(() => useServerIndicators(options()));
    expect(mockComputeIndicators).not.toHaveBeenCalled();
  });

  it("fetches the enabled indicators with bars mapped to the route shape", async () => {
    mockComputeIndicators.mockResolvedValue({ kama_10: [null, 1.7] });
    const { result } = renderHook(() => useServerIndicators(options({ showKAMA: true })));

    await waitFor(() => expect(result.current.serverData).toEqual({ kama_10: [null, 1.7] }));
    expect(mockComputeIndicators).toHaveBeenCalledWith(
      [
        { time: 1000, open: 1, high: 2, low: 0.5, close: 1.5, volume: 100 },
        { time: 1060, open: 1.5, high: 2.5, low: 1, close: 2, volume: 150 },
      ],
      ["kama_10"],
    );
  });

  it("a stale response never overwrites a newer one", async () => {
    let resolveFirst: (v: Record<string, unknown>) => void = () => {};
    mockComputeIndicators
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce({ kama_10: [2, 2] });
    const { result } = renderHook(() => useServerIndicators(options({ showKAMA: true })));

    // Second request supersedes the still-pending first one.
    act(() => result.current.refreshServerIndicators());
    await waitFor(() => expect(result.current.serverData).toEqual({ kama_10: [2, 2] }));

    // The first (stale) response lands late and must be discarded.
    await act(async () => { resolveFirst({ kama_10: [9, 9] }); });
    expect(result.current.serverData).toEqual({ kama_10: [2, 2] });
  });

  it("keeps the last data when the backend errors", async () => {
    mockComputeIndicators.mockResolvedValueOnce({ mfi_14: [50, 55] });
    const { result, rerender } = renderHook(
      (props: ReturnType<typeof options>) => useServerIndicators(props),
      { initialProps: options({ showMFI: true }) },
    );
    await waitFor(() => expect(result.current.serverData).toEqual({ mfi_14: [50, 55] }));

    mockComputeIndicators.mockRejectedValueOnce(new Error("backend down"));
    rerender(options({ showMFI: true, showAO: true }));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.serverData).toEqual({ mfi_14: [50, 55] });
  });
});
