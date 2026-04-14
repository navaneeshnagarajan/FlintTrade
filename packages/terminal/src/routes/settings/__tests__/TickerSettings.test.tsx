/**
 * TickerSettings.test.tsx — Unit tests for the Ticker Bar settings section.
 *
 * Covers:
 *   - Mode selector renders and updates store
 *   - Speed slider rendered when mode is "marquee", hidden otherwise
 *   - Symbol list renders existing symbols
 *   - Remove button calls setTickerSymbols correctly
 *   - Reset button restores defaults
 *   - AddSymbolInput renders and reacts to direct EXCHANGE:SYMBOL entry
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mock dependencies before imports
// ---------------------------------------------------------------------------

// searchSymbol — not called in most tests (we test direct entry path)
vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn().mockResolvedValue([]),
}));

// Zustand settingsStore — we inject a controllable mock
const mockSetTickerMode = vi.fn();
const mockSetTickerSymbols = vi.fn();
const mockSetTickerSpeed = vi.fn();

let mockState = {
  tickerMode: "marquee" as import("@/stores/settingsStore").TickerMode,
  tickerSymbols: ["NSE_INDEX:NIFTY", "BSE_INDEX:SENSEX"],
  tickerSpeed: 30,
  setTickerMode: mockSetTickerMode,
  setTickerSymbols: mockSetTickerSymbols,
  setTickerSpeed: mockSetTickerSpeed,
};

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
  DEFAULT_TICKER_SYMBOLS: [
    "NSE_INDEX:NIFTY",
    "BSE_INDEX:SENSEX",
    "NSE_INDEX:BANKNIFTY",
    "NSE_INDEX:INDIAVIX",
    "MCX:GOLD",
    "MCX:SILVER",
    "MCX:CRUDEOIL",
    "MCX:NATURALGAS",
  ],
}));

// ---------------------------------------------------------------------------
// Import component after mocks
// ---------------------------------------------------------------------------

import { TickerSettings } from "../TickerSettings";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderTickerSettings() {
  return render(<TickerSettings />);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TickerSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset mock state to defaults
    mockState = {
      tickerMode: "marquee",
      tickerSymbols: ["NSE_INDEX:NIFTY", "BSE_INDEX:SENSEX"],
      tickerSpeed: 30,
      setTickerMode: mockSetTickerMode,
      setTickerSymbols: mockSetTickerSymbols,
      setTickerSpeed: mockSetTickerSpeed,
    };
  });

  // ── Section header ─────────────────────────────────────────────────────────

  it("renders the Ticker Bar section title", () => {
    renderTickerSettings();
    expect(screen.getByText("Ticker Bar")).toBeInTheDocument();
  });

  // ── Mode selector ──────────────────────────────────────────────────────────

  it("renders all four mode options", () => {
    renderTickerSettings();
    expect(screen.getByText("Off")).toBeInTheDocument();
    expect(screen.getByText("Pinned")).toBeInTheDocument();
    expect(screen.getByText("Scroll")).toBeInTheDocument();
    expect(screen.getByText("Marquee")).toBeInTheDocument();
  });

  it("calls setTickerMode when a mode button is pressed", () => {
    renderTickerSettings();
    fireEvent.click(screen.getByText("Off"));
    expect(mockSetTickerMode).toHaveBeenCalledWith("off");
  });

  it("calls setTickerMode with 'pinned' when Pinned is pressed", () => {
    renderTickerSettings();
    fireEvent.click(screen.getByText("Pinned"));
    expect(mockSetTickerMode).toHaveBeenCalledWith("pinned");
  });

  // ── Speed slider ───────────────────────────────────────────────────────────

  it("shows speed slider when mode is 'marquee'", () => {
    renderTickerSettings();
    expect(screen.getByTestId("ticker-speed-slider")).toBeInTheDocument();
  });

  it("hides speed slider when mode is 'off'", () => {
    mockState = { ...mockState, tickerMode: "off" };
    renderTickerSettings();
    expect(screen.queryByTestId("ticker-speed-slider")).not.toBeInTheDocument();
  });

  it("hides speed slider when mode is 'pinned'", () => {
    mockState = { ...mockState, tickerMode: "pinned" };
    renderTickerSettings();
    expect(screen.queryByTestId("ticker-speed-slider")).not.toBeInTheDocument();
  });

  it("hides speed slider when mode is 'scroll'", () => {
    mockState = { ...mockState, tickerMode: "scroll" };
    renderTickerSettings();
    expect(screen.queryByTestId("ticker-speed-slider")).not.toBeInTheDocument();
  });

  it("slider reflects the current tickerSpeed value", () => {
    mockState = { ...mockState, tickerSpeed: 45 };
    renderTickerSettings();
    const slider = screen.getByTestId("ticker-speed-slider") as HTMLInputElement;
    expect(slider.value).toBe("45");
  });

  it("calls setTickerSpeed when slider value changes", () => {
    renderTickerSettings();
    const slider = screen.getByTestId("ticker-speed-slider");
    fireEvent.change(slider, { target: { value: "50" } });
    expect(mockSetTickerSpeed).toHaveBeenCalledWith(50);
  });

  // ── Symbol list ────────────────────────────────────────────────────────────

  it("renders existing ticker symbols", () => {
    renderTickerSettings();
    expect(screen.getByTestId("ticker-symbol-list")).toBeInTheDocument();
    expect(screen.getByTestId("ticker-symbol-tag-NSE_INDEX:NIFTY")).toBeInTheDocument();
    expect(screen.getByTestId("ticker-symbol-tag-BSE_INDEX:SENSEX")).toBeInTheDocument();
  });

  it("shows symbol count in the header", () => {
    renderTickerSettings();
    expect(screen.getByText("Symbols (2)")).toBeInTheDocument();
  });

  it("shows empty state message when symbol list is empty", () => {
    mockState = { ...mockState, tickerSymbols: [] };
    renderTickerSettings();
    expect(screen.getByText(/No symbols configured/)).toBeInTheDocument();
    expect(screen.queryByTestId("ticker-symbol-list")).not.toBeInTheDocument();
  });

  it("remove button calls setTickerSymbols without the removed symbol", () => {
    renderTickerSettings();
    const removeBtn = screen.getByTestId("remove-symbol-NSE_INDEX:NIFTY");
    fireEvent.click(removeBtn);
    expect(mockSetTickerSymbols).toHaveBeenCalledWith(["BSE_INDEX:SENSEX"]);
  });

  // ── Reset button ───────────────────────────────────────────────────────────

  it("reset button restores DEFAULT_TICKER_SYMBOLS", () => {
    renderTickerSettings();
    fireEvent.click(screen.getByTestId("ticker-reset-symbols"));
    expect(mockSetTickerSymbols).toHaveBeenCalledWith(
      expect.arrayContaining(["NSE_INDEX:NIFTY", "BSE_INDEX:SENSEX", "MCX:GOLD"]),
    );
    expect(mockSetTickerSymbols.mock.calls[0][0]).toHaveLength(8);
  });

  // ── Add symbol input ───────────────────────────────────────────────────────

  it("renders the symbol search input", () => {
    renderTickerSettings();
    expect(screen.getByTestId("ticker-symbol-search")).toBeInTheDocument();
  });

  it("renders the add symbol button", () => {
    renderTickerSettings();
    expect(screen.getByTestId("ticker-add-symbol-btn")).toBeInTheDocument();
  });

  it("add button calls setTickerSymbols for a direct EXCHANGE:SYMBOL entry", () => {
    renderTickerSettings();
    const input = screen.getByTestId("ticker-symbol-search");
    fireEvent.change(input, { target: { value: "NSE_INDEX:FINNIFTY" } });
    const addBtn = screen.getByTestId("ticker-add-symbol-btn");
    fireEvent.click(addBtn);
    expect(mockSetTickerSymbols).toHaveBeenCalledWith([
      "NSE_INDEX:NIFTY",
      "BSE_INDEX:SENSEX",
      "NSE_INDEX:FINNIFTY",
    ]);
  });

  it("does not add a duplicate symbol", () => {
    renderTickerSettings();
    const input = screen.getByTestId("ticker-symbol-search");
    // Type an already-present symbol in direct format
    fireEvent.change(input, { target: { value: "NSE_INDEX:NIFTY" } });
    const addBtn = screen.getByTestId("ticker-add-symbol-btn");
    fireEvent.click(addBtn);
    // setTickerSymbols should NOT be called (handleAdd returns early)
    expect(mockSetTickerSymbols).not.toHaveBeenCalled();
  });

  it("renders the display mode label", () => {
    renderTickerSettings();
    expect(screen.getByText("Display Mode")).toBeInTheDocument();
  });

  it("renders the scroll duration label when in marquee mode", () => {
    renderTickerSettings();
    expect(screen.getByText("Scroll Duration")).toBeInTheDocument();
  });
});
