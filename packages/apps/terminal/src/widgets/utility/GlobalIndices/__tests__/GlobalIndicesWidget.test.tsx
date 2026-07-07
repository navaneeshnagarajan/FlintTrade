/**
 * GlobalIndicesWidget.test.tsx
 *
 * Tests: render, regions, table headers, sample data, loading state, and the
 * honest live-mode behaviour — a connected (live) user must never see
 * fabricated sample rows, even when the live response is empty.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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
  mockIndices.mockResolvedValue({ indices: [], updated_at: new Date().toISOString() });
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
    mockIndices.mockResolvedValue({ indices: [], updated_at: new Date().toISOString() });
    renderWidget();

    // Honest empty state is shown.
    expect(await screen.findByText("No global indices available")).toBeTruthy();
    // Fabricated sample rows must NOT appear for a connected user.
    expect(screen.queryByText("NIFTY 50")).toBeNull();
    expect(screen.queryByText("S&P 500")).toBeNull();
    // No sample-data affordance is rendered when connected.
    expect(screen.queryByText("(sample data)")).toBeNull();
  });

  it("renders live indices and no sample affordance when connected with data", async () => {
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({
      indices: LIVE_INDICES,
      updated_at: new Date().toISOString(),
    });
    renderWidget();

    expect(await screen.findByText("NIFTY 50")).toBeTruthy();
    expect(screen.queryByText("(sample data)")).toBeNull();
    expect(screen.queryByText("Sample data")).toBeNull();
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
  });
});
