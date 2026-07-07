import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Module mocks — must be declared before dynamic imports
// ---------------------------------------------------------------------------

vi.mock("../useGreeksSurface", () => ({
  useGreeksSurface: vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

// Mock shadcn/ui Select to render as native <select> for testability
vi.mock("@/components/ui/select", async () => {
  const { createContext, useContext } = await import("react");
  type SelectCtx = { value?: string; onValueChange?: (v: string) => void };
  const Ctx = createContext<SelectCtx>({});
  return {
    Select: ({
      value,
      onValueChange,
      children,
    }: {
      value?: string;
      onValueChange?: (v: string) => void;
      children?: React.ReactNode;
    }) => <Ctx.Provider value={{ value, onValueChange }}>{children}</Ctx.Provider>,
    SelectTrigger: ({ "aria-label": ariaLabel }: { "aria-label"?: string; [key: string]: unknown }) => (
      <span aria-label={ariaLabel} />
    ),
    SelectValue: () => null,
    SelectContent: ({ children }: { children?: React.ReactNode }) => {
      const ctx = useContext(Ctx);
      return (
        <select
          role="combobox"
          value={ctx.value ?? ""}
          onChange={(e) => ctx.onValueChange?.(e.target.value)}
        >
          {children}
        </select>
      );
    },
    SelectItem: ({ value, children }: { value: string; children?: React.ReactNode }) => (
      <option value={value}>{children}</option>
    ),
  };
});

// Mock shadcn/ui Input
vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}));

import React from "react";

vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({
    children,
    featureName,
  }: {
    children: React.ReactNode;
    featureName: string;
  }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>
      {children}
    </div>
  ),
}));

import { useGreeksSurface } from "../useGreeksSurface";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import GreeksSurfaceWidget from "../GreeksSurfaceWidget";
import { SAMPLE_GREEKS_SURFACE_DATA } from "../sampleData";

const mockUseGreeksSurface = useGreeksSurface as ReturnType<typeof vi.fn>;
const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

const IDLE_QUERY = {
  data: undefined,
  isLoading: false,
  isError: false,
  error: null,
  refetch: vi.fn(),
  isFetching: false,
};

describe("GreeksSurfaceWidget", () => {
  it("renders sample data with FeatureTeaser when broker disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseGreeksSurface.mockReturnValue(IDLE_QUERY);

    render(<GreeksSurfaceWidget />, { wrapper });

    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("feature-teaser").getAttribute("data-feature")).toBe(
      "Greeks Surface",
    );
    // Visible honesty affordance for the fabricated surface.
    expect(screen.getByText("Demo data")).toBeTruthy();
  });

  it("shows the Demo data badge when a connected payload is flagged is_sample_data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGreeksSurface.mockReturnValue({
      ...IDLE_QUERY,
      data: { expiries: SAMPLE_GREEKS_SURFACE_DATA, isSampleData: true },
    });

    render(<GreeksSurfaceWidget />, { wrapper });

    expect(screen.getByText("Demo data")).toBeTruthy();
    // No teaser when connected — the badge alone flags the fabricated data.
    expect(screen.queryByTestId("feature-teaser")).toBeNull();
  });

  it("hides the Demo data badge for a live (unflagged) connected payload", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGreeksSurface.mockReturnValue({
      ...IDLE_QUERY,
      data: { expiries: SAMPLE_GREEKS_SURFACE_DATA, isSampleData: false },
    });

    render(<GreeksSurfaceWidget />, { wrapper });

    expect(screen.queryByText("Demo data")).toBeNull();
  });

  it("shows loading state when connected and fetching", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGreeksSurface.mockReturnValue({
      ...IDLE_QUERY,
      isLoading: true,
      isFetching: true,
    });

    render(<GreeksSurfaceWidget />, { wrapper });

    expect(screen.getByText(/loading greeks surface/i)).toBeTruthy();
  });

  it("shows empty state when connected but no data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGreeksSurface.mockReturnValue(IDLE_QUERY);

    render(<GreeksSurfaceWidget />, { wrapper });

    expect(screen.getByText(/select symbol to view greeks surface/i)).toBeTruthy();
  });

  it("renders error banner when query fails", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGreeksSurface.mockReturnValue({
      ...IDLE_QUERY,
      isError: true,
      error: new Error("Greeks surface unavailable"),
    });

    render(<GreeksSurfaceWidget />, { wrapper });

    expect(screen.getByText(/greeks surface unavailable/i)).toBeTruthy();
  });

  it("renders surface grid cells when connected with live data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGreeksSurface.mockReturnValue({
      ...IDLE_QUERY,
      data: { expiries: SAMPLE_GREEKS_SURFACE_DATA, isSampleData: false },
    });

    render(<GreeksSurfaceWidget />, { wrapper });

    // Grid cells rendered — should have role="gridcell"
    const cells = screen.getAllByRole("gridcell");
    expect(cells.length).toBeGreaterThan(0);
  });

  it("renders colour legend", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGreeksSurface.mockReturnValue({
      ...IDLE_QUERY,
      data: { expiries: SAMPLE_GREEKS_SURFACE_DATA, isSampleData: false },
    });

    render(<GreeksSurfaceWidget />, { wrapper });

    // Colour legend label appears at least once ("IV %" also in metric toggle button)
    const ivLabels = screen.getAllByText("IV %");
    expect(ivLabels.length).toBeGreaterThanOrEqual(1);
  });

  it("metric toggle buttons are rendered", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseGreeksSurface.mockReturnValue(IDLE_QUERY);

    render(<GreeksSurfaceWidget />, { wrapper });

    // At least one element with "IV %" text (toggle button)
    expect(screen.getAllByText("IV %").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Delta")).toBeTruthy();
    expect(screen.getByText("Gamma")).toBeTruthy();
    expect(screen.getByText("Theta")).toBeTruthy();
  });

  it("switching metric updates aria-label on cells", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGreeksSurface.mockReturnValue({
      ...IDLE_QUERY,
      data: { expiries: SAMPLE_GREEKS_SURFACE_DATA, isSampleData: false },
    });

    render(<GreeksSurfaceWidget />, { wrapper });

    // Switch to Delta
    fireEvent.click(screen.getByText("Delta"));

    const cells = screen.getAllByRole("gridcell");
    // At least one cell should mention "Delta"
    const hasDelta = cells.some((c) =>
      c.getAttribute("aria-label")?.includes("Delta"),
    );
    expect(hasDelta).toBe(true);
  });

  it("rotate and reset buttons are present", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseGreeksSurface.mockReturnValue(IDLE_QUERY);

    render(<GreeksSurfaceWidget />, { wrapper });

    expect(screen.getByLabelText("Reset 3D view")).toBeTruthy();
    expect(screen.getByLabelText("Rotate view up")).toBeTruthy();
    expect(screen.getByLabelText("Rotate view down")).toBeTruthy();
    expect(screen.getByLabelText("Rotate view left")).toBeTruthy();
    expect(screen.getByLabelText("Rotate view right")).toBeTruthy();
  });

  it("refresh button is present", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseGreeksSurface.mockReturnValue(IDLE_QUERY);

    render(<GreeksSurfaceWidget />, { wrapper });

    expect(screen.getByLabelText("Refresh Greeks surface")).toBeTruthy();
  });

  it("symbol selector renders all supported symbols", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseGreeksSurface.mockReturnValue(IDLE_QUERY);

    render(<GreeksSurfaceWidget />, { wrapper });

    // With the mocked Select, SelectContent renders a native <select role="combobox">
    const selects = screen.getAllByRole("combobox") as HTMLSelectElement[];
    // The symbol selector is the first combobox
    const symbolSelect = selects[0];
    const options = Array.from(symbolSelect.options).map((o) => o.value);
    expect(options).toContain("NIFTY");
    expect(options).toContain("BANKNIFTY");
    expect(options).toContain("SENSEX");
  });
});

// ---------------------------------------------------------------------------
// Sample data unit tests
// ---------------------------------------------------------------------------

describe("SAMPLE_GREEKS_SURFACE_DATA", () => {
  it("has three expiry curves", () => {
    expect(SAMPLE_GREEKS_SURFACE_DATA).toHaveLength(3);
  });

  it("each expiry has 11 moneyness points (-5% to +5%)", () => {
    for (const exp of SAMPLE_GREEKS_SURFACE_DATA) {
      expect(exp.points).toHaveLength(11);
    }
  });

  it("ATM point has moneyness label 'ATM'", () => {
    for (const exp of SAMPLE_GREEKS_SURFACE_DATA) {
      const atm = exp.points.find((p) => p.moneyness === "ATM");
      expect(atm).toBeDefined();
    }
  });

  it("all IV values are positive", () => {
    for (const exp of SAMPLE_GREEKS_SURFACE_DATA) {
      for (const pt of exp.points) {
        expect(pt.iv).toBeGreaterThan(0);
      }
    }
  });

  it("delta is between 0 and 1", () => {
    for (const exp of SAMPLE_GREEKS_SURFACE_DATA) {
      for (const pt of exp.points) {
        expect(pt.delta).toBeGreaterThanOrEqual(0);
        expect(pt.delta).toBeLessThanOrEqual(1);
      }
    }
  });

  it("front week DTE < front month DTE < back month DTE", () => {
    const [fw, fm, bm] = SAMPLE_GREEKS_SURFACE_DATA;
    expect(fw.dte).toBeLessThan(fm.dte);
    expect(fm.dte).toBeLessThan(bm.dte);
  });

  it("front week ATM IV is higher than back month ATM IV (term structure)", () => {
    const atmIV = (exp: (typeof SAMPLE_GREEKS_SURFACE_DATA)[0]) =>
      exp.points.find((p) => p.moneyness === "ATM")!.iv;

    expect(atmIV(SAMPLE_GREEKS_SURFACE_DATA[0])).toBeGreaterThan(
      atmIV(SAMPLE_GREEKS_SURFACE_DATA[2]),
    );
  });
});
