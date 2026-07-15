/**
 * GlobalIndicesWidget.test.tsx
 *
 * Tests: render, regions, table headers, sample data, loading state, and the
 * honest live-mode behaviour — a connected (live) user must never see
 * fabricated sample rows, even when the live response is empty.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import "@testing-library/jest-dom";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/services/ftApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi")>();
  return { ...actual, getGlobalIndices: vi.fn() };
});

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getGlobalIndices } from "@/services/ftApi";
import type { GlobalIndexEntry } from "@/services/ftApi";
import GlobalIndicesWidget from "../GlobalIndicesWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockIndices = getGlobalIndices as ReturnType<typeof vi.fn>;

function renderWidget(ui: ReactElement = <GlobalIndicesWidget />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  mockConnected.mockReturnValue(false);
  mockIndices.mockReset();
  mockIndices.mockResolvedValue({
    indices: [],
    updated_at: new Date().toISOString(),
    is_sample_data: false,
  });
});

describe("GlobalIndicesWidget", () => {
  it("renders the widget header", () => {
    renderWidget();
    expect(screen.getByText("Global Indices")).toBeTruthy();
  });

  it("renders table column headers", () => {
    renderWidget();
    expect(screen.getByText("Index")).toBeTruthy();
    expect(screen.getByText("LTP")).toBeTruthy();
    expect(screen.getByText("Chg")).toBeTruthy();
    expect(screen.getByText("Trend")).toBeTruthy();
  });

  it("renders region group headers from sample data", () => {
    renderWidget();
    expect(screen.getByText("India")).toBeTruthy();
    expect(screen.getByText("US")).toBeTruthy();
    expect(screen.getByText("Europe")).toBeTruthy();
    expect(screen.getByText("Asia")).toBeTruthy();
  });

  it("renders sample index names", () => {
    renderWidget();
    expect(screen.getByText("NIFTY 50")).toBeTruthy();
    expect(screen.getByText("S&P 500")).toBeTruthy();
    expect(screen.getByText("FTSE 100")).toBeTruthy();
    expect(screen.getByText("Nikkei 225")).toBeTruthy();
  });

  it("shows sample data label when disconnected", () => {
    renderWidget();
    expect(screen.getByText("(sample data)")).toBeTruthy();
    expect(screen.queryByText(/Updated:/)).toBeNull();
  });

  it("does not export a module-load freshness timestamp", async () => {
    const sampleData = await import("../sampleData");
    expect("SAMPLE_UPDATED_AT" in sampleData).toBe(false);
  });

  it("renders sparklines for each index row", () => {
    renderWidget();
    const sparklines = screen.getAllByRole("img", { name: /30-day index sparkline/i });
    expect(sparklines.length).toBeGreaterThanOrEqual(10);
    expect(sparklines[0]).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparklines[0].querySelector("polyline")).not.toBeInTheDocument();
    expect(sparklines[0].querySelectorAll("path").length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Honest live-mode behaviour — no fabricated rows for connected users.
// ---------------------------------------------------------------------------

describe("GlobalIndicesWidget (connected)", () => {
  const LIVE_INDICES: GlobalIndexEntry[] = [
    {
      id: "NIFTY50",
      name: "NIFTY 50",
      region: "India",
      ltp: 22_500.5,
      change: 50.2,
      change_pct: 0.22,
      history: [22_400, 22_450, 22_500],
    },
  ];

  it("queries the live endpoint only when connected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockIndices).not.toHaveBeenCalled();
  });

  it("shows the honest empty state — and no sample rows — when the live response is empty", async () => {
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({
      indices: [],
      updated_at: new Date().toISOString(),
      is_sample_data: false,
    });
    renderWidget();

    // Honest empty state is shown.
    expect(await screen.findByText("No global indices available")).toBeTruthy();
    // Fabricated sample rows must NOT appear for a connected user.
    expect(screen.queryByText("NIFTY 50")).toBeNull();
    expect(screen.queryByText("S&P 500")).toBeNull();
    // An explicitly live empty response has no sample-data affordance.
    expect(screen.queryByText("(sample data)")).toBeNull();
    expect(screen.queryByText(/Could not load global indices/i)).toBeNull();
  });

  it("renders live indices and no sample affordance when connected with data", async () => {
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({
      indices: LIVE_INDICES,
      updated_at: new Date().toISOString(),
      is_sample_data: false,
    });
    renderWidget();

    expect(await screen.findByText("NIFTY 50")).toBeTruthy();
    expect(screen.queryByText("(sample data)")).toBeNull();
    expect(screen.queryByText("Sample data")).toBeNull();
    expect(screen.getByLabelText("Refresh global indices")).toBeTruthy();
    // A sample-only index must NOT appear alongside the single live row.
    expect(screen.queryByText("S&P 500")).toBeNull();
  });

  it("badges a connected response flagged is_sample_data — stub prices must never render as live", async () => {
    // The backend endpoint is currently a hardcoded stub that declares
    // is_sample_data: true and omits updated_at. A connected user must
    // still see the sample affordance and no invented freshness timestamp.
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({ indices: LIVE_INDICES, is_sample_data: true });
    renderWidget();

    expect(await screen.findByText("NIFTY 50")).toBeTruthy();
    // Header badge + footer note both visible despite the connection.
    expect(screen.getByText("Sample data")).toBeTruthy();
    expect(screen.getByText("(sample data)")).toBeTruthy();
    // No fabricated "Updated: …" freshness claim when the payload has no
    // honest timestamp.
    expect(screen.queryByText(/Updated:/)).toBeNull();
    expect(screen.queryByLabelText("Refresh global indices")).toBeNull();
  });

  it("treats missing connected provenance as sample or unknown", async () => {
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({
      indices: LIVE_INDICES,
      updated_at: "2026-07-14T09:30:00.000Z",
    });
    renderWidget();

    expect(await screen.findByText("NIFTY 50")).toBeTruthy();
    expect(screen.getByText("Sample data")).toBeTruthy();
    expect(screen.getByText("(sample data)")).toBeTruthy();
    expect(screen.queryByLabelText("Refresh global indices")).toBeNull();
    expect(screen.queryByText(/Updated:/)).toBeNull();
  });

  it("distinguishes request failure from an empty response and retries honestly", async () => {
    mockConnected.mockReturnValue(true);

    let resolveRetry: ((value: { indices: GlobalIndexEntry[]; is_sample_data: false }) => void) | undefined;
    mockIndices
      .mockRejectedValueOnce(new Error("Indices API unavailable"))
      .mockImplementationOnce(
        () => new Promise((resolve) => {
          resolveRetry = resolve;
        }),
      );

    renderWidget();

    expect(await screen.findByText("Indices API unavailable")).toBeTruthy();
    expect(screen.queryByText("No global indices available")).toBeNull();

    const retry = screen.getByRole("button", { name: "Retry global indices" });
    fireEvent.click(retry);
    expect(await screen.findByText("Retrying global indices...")).toBeTruthy();

    await act(async () => {
      resolveRetry?.({ indices: [], is_sample_data: false });
    });

    expect(await screen.findByText("No global indices available")).toBeTruthy();
    expect(screen.queryByText("Indices API unavailable")).toBeNull();
  });

  it("stops automatic polling after a response with missing provenance", async () => {
    vi.useFakeTimers();
    mockConnected.mockReturnValue(true);

    let resolveRequest: ((value: { indices: GlobalIndexEntry[] }) => void) | undefined;
    mockIndices.mockImplementation(
      () => new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(
      <QueryClientProvider client={qc}>
        <GlobalIndicesWidget />
      </QueryClientProvider>,
    );

    try {
      expect(mockIndices).toHaveBeenCalledTimes(1);
      await act(async () => {
        resolveRequest?.({ indices: LIVE_INDICES });
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText("NIFTY 50")).toBeTruthy();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(mockIndices).toHaveBeenCalledTimes(1);
    } finally {
      view.unmount();
      qc.clear();
      vi.useRealTimers();
    }
  });
});
