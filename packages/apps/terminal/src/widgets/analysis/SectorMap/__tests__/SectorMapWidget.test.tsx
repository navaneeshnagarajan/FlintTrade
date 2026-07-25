/**
 * SectorMapWidget.test.tsx
 *
 * Tests for the Sector Map analysis widget.
 * Verifies rendering, demo data display, and view mode controls.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// Stub ResizeObserver (not available in JSDOM)
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

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockUseBrokerConnected(),
}));

// Mock Jotai
vi.mock("jotai", () => ({
  atom: (v: unknown) => v,
  useAtom: () => [[], vi.fn()],
}));

// Mock RRG data hook
vi.mock("@/hooks/useRRGData", () => ({
  useRRGData: () => ({ data: null, isLoading: false, error: null }),
}));

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

import SectorMapWidget from "../SectorMapWidget";
import { RRGCanvas } from "../RRGCanvas";
import type { RRGResponse } from "@/services/ftApi";

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

const defaultProps = makeDockviewPanelProps();

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SectorMapWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseBrokerConnected.mockReturnValue(true);
    // No positions — widget falls back to demo data
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
  });

  it("renders without crashing", () => {
    const { container } = render(<SectorMapWidget {...defaultProps} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the Sector Map heading", () => {
    render(<SectorMapWidget {...defaultProps} />);
    expect(screen.getByText("Sector Map")).toBeInTheDocument();
  });

  it("labels fallback sector data as sample and does not fetch positions when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<SectorMapWidget {...defaultProps} />);

    expect(mockUsePositions).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("shows view mode toggle buttons (Treemap, Grid, Sectors)", () => {
    render(<SectorMapWidget {...defaultProps} />);
    expect(screen.getByTitle("Treemap")).toBeInTheDocument();
    expect(screen.getByTitle("Grid")).toBeInTheDocument();
    expect(screen.getByTitle("Sectors")).toBeInTheDocument();
  });

  it("shows legend footer with colour gradient", () => {
    render(<SectorMapWidget {...defaultProps} />);
    expect(screen.getByText(/-4% → \+4%/)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// RRGCanvas provenance — the sample indicator must fail closed, exactly as
// PortfolioRRGTab's badge already does.
// ---------------------------------------------------------------------------

describe("RRGCanvas provenance", () => {
  beforeEach(() => {
    // JSDOM has no Canvas 2D implementation; the draw loop bails on a null
    // context, so the surrounding markup is what these tests exercise.
    HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(null);
  });

  /** `is_sample_data` is a required field in the TS type but optional on the
   *  wire, so the absent case needs an assertion to be expressible. */
  function rrgResponse(provenance: { is_sample_data?: boolean }): RRGResponse {
    return {
      benchmark: "NIFTY 50",
      tail_length: 2,
      sectors: [
        {
          symbol: "NIFTYIT",
          name: "Nifty IT",
          current_quadrant: "leading",
          tail: [
            { date: "2026-07-17", rs_ratio: 100.4, rs_momentum: 100.2 },
            { date: "2026-07-18", rs_ratio: 100.9, rs_momentum: 100.6 },
          ],
        },
      ],
      ...provenance,
    } as RRGResponse;
  }

  it("badges the plot as sample when the response omits is_sample_data", () => {
    render(<RRGCanvas data={rrgResponse({})} tailLength={2} />);
    expect(screen.getByText("sample data")).toBeInTheDocument();
  });

  it("drops the badge only on an explicit is_sample_data: false", () => {
    render(<RRGCanvas data={rrgResponse({ is_sample_data: false })} tailLength={2} />);
    expect(screen.queryByText("sample data")).not.toBeInTheDocument();
  });

  it("badges the plot as sample on an explicit is_sample_data: true", () => {
    render(<RRGCanvas data={rrgResponse({ is_sample_data: true })} tailLength={2} />);
    expect(screen.getByText("sample data")).toBeInTheDocument();
  });
});
