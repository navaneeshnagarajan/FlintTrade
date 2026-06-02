/**
 * GlobalIndicesWidget.test.tsx
 *
 * Tests: render, regions, table headers, sample data, loading state.
 */

import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

import GlobalIndicesWidget from "../GlobalIndicesWidget";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("GlobalIndicesWidget", () => {
  it("renders the widget header", () => {
    render(<GlobalIndicesWidget />, { wrapper });
    expect(screen.getByText("Global Indices")).toBeTruthy();
  });

  it("renders table column headers", () => {
    render(<GlobalIndicesWidget />, { wrapper });
    expect(screen.getByText("Index")).toBeTruthy();
    expect(screen.getByText("LTP")).toBeTruthy();
    expect(screen.getByText("Chg")).toBeTruthy();
    expect(screen.getByText("Trend")).toBeTruthy();
  });

  it("renders region group headers from sample data", () => {
    render(<GlobalIndicesWidget />, { wrapper });
    expect(screen.getByText("India")).toBeTruthy();
    expect(screen.getByText("US")).toBeTruthy();
    expect(screen.getByText("Europe")).toBeTruthy();
    expect(screen.getByText("Asia")).toBeTruthy();
  });

  it("renders sample index names", () => {
    render(<GlobalIndicesWidget />, { wrapper });
    expect(screen.getByText("NIFTY 50")).toBeTruthy();
    expect(screen.getByText("S&P 500")).toBeTruthy();
    expect(screen.getByText("FTSE 100")).toBeTruthy();
    expect(screen.getByText("Nikkei 225")).toBeTruthy();
  });

  it("shows sample data label when disconnected", () => {
    render(<GlobalIndicesWidget />, { wrapper });
    expect(screen.getByText("(sample data)")).toBeTruthy();
  });

  it("renders sparklines for each index row", () => {
    render(<GlobalIndicesWidget />, { wrapper });
    const sparklines = screen.getAllByRole("img", { name: /30-day index sparkline/i });
    expect(sparklines.length).toBeGreaterThanOrEqual(10);
    expect(sparklines[0]).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparklines[0].querySelector("polyline")).not.toBeInTheDocument();
    expect(sparklines[0].querySelectorAll("path").length).toBeGreaterThan(0);
  });
});
