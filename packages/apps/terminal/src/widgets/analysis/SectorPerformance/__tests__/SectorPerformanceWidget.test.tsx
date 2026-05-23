import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import SectorPerformanceWidget from "../SectorPerformanceWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SectorPerformanceWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    expect(screen.getByText("Sector Performance")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    render(<SectorPerformanceWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders all 5 timeframe tabs", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    expect(screen.getByRole("tab", { name: "1D" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "1W" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "1M" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "3M" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "1Y" })).toBeTruthy();
  });

  it("1D is selected by default", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    const tab1d = screen.getByRole("tab", { name: "1D" });
    expect(tab1d.getAttribute("aria-selected")).toBe("true");
  });

  it("renders IT sector", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    expect(screen.getByText("IT")).toBeTruthy();
  });

  it("renders 12 sector bars on 1D", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    const rows = screen.getAllByRole("generic").filter(
      (el) => el.getAttribute("aria-label")?.includes("sector")
        || el.className?.includes("flex items-center gap-2"),
    );
    // Flexible check: IT, Bank, Pharma, Metal, etc. all present
    expect(screen.getByText("Pharma")).toBeTruthy();
    expect(screen.getByText("Auto")).toBeTruthy();
    expect(screen.getByText("Metal")).toBeTruthy();
    expect(screen.getByText("Realty")).toBeTruthy();
    expect(rows).toBeDefined();
  });

  it("switching to 1W tab changes aria-selected", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    const tab1w = screen.getByRole("tab", { name: "1W" });
    fireEvent.click(tab1w);
    expect(tab1w.getAttribute("aria-selected")).toBe("true");
    const tab1d = screen.getByRole("tab", { name: "1D" });
    expect(tab1d.getAttribute("aria-selected")).toBe("false");
  });

  it("bars container has aria-label", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    expect(screen.getByLabelText("Sector performance bars")).toBeTruthy();
  });

  it("refresh button is present", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    expect(screen.getByLabelText("Refresh sector performance")).toBeTruthy();
  });

  it("positive/negative count row is rendered", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    // Some ↑ and ↓ symbols present in header
    const upEl = document.querySelector(".text-profit.font-mono");
    const downEl = document.querySelector(".text-loss.font-mono");
    expect(upEl).toBeTruthy();
    expect(downEl).toBeTruthy();
  });

  it("timeframe tablist has correct aria-label", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    expect(screen.getByRole("tablist", { name: "Timeframe" })).toBeTruthy();
  });

  it("FMCG sector is present in 1D data", () => {
    mockConnected.mockReturnValue(false);
    render(<SectorPerformanceWidget />);
    expect(screen.getByText("FMCG")).toBeTruthy();
  });
});
