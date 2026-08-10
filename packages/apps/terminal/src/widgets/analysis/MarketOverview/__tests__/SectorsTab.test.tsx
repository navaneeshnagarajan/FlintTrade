/**
 * SectorsTab.test — adapted from the retired SectorMap and SectorPerformance
 * suites.
 *
 * The bar view's contract CHANGED in this merge: SectorPerformance pinned a
 * never-live badge because it had no data source; the merged view now has a
 * live path through sectors/rotation, so these tests pin fail-closed
 * provenance in BOTH directions instead (badge whenever the response is not
 * explicitly live; no badge plus a timestamp only when it is).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const mockUsePositions = vi.fn();
const mockUseBrokerConnected = vi.fn();
const mockMode = vi.fn();

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockUseBrokerConnected(),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (state: { mode: string }) => unknown) =>
    selector({ mode: mockMode() as string }),
}));

vi.mock("@/services/ftApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi")>();
  return { ...actual, getSectorRotation: vi.fn() };
});

// Mock shadcn/ui components to avoid Radix rendering issues in JSDOM
vi.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  SelectValue: () => <span>Equal</span>,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode; [key: string]: unknown }) => (
    <span {...props}>{children}</span>
  ),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import { getSectorRotation } from "@/services/ftApi";
import SectorsTab from "../tabs/SectorsTab";
import { SAMPLE_SECTOR_ROTATION } from "../sampleSectors";

const mockGetSectorRotation = getSectorRotation as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function queryResult(overrides = {}) {
  return {
    data: undefined,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(),
    dataUpdatedAt: 0,
    ...overrides,
  };
}

function renderTab(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const LIVE_ROTATION = {
  sectors: [
    { symbol: "NIFTYIT", name: "IT", change_1d: 2.5, change_1w: 1.0, change_1m: 3.0, change_3m: 4.0, change_6m: 5.0, change_1y: 6.0, market_cap_cr: 980000, momentum_score: 3.0, quadrant: "leading" as const },
    { symbol: "NIFTYAUTO", name: "Auto", change_1d: -1.5, change_1w: -0.5, change_1m: 0.5, change_3m: 1.0, change_6m: 2.0, change_1y: 3.0, market_cap_cr: 540000, momentum_score: 0.5, quadrant: "improving" as const },
  ],
  updated_at: "2026-07-26 15:30 IST",
  is_sample_data: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  mockUseBrokerConnected.mockReturnValue(true);
  mockMode.mockReturnValue("explore");
  // No positions — the map views fall back to demo data
  mockUsePositions.mockReturnValue(queryResult({ data: [] }));
  mockGetSectorRotation.mockResolvedValue(LIVE_ROTATION);
});

// ---------------------------------------------------------------------------
// Map views (from SectorMap)
// ---------------------------------------------------------------------------

describe("SectorsTab map views", () => {
  it("renders without crashing", () => {
    const { container } = renderTab(<SectorsTab />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the Sectors heading", () => {
    renderTab(<SectorsTab />);
    expect(screen.getByText("Sectors")).toBeInTheDocument();
  });

  it("labels fallback sector data as sample and does not fetch positions when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    renderTab(<SectorsTab />);

    expect(mockUsePositions).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("shows view toggle buttons (Bars, Treemap, Grid, Sectors table)", () => {
    renderTab(<SectorsTab />);
    expect(screen.getByTitle("Bars")).toBeInTheDocument();
    expect(screen.getByTitle("Treemap")).toBeInTheDocument();
    expect(screen.getByTitle("Grid")).toBeInTheDocument();
    expect(screen.getByTitle("Sectors")).toBeInTheDocument();
  });

  it("shows legend footer with colour gradient", () => {
    renderTab(<SectorsTab />);
    expect(screen.getByText(/-4% → \+4%/)).toBeInTheDocument();
  });

  it("labels explore colours as day change %", () => {
    mockMode.mockReturnValue("explore");
    renderTab(<SectorsTab />);
    expect(screen.getByText(/Colour = day change %/)).toBeInTheDocument();
  });

  it("labels live colours as unrealised P&L vs entry — never as market day change", () => {
    // The labelling fix from SectorMap: the live path maps the operator's own
    // positions, so `change` is P&L% against entry, and the legend says so.
    mockMode.mockReturnValue("live");
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "TCS", ltp: 4000, averagePrice: 3800, quantity: 1 }],
      }),
    );
    renderTab(<SectorsTab />);
    expect(screen.getByText(/Colour = unrealised P&L % vs entry/)).toBeInTheDocument();
    expect(screen.queryByText(/Colour = day change %/)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Bars view (from SectorPerformance — now with a live path)
// ---------------------------------------------------------------------------

describe("SectorsTab bars view", () => {
  it("renders all 6 timeframe tabs with 1D selected by default", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderTab(<SectorsTab initialView="bars" />);
    for (const tf of ["1D", "1W", "1M", "3M", "6M", "1Y"]) {
      expect(screen.getByRole("tab", { name: tf })).toBeTruthy();
    }
    expect(screen.getByRole("tab", { name: "1D" }).getAttribute("aria-selected")).toBe("true");
  });

  it("switching timeframe changes aria-selected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderTab(<SectorsTab initialView="bars" />);
    const tab1w = screen.getByRole("tab", { name: "1W" });
    fireEvent.click(tab1w);
    expect(tab1w.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "1D" }).getAttribute("aria-selected")).toBe("false");
  });

  it("shows the single sample sector dataset with a badge when disconnected, and never fetches", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderTab(<SectorsTab initialView="bars" />);

    expect(mockGetSectorRotation).not.toHaveBeenCalled();
    const badge = screen.getByText("Sample");
    expect(badge.getAttribute("title")).toMatch(/no live sector rotation data/i);
    // The one sample sector table renders (12 Nifty sectoral indices).
    for (const name of ["IT", "Pharma", "FMCG", "Realty", "PSU Bank"]) {
      expect(screen.getByText(name)).toBeTruthy();
    }
    expect(SAMPLE_SECTOR_ROTATION.sectors).toHaveLength(12);
    // Sample rows never render a freshness timestamp.
    expect(screen.queryByText(/Updated:/)).toBeNull();
  });

  it("keeps the badge when a connected response flags is_sample_data", async () => {
    mockGetSectorRotation.mockResolvedValue({ ...LIVE_ROTATION, is_sample_data: true });
    renderTab(<SectorsTab initialView="bars" />);
    // The badge stays and the fabricated backend rows never claim freshness.
    expect(await screen.findByText("Sample")).toBeTruthy();
    expect(screen.queryByText(/Updated:/)).toBeNull();
  });

  it("keeps the badge when a connected response omits is_sample_data (fail-closed)", async () => {
    const { is_sample_data: _dropped, ...unflagged } = LIVE_ROTATION;
    mockGetSectorRotation.mockResolvedValue(unflagged);
    renderTab(<SectorsTab initialView="bars" />);
    expect(await screen.findByText("Sample")).toBeTruthy();
  });

  it("drops the badge and shows live rows + timestamp on an explicit is_sample_data: false", async () => {
    renderTab(<SectorsTab initialView="bars" />);

    // Live rows replace the sample table entirely: the live payload has no
    // Media row, so the sample's Media bar must vanish.
    expect(await screen.findByText(/Updated: 2026-07-26 15:30 IST/)).toBeTruthy();
    expect(screen.queryByText("Sample")).toBeNull();
    expect(screen.getByText("IT")).toBeTruthy();
    expect(screen.getByText("Auto")).toBeTruthy();
    expect(screen.queryByText("Media")).toBeNull();
    // Ranked by 1D: IT (+2.50%) before Auto (-1.50%).
    expect(screen.getByLabelText("IT +2.50%")).toBeTruthy();
    expect(screen.getByLabelText("Auto -1.50%")).toBeTruthy();
  });

  it("renders the positive/negative counts row", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderTab(<SectorsTab initialView="bars" />);
    const upEl = document.querySelector(".text-profit.font-mono");
    const downEl = document.querySelector(".text-loss.font-mono");
    expect(upEl).toBeTruthy();
    expect(downEl).toBeTruthy();
  });

  it("bars container has an aria-label", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderTab(<SectorsTab initialView="bars" />);
    expect(screen.getByLabelText("Sector performance bars")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Heatmap view (rehomed from the Market Intelligence sector heatmap, D4)
// ---------------------------------------------------------------------------

describe("SectorsTab heatmap view", () => {
  it("is offered as a view alongside the bars", () => {
    renderTab(<SectorsTab />);
    expect(screen.getByTitle("Heatmap")).toBeInTheDocument();
  });

  it("sizes tiles by market cap — the dimension the bars view discards", async () => {
    renderTab(<SectorsTab initialView="heatmap" />);

    // Wait for the live payload to replace the sample rows before reading the
    // tile order — the aria-label is identical on both, so findByRole alone
    // would resolve against the sample table.
    await screen.findByText("+2.50%");
    const list = screen.getByRole("list", {
      name: "Sector heatmap by 1D return and market capitalisation",
    });
    const tiles = Array.from(
      list.querySelectorAll<HTMLElement>("[data-weighted-heatmap-tile]"),
    );
    // Ordered by market cap, heaviest first: IT (9.8L Cr) before Auto (5.4L Cr).
    expect(tiles.map((t) => t.dataset.weightedHeatmapTile)).toEqual(["NIFTYIT", "NIFTYAUTO"]);
    // The market cap is on screen, in the lakh-crore scale Indian desks read.
    expect(screen.getByText("9.8L Cr")).toBeInTheDocument();
    expect(screen.getByText("5.4L Cr")).toBeInTheDocument();
  });

  it("colours by the selected timeframe's return and re-labels on switch", async () => {
    renderTab(<SectorsTab initialView="heatmap" />);

    expect(await screen.findByText("+2.50%")).toBeInTheDocument();
    expect(screen.getByText("-1.50%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "1Y" }));

    // 1Y figures replace the 1D ones — one plane, one row set, two projections.
    expect(await screen.findByText("+6.00%")).toBeInTheDocument();
    expect(screen.getByText("+3.00%")).toBeInTheDocument();
    expect(screen.queryByText("+2.50%")).toBeNull();
  });

  it("reads the same rows as the bars view — no second fetch", async () => {
    renderTab(<SectorsTab initialView="heatmap" />);
    await screen.findByText("+2.50%");
    expect(mockGetSectorRotation).toHaveBeenCalledTimes(1);
  });

  it("badges sample rows and never claims freshness for them", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderTab(<SectorsTab initialView="heatmap" />);

    expect(mockGetSectorRotation).not.toHaveBeenCalled();
    expect(screen.getByText("Sample")).toBeInTheDocument();
    expect(screen.queryByText(/Updated:/)).toBeNull();
  });

  it("keeps the badge when a connected response omits is_sample_data (fail-closed)", async () => {
    const { is_sample_data: _dropped, ...unflagged } = LIVE_ROTATION;
    mockGetSectorRotation.mockResolvedValue(unflagged);
    renderTab(<SectorsTab initialView="heatmap" />);
    expect(await screen.findByText("Sample")).toBeTruthy();
  });

  it("states that tile size is market cap so colour is not read as the whole story", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderTab(<SectorsTab initialView="heatmap" />);
    expect(screen.getByText(/Tile size = market cap · Colour = 1D change/)).toBeInTheDocument();
  });

  it("does not render the position-map legend or stats", () => {
    // The heatmap projects the rotation plane, not the operator's positions, so
    // the P&L-vs-entry legend must stay off it.
    mockUseBrokerConnected.mockReturnValue(false);
    renderTab(<SectorsTab initialView="heatmap" />);
    expect(screen.queryByText(/Colour = day change %/)).toBeNull();
    expect(screen.queryByText(/Colour = unrealised P&L % vs entry/)).toBeNull();
  });
});
