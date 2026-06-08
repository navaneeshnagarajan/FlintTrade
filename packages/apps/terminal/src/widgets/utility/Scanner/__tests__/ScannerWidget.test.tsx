/**
 * ScannerWidget.test.tsx — Basic render and interaction tests for Pre-Market Scanner.
 */

import { describe, it, expect, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock });

// Suppress ResizeObserver noise
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

import ScannerWidget from "../ScannerWidget";

describe("ScannerWidget", () => {
  it("renders scanner header and tabs", () => {
    render(<ScannerWidget />);
    expect(screen.getByText("Scanner")).toBeInTheDocument();
    expect(screen.getByText("Gap Scan")).toBeInTheDocument();
    expect(screen.getByText("OI Change")).toBeInTheDocument();
    // "Volume" appears both as tab and table header — use getAllByText
    expect(screen.getAllByText("Volume").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Sectors")).toBeInTheDocument();
  });

  it("shows sample data notice", () => {
    render(<ScannerWidget />);
    expect(
      screen.getByText(/sample data/i),
    ).toBeInTheDocument();
  });

  it("renders Gap Scan tab with stock data by default", () => {
    render(<ScannerWidget />);
    // Gap Scan is default tab — should show some NIFTY 50 stocks
    expect(screen.getByText("TATAMOTORS")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
  });

  it("switches to OI Change tab", () => {
    render(<ScannerWidget />);
    fireEvent.click(screen.getByText("OI Change"));
    // OI Change tab shows options symbols
    expect(screen.getByText("NIFTY 24200 CE")).toBeInTheDocument();
  });

  it("switches to Volume tab", () => {
    render(<ScannerWidget />);
    // The tab nav has aria-label "Scanner tabs" — find Volume button within it
    const nav = screen.getByLabelText("Scanner tabs");
    const volumeTab = nav.querySelector("button:nth-child(3)");
    expect(volumeTab).not.toBeNull();
    fireEvent.click(volumeTab!);
    // Volume tab shows Vol Ratio column header
    expect(screen.getByText("Vol Ratio")).toBeInTheDocument();
  });

  it("switches to Sectors tab", () => {
    render(<ScannerWidget />);
    fireEvent.click(screen.getByText("Sectors"));
    // Sectors tab shows sector names
    expect(screen.getByText("Auto")).toBeInTheDocument();
    expect(screen.getByText("Banking")).toBeInTheDocument();
  });

  it("does not render a deceptive refresh button or live-looking clock over static sample data", () => {
    // The scanner has no live feed (rows come from static sampleData, disclosed
    // by the "Sample data" notice). The old "last refreshed" clock + manual
    // refresh spinner only bumped a timestamp / slept over unchanging data —
    // removed so nothing implies a live refresh that never happens.
    render(<ScannerWidget />);
    expect(screen.queryByLabelText("Refresh scanner")).not.toBeInTheDocument();
    expect(screen.getByText(/Sample data/i)).toBeInTheDocument();
  });

  it("renders Add to Watchlist buttons in Gap Scan", () => {
    render(<ScannerWidget />);
    const addButtons = screen.getAllByLabelText(/Add .* to watchlist/i);
    expect(addButtons.length).toBeGreaterThan(0);
  });
});
