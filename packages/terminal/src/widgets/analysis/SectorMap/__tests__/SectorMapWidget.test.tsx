/**
 * SectorMapWidget.test.tsx
 *
 * Tests for the Sector Map analysis widget.
 * Verifies rendering, demo data display, and view mode controls.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

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

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
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

// Mock sector map data hook
vi.mock("@/hooks/useSectorMapData", () => ({
  __esModule: true,
  default: () => null,
  useSectorMapData: () => null,
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

const defaultProps = {} as Parameters<typeof SectorMapWidget>[0];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SectorMapWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
