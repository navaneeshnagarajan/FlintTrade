import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
//
// The widget fetches live intraday bars via `getHistory` once a broker is
// connected, and falls back to deterministic SAMPLE bars otherwise. We mock
// both the connection signal and the history fetch so we can exercise the
// live ("Live" badge) and disconnected ("Sample data" badge) paths.

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getHistory: vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getHistory } from "@/services/api";
import VWAPBandsWidget from "../VWAPBandsWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetHistory = getHistory as ReturnType<typeof vi.fn>;

/** A single IST session (2024-01-15) of 5-minute bars, epoch seconds (UTC). */
function liveSessionBars() {
  // 2024-01-15 09:15 IST == 03:45 UTC == 1705289100
  const base = 1705289100;
  return Array.from({ length: 6 }, (_, i) => {
    const close = 22500 + i * 5;
    return {
      timestamp: base + i * 300,
      open: close - 2,
      high: close + 4,
      low: close - 4,
      close,
      volume: 100_000 + i * 1000,
    };
  });
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <VWAPBandsWidget />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockConnected.mockReturnValue(false);
  mockGetHistory.mockResolvedValue([]);
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("VWAPBandsWidget", () => {
  it("renders the widget title", () => {
    renderWidget();
    expect(screen.getByText("VWAP Bands")).toBeTruthy();
  });

  it("shows the 'Sample data' badge in explore mode (disconnected)", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("does not fetch history when no broker is connected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockGetHistory).not.toHaveBeenCalled();
  });

  it("flips to a 'Live' badge once the broker returns intraday bars", async () => {
    mockConnected.mockReturnValue(true);
    mockGetHistory.mockResolvedValue(liveSessionBars());
    renderWidget();

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(mockGetHistory).toHaveBeenCalledWith("NIFTY", "NSE_INDEX", "5m", expect.any(String), expect.any(String));
  });

  it("falls back to 'Sample data' when connected but the broker returns no bars", async () => {
    mockConnected.mockReturnValue(true);
    mockGetHistory.mockResolvedValue([]);
    renderWidget();

    // Give the (resolved-empty) query a tick, then assert the honest fallback.
    await waitFor(() => expect(mockGetHistory).toHaveBeenCalled());
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("badge is an honest, screen-reader-announced status with an explanatory title", () => {
    renderWidget();
    const badge = screen.getByText("Sample data");
    expect(badge).toHaveAttribute("role", "status");
    expect(badge).toHaveAttribute(
      "aria-label",
      "Showing sample data; no live backend endpoint yet",
    );
    expect(badge.getAttribute("title")).toMatch(/no live data wired yet/i);
  });

  it("does not render a deceptive live-looking refresh affordance", () => {
    renderWidget();
    expect(screen.queryByRole("button", { name: /refresh VWAP data/i })).toBeNull();
  });

  it("renders VWAP stat labels", () => {
    renderWidget();
    expect(screen.getAllByText("VWAP").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Price").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/VWAP/i).length).toBeGreaterThan(0);
  });

  it("renders symbol selector button defaulting to NIFTY", () => {
    renderWidget();
    expect(screen.getByRole("button", { name: /selected symbol: NIFTY/i })).toBeTruthy();
  });

  it("opens symbol dropdown and shows all symbols", () => {
    renderWidget();
    fireEvent.click(screen.getByRole("button", { name: /selected symbol/i }));
    expect(screen.getByText("BANKNIFTY")).toBeTruthy();
    expect(screen.getByText("RELIANCE")).toBeTruthy();
    expect(screen.getByText("HDFCBANK")).toBeTruthy();
  });

  it("renders band legend entries", () => {
    renderWidget();
    expect(screen.getByText("± 1σ")).toBeTruthy();
    expect(screen.getByText("± 2σ")).toBeTruthy();
    expect(screen.getByText("± 3σ")).toBeTruthy();
  });

  it("renders VWAP through the shared Flint banded-line primitive", () => {
    renderWidget();
    const chart = screen.getByRole("img", { name: /vwap bands chart/i });
    expect(chart).toHaveAttribute("data-flint-chart", "banded-line");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-banded-line-band]").length).toBe(3);
    expect(chart.querySelectorAll("[data-banded-line-series]").length).toBeGreaterThanOrEqual(2);
  });

  it("renders band legend swatches without local SVG", () => {
    const { container } = renderWidget();
    expect(container.querySelector('svg[width="16"][height="8"]')).not.toBeInTheDocument();
  });
});
