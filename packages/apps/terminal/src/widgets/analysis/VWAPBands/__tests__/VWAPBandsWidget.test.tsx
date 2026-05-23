import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

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
import VWAPBandsWidget from "../VWAPBandsWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("VWAPBandsWidget", () => {
  it("renders the widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<VWAPBandsWidget />);
    expect(screen.getByText("VWAP Bands")).toBeTruthy();
  });

  it("shows Sample badge when broker disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<VWAPBandsWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when broker connected", () => {
    // Stub fetch to prevent unresolved async in test env
    global.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
    mockConnected.mockReturnValue(true);
    render(<VWAPBandsWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders VWAP stat labels", () => {
    mockConnected.mockReturnValue(false);
    render(<VWAPBandsWidget />);
    // "VWAP" and "Price" each appear in both the stat card and the band legend
    expect(screen.getAllByText("VWAP").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Price").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/VWAP/i).length).toBeGreaterThan(0);
  });

  it("renders symbol selector button defaulting to NIFTY", () => {
    mockConnected.mockReturnValue(false);
    render(<VWAPBandsWidget />);
    expect(screen.getByRole("button", { name: /selected symbol: NIFTY/i })).toBeTruthy();
  });

  it("opens symbol dropdown and shows all symbols", () => {
    mockConnected.mockReturnValue(false);
    render(<VWAPBandsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /selected symbol/i }));
    expect(screen.getByText("BANKNIFTY")).toBeTruthy();
    expect(screen.getByText("RELIANCE")).toBeTruthy();
    expect(screen.getByText("HDFCBANK")).toBeTruthy();
  });

  it("renders band legend entries", () => {
    mockConnected.mockReturnValue(false);
    render(<VWAPBandsWidget />);
    expect(screen.getByText("± 1σ")).toBeTruthy();
    expect(screen.getByText("± 2σ")).toBeTruthy();
    expect(screen.getByText("± 3σ")).toBeTruthy();
  });

  it("refresh button is disabled when broker disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<VWAPBandsWidget />);
    const btn = screen.getByRole("button", { name: /refresh VWAP data/i });
    expect(btn).toBeDisabled();
  });
});
