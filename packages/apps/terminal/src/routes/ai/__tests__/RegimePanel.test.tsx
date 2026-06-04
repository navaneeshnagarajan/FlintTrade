/**
 * RegimePanel.test.tsx
 *
 * Tests for the Regime Detector Display panel.
 * Covers: loading state, error state, regime badge, tradeable indicator,
 * indicator stats, +DI/-DI bar, symbol selector, quick-symbol buttons.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { RegimeResult } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Mocks — hoisted before component import
// ---------------------------------------------------------------------------

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    stagger: (i: number) => ({ delay: i * 0.05 }),
    transitions: { tab: { duration: 0.2 } },
  },
}));

const mockGetRegimeDetector = vi.fn();

vi.mock("@/services/ftApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi")>();
  return {
    ...actual,
    getRegimeDetector: (symbol: string) => mockGetRegimeDetector(symbol),
  };
});

// Static import must come AFTER vi.mock() calls
import RegimePanel from "../RegimePanel";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const TRENDING_UP_RESULT: RegimeResult = {
  state: "TRENDING_UP",
  adx: 32.5,
  bb_width: 0.035,
  atr_current: 145.2,
  atr_slope: -0.3,
  plus_di: 28.4,
  minus_di: 14.2,
  close: 24350.5,
  n_bars: 200,
};

const VOLATILE_DIRECTIONLESS_RESULT: RegimeResult = {
  state: "VOLATILE_DIRECTIONLESS",
  adx: 18.1,
  bb_width: 0.062,
  atr_current: 220.8,
  atr_slope: 1.2,
  plus_di: 18.0,
  minus_di: 19.5,
  close: 51800.0,
  n_bars: 150,
};

const LOW_VOLATILITY_RESULT: RegimeResult = {
  state: "LOW_VOLATILITY",
  adx: 12.0,
  bb_width: 0.015,
  atr_current: 60.0,
  atr_slope: -0.8,
  plus_di: 15.0,
  minus_di: 14.0,
  close: 24100.0,
  n_bars: 180,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPanel() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <RegimePanel />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RegimePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the panel title", () => {
    mockGetRegimeDetector.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByText("Regime Detector")).toBeInTheDocument();
  });

  it("shows loading state while fetching", () => {
    mockGetRegimeDetector.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(
      screen.getByText(/Detecting regime for NIFTY/i),
    ).toBeInTheDocument();
  });

  it("renders TRENDING_UP badge on success", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Trending Up")).toBeInTheDocument();
    });
  });

  it("shows Tradeable indicator for TRENDING_UP", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Tradeable")).toBeInTheDocument();
    });
  });

  it("shows Avoid Directional for VOLATILE_DIRECTIONLESS", async () => {
    mockGetRegimeDetector.mockResolvedValue(VOLATILE_DIRECTIONLESS_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Volatile Directionless")).toBeInTheDocument();
      expect(screen.getByText("Avoid Directional")).toBeInTheDocument();
    });
  });

  it("shows Avoid Directional for LOW_VOLATILITY", async () => {
    mockGetRegimeDetector.mockResolvedValue(LOW_VOLATILITY_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Low Volatility")).toBeInTheDocument();
      expect(screen.getByText("Avoid Directional")).toBeInTheDocument();
    });
  });

  it("renders ADX value and interpretation", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("ADX")).toBeInTheDocument();
      expect(screen.getByText("32.5")).toBeInTheDocument();
      expect(screen.getByText("Strong trend")).toBeInTheDocument();
    });
  });

  it("renders BB Width value", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("BB Width")).toBeInTheDocument();
      expect(screen.getByText("3.50%")).toBeInTheDocument();
    });
  });

  it("renders ATR current value", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("ATR")).toBeInTheDocument();
      expect(screen.getByText("145.20")).toBeInTheDocument();
    });
  });

  it("renders +DI / -DI comparison bar heading", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Directional Pressure")).toBeInTheDocument();
    });
  });

  it("renders +DI and -DI values", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/\+DI 28\.4/)).toBeInTheDocument();
      expect(screen.getByText(/-DI 14\.2/)).toBeInTheDocument();
    });
  });

  it("shows an honest 'coming soon' state on API failure", async () => {
    // The endpoint fails closed (e.g. 404 / no historical data); the panel
    // degrades to a calm preview placeholder, not a raw backend error.
    mockGetRegimeDetector.mockRejectedValue(new Error("Not enough bars"));
    renderPanel();
    await waitFor(() => {
      expect(
        screen.getByText("Regime detection coming soon"),
      ).toBeInTheDocument();
    });
    // Raw backend error message must not leak into the UI.
    expect(screen.queryByText("Not enough bars")).not.toBeInTheDocument();
  });

  it("clicking a quick symbol updates the query symbol", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();

    // Wait for first render to settle
    await waitFor(() => screen.getAllByText("BANKNIFTY"));

    // Click the BANKNIFTY quick button
    const bankniftyBtn = screen
      .getAllByText("BANKNIFTY")
      .find((el) => el.tagName === "BUTTON");
    if (!bankniftyBtn) throw new Error("BANKNIFTY button not found");
    fireEvent.click(bankniftyBtn);

    await waitFor(() => {
      expect(mockGetRegimeDetector).toHaveBeenCalledWith("BANKNIFTY");
    });
  });

  it("search button changes active symbol and triggers new query", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();

    // Wait for initial NIFTY fetch to complete
    await waitFor(() => screen.getByText("Trending Up"));

    const input = screen.getByPlaceholderText("e.g. NIFTY");
    fireEvent.change(input, { target: { value: "RELIANCE" } });
    fireEvent.click(
      screen.getByRole("button", { name: /Search regime for symbol/i }),
    );

    // Symbol state updates — mock should receive RELIANCE
    await waitFor(() => {
      const calls = mockGetRegimeDetector.mock.calls.map((c) => c[0]);
      expect(calls).toContain("RELIANCE");
    });
  });

  it("Enter key in input triggers search with new symbol", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();

    // Wait for initial NIFTY fetch to complete
    await waitFor(() => screen.getByText("Trending Up"));

    const input = screen.getByPlaceholderText("e.g. NIFTY");
    fireEvent.change(input, { target: { value: "HDFC" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      const calls = mockGetRegimeDetector.mock.calls.map((c) => c[0]);
      expect(calls).toContain("HDFC");
    });
  });

  it("renders n_bars count in result footer", async () => {
    mockGetRegimeDetector.mockResolvedValue(TRENDING_UP_RESULT);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("200 bars")).toBeInTheDocument();
    });
  });

  it("renders all quick symbol buttons", () => {
    mockGetRegimeDetector.mockReturnValue(new Promise(() => {}));
    renderPanel();
    ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"].forEach(
      (sym) => {
        expect(
          screen
            .getAllByText(sym)
            .some((el) => el.tagName === "BUTTON" || el.closest("button")),
        ).toBe(true);
      },
    );
  });

  it("'Check again' button triggers refetch after the coming-soon state", async () => {
    mockGetRegimeDetector
      .mockRejectedValueOnce(new Error("fail"))
      .mockResolvedValueOnce(TRENDING_UP_RESULT);

    renderPanel();
    await waitFor(() => screen.getByText("Regime detection coming soon"));

    fireEvent.click(screen.getByText("Check again"));
    await waitFor(() => {
      expect(mockGetRegimeDetector).toHaveBeenCalledTimes(2);
    });
  });
});
