import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { WidgetProps } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
//
// When connected, the widget fetches expiries (getExpiry) and the IV smile per
// expiry (getFtIVSmile), then derives the aligned greek matrix. We mock both so
// we can exercise live, disconnected sample, and connected unavailable states.

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getExpiry: vi.fn(),
}));

vi.mock("@/services/ftApi.analysis", () => ({
  getFtIVSmile: vi.fn(),
}));

// FeatureTeaser passthrough + sentinel. The real teaser renders its children
// under aria-hidden, which would hide the sample matrix from role queries.
vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({ children, featureName }: { children: React.ReactNode; featureName: string }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>{children}</div>
  ),
}));

import React from "react";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getExpiry } from "@/services/api";
import { getFtIVSmile } from "@/services/ftApi.analysis";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import GreeksHeatmapWidget from "../GreeksHeatmapWidget";
import { SAMPLE_GREEKS_HEATMAP_DATA, SYMBOL_CHOICES } from "../GreeksHeatmapWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetExpiry = getExpiry as ReturnType<typeof vi.fn>;
const mockGetSmile = getFtIVSmile as ReturnType<typeof vi.fn>;

function liveSmile() {
  return {
    underlying: "NIFTY",
    spot_price: 22000,
    is_sample_data: false,
    curves: [
      {
        expiry: "17-APR-26",
        days_to_expiry: 8,
        atm_iv: 0.15,
        atm_strike: 22000,
        skew_25delta: 0.02,
        points: [
          { strike: 21800, call_iv: 0.16, put_iv: 0.165, moneyness: 0.991 },
          { strike: 22000, call_iv: 0.15, put_iv: 0.15, moneyness: 1.0 },
          { strike: 22200, call_iv: 0.145, put_iv: 0.148, moneyness: 1.009 },
        ],
      },
    ],
  };
}

/** Empty single-expiry smile (e.g. for a degenerate/zero-dte fixture). */
function emptySmile() {
  return { underlying: "NIFTY", spot_price: 0, curves: [], is_sample_data: false };
}

function renderWidget(
  params: Record<string, unknown> = {},
  overrides: Partial<WidgetProps> = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <GreeksHeatmapWidget {...makeWidgetPanelProps({ params, ...overrides })} />
    </QueryClientProvider>,
  );
}

/** Metric toggle button lookup (the toggle is a labelled radio-ish group). */
function metricButton(label: string): HTMLButtonElement {
  const group = screen.getByRole("group", { name: "Select metric" });
  return Array.from(group.querySelectorAll("button")).find(
    (b) => b.textContent === label,
  )!;
}

function projectionButton(label: string): HTMLButtonElement {
  const group = screen.getByRole("group", { name: "Select projection" });
  return Array.from(group.querySelectorAll("button")).find(
    (b) => b.textContent === label,
  )!;
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  mockConnected.mockReturnValue(false);
  mockGetExpiry.mockResolvedValue({ expiry: [] });
  mockGetSmile.mockResolvedValue(emptySmile());
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("GreeksHeatmapWidget (Greeks Matrix)", () => {
  it("renders header with widget title", () => {
    renderWidget();
    expect(screen.getByText("Greeks Matrix")).toBeTruthy();
  });

  it("shows Sample data badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("does not fetch when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockGetExpiry).not.toHaveBeenCalled();
    expect(mockGetSmile).not.toHaveBeenCalled();
  });

  it("flips to a Live badge once the IV smile yields a greek matrix", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["17-APR-26"] });
    mockGetSmile.mockResolvedValue(liveSmile());
    renderWidget();

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(mockGetSmile).toHaveBeenCalled();
  });

  // ---- Honesty invariants (all four carried over unchanged) ----------------

  it("rejects a connected IV smile explicitly flagged as sample data", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["17-APR-26"] });
    mockGetSmile.mockResolvedValue({ ...liveSmile(), is_sample_data: true });
    renderWidget();

    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("gridcell")).toHaveLength(0);
  });

  it("fails closed when a connected IV smile omits its provenance flag", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["17-APR-26"] });
    const { is_sample_data: _flag, ...unknownProvenance } = liveSmile();
    mockGetSmile.mockResolvedValue(unknownProvenance);
    renderWidget();

    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("gridcell")).toHaveLength(0);
  });

  it("shows unavailable instead of sample data when connected but no expiries are available", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: [] });
    renderWidget();

    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(mockGetSmile).not.toHaveBeenCalled();
  });

  it("shows unavailable instead of sample data when every expiry is degenerate", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["01-JAN-20"] });
    mockGetSmile.mockResolvedValue({ ...liveSmile(), curves: [{ ...liveSmile().curves[0], days_to_expiry: 0 }] });
    renderWidget();

    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("surfaces a connected live-read failure without rendering sample figures", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockRejectedValue(new Error("broker read failed"));
    renderWidget();

    await waitFor(() => expect(screen.getByText("Unavailable")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("gridcell")).toHaveLength(0);
    expect(screen.getByText("Live Greeks are unavailable for this symbol.")).toBeInTheDocument();
  });

  // ---- Absorbed from the retired GreeksSurface widget ----------------------

  it("renders the error banner message on a connected failure", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockRejectedValue(new Error("Greeks surface unavailable"));
    renderWidget();

    await waitFor(() => expect(screen.getByText(/greeks surface unavailable/i)).toBeInTheDocument());
  });

  it("shows the loading badge while a connected read is in flight", () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockReturnValue(new Promise(() => { /* never settles */ }));
    renderWidget();

    expect(screen.getByText("Loading")).toBeTruthy();
    expect(screen.getByText(/loading live greeks/i)).toBeTruthy();
  });

  it("wraps the disconnected sample matrix in a FeatureTeaser", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();

    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("feature-teaser").getAttribute("data-feature")).toBe(
      "Greeks Matrix",
    );
    // Visible honesty affordance for the fabricated matrix.
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("does not wrap a connected live matrix in a FeatureTeaser", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["17-APR-26"] });
    mockGetSmile.mockResolvedValue(liveSmile());
    renderWidget();

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.queryByTestId("feature-teaser")).toBeNull();
  });

  it("shows the term-structure caveat verbatim on the live matrix", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["17-APR-26"] });
    mockGetSmile.mockResolvedValue(liveSmile());
    renderWidget();

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(
      screen.getByText(
        /Every expiry reads the same IV snapshot — greeks by time, not a true term structure\./,
      ),
    ).toBeInTheDocument();
  });

  // ---- Metric toggle -------------------------------------------------------

  it("renders metric toggle buttons including IV and Vega", () => {
    renderWidget();
    const group = screen.getByRole("group", { name: "Select metric" });
    expect(group.querySelector("button[aria-pressed]")).toBeTruthy();
    expect(screen.getAllByText("IV %").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Delta").length).toBeGreaterThan(0);
    expect(screen.getByText("Gamma")).toBeTruthy();
    expect(screen.getByText("Theta")).toBeTruthy();
    expect(screen.getByText("Vega")).toBeTruthy();
  });

  it("Delta button is pressed by default", () => {
    renderWidget();
    const group = screen.getByRole("group", { name: "Select metric" });
    const pressed = group.querySelector("button[aria-pressed='true']");
    expect(pressed?.textContent).toBe("Delta");
  });

  it("clicking Gamma toggles its pressed state", () => {
    renderWidget();
    const gammaBtn = metricButton("Gamma");
    expect(gammaBtn.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(gammaBtn);
    expect(gammaBtn.getAttribute("aria-pressed")).toBe("true");
  });

  it("switching the metric updates the cell aria-labels", () => {
    renderWidget();
    fireEvent.click(metricButton("Vega"));

    const cells = screen.getAllByRole("gridcell");
    expect(cells.some((c) => c.getAttribute("aria-label")?.includes("Vega"))).toBe(true);
  });

  it("renders the colour legend for the selected metric", () => {
    renderWidget();
    // Default metric (Delta) appears on the toggle AND on the legend.
    expect(screen.getAllByText("Delta").length).toBeGreaterThanOrEqual(2);
    fireEvent.click(metricButton("IV %"));
    expect(screen.getAllByText("IV %").length).toBeGreaterThanOrEqual(2);
  });

  // ---- Projection ----------------------------------------------------------

  it("renders the 2-D heat grid by default", () => {
    renderWidget();
    expect(screen.getByRole("grid", { name: /heat grid/i })).toBeTruthy();
    expect(screen.queryByLabelText("Greeks surface 3D grid")).toBeNull();
  });

  it("renders the CSS-3D surface projection when selected", () => {
    renderWidget();
    fireEvent.click(projectionButton("Surface"));

    expect(screen.getByLabelText("Greeks surface 3D grid")).toBeTruthy();
    expect(screen.queryByRole("grid", { name: /heat grid/i })).toBeNull();
    expect(screen.getAllByRole("gridcell").length).toBeGreaterThan(0);
  });

  it("renders axis labels outside the 3-D transform, carrying REAL strikes", () => {
    renderWidget();
    fireEvent.click(projectionButton("Surface"));

    const surface = screen.getByLabelText("Greeks surface 3D grid");
    const strikeLabel = screen.getByText("22000");
    // The label lives outside the rotated container, so it stays readable.
    expect(surface.contains(strikeLabel)).toBe(false);
    expect(screen.getByText("Strike →")).toBeTruthy();
    expect(screen.getByText("Expiry →")).toBeTruthy();
  });

  it("shows the rotate and reset controls only under the surface projection", () => {
    renderWidget();
    expect(screen.queryByLabelText("Reset 3D view")).toBeNull();

    fireEvent.click(projectionButton("Surface"));

    expect(screen.getByLabelText("Reset 3D view")).toBeTruthy();
    expect(screen.getByLabelText("Rotate view up")).toBeTruthy();
    expect(screen.getByLabelText("Rotate view down")).toBeTruthy();
    expect(screen.getByLabelText("Rotate view left")).toBeTruthy();
    expect(screen.getByLabelText("Rotate view right")).toBeTruthy();
  });

  it("rotating and resetting changes the 3-D transform", () => {
    renderWidget({ projection: "surface" });
    const surface = screen.getByLabelText("Greeks surface 3D grid") as HTMLElement;
    const initial = surface.style.transform;

    fireEvent.click(screen.getByLabelText("Rotate view up"));
    expect(surface.style.transform).not.toBe(initial);

    fireEvent.click(screen.getByLabelText("Reset 3D view"));
    expect(surface.style.transform).toBe(initial);
  });

  // ---- Panel params (how the retired `greekssurface` id survives) ----------

  it("opens the retired greekssurface view from panel params", () => {
    renderWidget({ projection: "surface", metric: "iv" });

    expect(screen.getByLabelText("Greeks surface 3D grid")).toBeTruthy();
    const group = screen.getByRole("group", { name: "Select metric" });
    expect(group.querySelector("button[aria-pressed='true']")?.textContent).toBe("IV %");
  });

  it("falls back to the grid/delta view for unrecognised params", () => {
    renderWidget({ projection: "hologram", metric: "rho" });

    expect(screen.getByRole("grid", { name: /heat grid/i })).toBeTruthy();
    const group = screen.getByRole("group", { name: "Select metric" });
    expect(group.querySelector("button[aria-pressed='true']")?.textContent).toBe("Delta");
  });

  it("persists a projection and metric change into the panel params", () => {
    const updateParameters = vi.fn();
    renderWidget(
      { projection: "grid" },
      { api: { updateParameters } as unknown as WidgetProps["api"] },
    );

    fireEvent.click(projectionButton("Surface"));
    expect(updateParameters).toHaveBeenCalledWith({ projection: "surface" });

    fireEvent.click(metricButton("Vega"));
    expect(updateParameters).toHaveBeenCalledWith({ projection: "grid", metric: "vega" });
  });

  // ---- Shell ---------------------------------------------------------------

  it("renders heatmap grid cells for all expiries and strikes (sample mode)", () => {
    renderWidget();
    const cells = screen.getAllByRole("gridcell");
    // 3 expiries × 9 strikes = 27 cells
    expect(cells.length).toBe(27);
  });

  it("renders symbol selector with expected options", () => {
    renderWidget();
    const trigger = screen.getByLabelText("Select symbol");
    expect(trigger).toBeTruthy();
    expect(trigger.textContent).toContain("NIFTY");
    // The retired surface's own symbol list, pinned on the merged widget.
    expect(SYMBOL_CHOICES).toContain("NIFTY");
    expect(SYMBOL_CHOICES).toContain("BANKNIFTY");
    expect(SYMBOL_CHOICES).toContain("SENSEX");
  });

  it("does not render a dead refresh button (removed deceptive affordance)", () => {
    renderWidget();
    // Both retired labels: the heatmap never had one, and the surface's button
    // rendered even while disconnected, where its query cannot refetch.
    expect(screen.queryByLabelText("Refresh Greeks heatmap")).toBeNull();
    expect(screen.queryByLabelText("Refresh Greeks surface")).toBeNull();
    expect(screen.queryByLabelText("Refresh Greeks matrix")).toBeNull();
  });

  it("footer shows expiry and strike counts (sample mode)", () => {
    renderWidget();
    expect(screen.getByText(/3 expiries/i)).toBeTruthy();
    expect(screen.getByText(/9 strikes/i)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sample data tests
// ---------------------------------------------------------------------------

describe("SAMPLE_GREEKS_HEATMAP_DATA", () => {
  it("has 3 expiry rows", () => {
    expect(SAMPLE_GREEKS_HEATMAP_DATA).toHaveLength(3);
  });

  it("each row has 9 strike cells", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      expect(row.cells).toHaveLength(9);
    }
  });

  it("each row has at least one ATM cell", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      const atm = row.cells.find((c) => c.moneyness === "ATM");
      expect(atm).toBeDefined();
    }
  });

  it("delta values are between 0 and 1", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      for (const cell of row.cells) {
        expect(cell.delta).toBeGreaterThanOrEqual(0);
        expect(cell.delta).toBeLessThanOrEqual(1);
      }
    }
  });

  it("theta values are non-positive (cost)", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      for (const cell of row.cells) {
        expect(cell.theta).toBeLessThanOrEqual(0);
      }
    }
  });

  it("vega values are non-negative", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      for (const cell of row.cells) {
        expect(cell.vega).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("all IV values are positive", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      for (const cell of row.cells) {
        expect(cell.iv).toBeGreaterThan(0);
      }
    }
  });

  it("near expiry has higher average gamma than back month (term structure)", () => {
    const avgGamma = (row: (typeof SAMPLE_GREEKS_HEATMAP_DATA)[0]) =>
      row.cells.reduce((s, c) => s + c.gamma, 0) / row.cells.length;
    // Average over all strikes to smooth out random noise
    const nearAvg = avgGamma(SAMPLE_GREEKS_HEATMAP_DATA[0]);
    const backAvg = avgGamma(SAMPLE_GREEKS_HEATMAP_DATA[2]);
    expect(nearAvg).toBeGreaterThan(backAvg);
  });

  it("front week DTE < front month DTE < back month DTE", () => {
    const [fw, fm, bm] = SAMPLE_GREEKS_HEATMAP_DATA;
    expect(fw.dte).toBeLessThan(fm.dte);
    expect(fm.dte).toBeLessThan(bm.dte);
  });

  it("front week ATM IV is higher than back month ATM IV (term structure)", () => {
    const atmIv = (row: (typeof SAMPLE_GREEKS_HEATMAP_DATA)[0]) =>
      row.cells.find((c) => c.moneyness === "ATM")!.iv;

    expect(atmIv(SAMPLE_GREEKS_HEATMAP_DATA[0])).toBeGreaterThan(
      atmIv(SAMPLE_GREEKS_HEATMAP_DATA[2]),
    );
  });
});
