import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ------------------------------------------------------------------
// Module-level mocks — declared before any imports of the component
// ------------------------------------------------------------------

const mockUseSymbolSearch = vi.fn();

vi.mock("../useSymbolSearch", () => ({
  useSymbolSearch: (...args: unknown[]) => mockUseSymbolSearch(...args),
}));

vi.mock("jotai", () => ({
  useAtomValue: vi.fn().mockReturnValue(null),
}));

vi.mock("@/atoms/marketAtoms", () => ({
  tickAtomFamily: vi.fn().mockReturnValue({}),
}));

// Component import AFTER mocks are in place
import { SymbolSearchTab } from "../SymbolSearchTab";

// ------------------------------------------------------------------
// Default result fixture
// ------------------------------------------------------------------

const TWO_RESULTS = [
  { symbol: "RELIANCE", exchange: "NSE" },
  { symbol: "RELIANCEPP", exchange: "NSE" },
];

describe("SymbolSearchTab", () => {
  beforeEach(() => {
    // Default: return two results for any query
    mockUseSymbolSearch.mockReturnValue({ results: TWO_RESULTS, isLoading: false });
  });

  // ----------------------------------------------------------------
  // Renders search results
  // ----------------------------------------------------------------

  it("renders search results with symbol and exchange", () => {
    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("RELIANCEPP")).toBeInTheDocument();
    expect(screen.getAllByText("NSE")).toHaveLength(2);
  });

  // ----------------------------------------------------------------
  // Empty / short query
  // ----------------------------------------------------------------

  it("shows empty prompt when query is empty", () => {
    mockUseSymbolSearch.mockReturnValue({ results: [], isLoading: false });

    render(
      <SymbolSearchTab
        query=""
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/type to search/i)).toBeInTheDocument();
  });

  it("shows empty prompt when query is a single character", () => {
    mockUseSymbolSearch.mockReturnValue({ results: [], isLoading: false });

    render(
      <SymbolSearchTab
        query="R"
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/type to search/i)).toBeInTheDocument();
  });

  // ----------------------------------------------------------------
  // Loading state
  // ----------------------------------------------------------------

  it("shows loading indicator while fetching", () => {
    mockUseSymbolSearch.mockReturnValue({ results: [], isLoading: true });

    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/searching/i)).toBeInTheDocument();
  });

  // ----------------------------------------------------------------
  // No results
  // ----------------------------------------------------------------

  it("shows no-results message when results are empty for a valid query", () => {
    mockUseSymbolSearch.mockReturnValue({ results: [], isLoading: false });

    render(
      <SymbolSearchTab
        query="XYZ"
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/no symbols match/i)).toBeInTheDocument();
    expect(screen.getByText(/XYZ/)).toBeInTheDocument();
  });

  // ----------------------------------------------------------------
  // Row click → chart action
  // ----------------------------------------------------------------

  it("calls onSelectSymbol with chart action on row click", () => {
    const onSelect = vi.fn();
    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={0}
        onSelectSymbol={onSelect}
        onActiveIndexChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("RELIANCE"));
    expect(onSelect).toHaveBeenCalledWith("RELIANCE", "NSE", "chart");
  });

  // ----------------------------------------------------------------
  // Quick action buttons on active row
  // ----------------------------------------------------------------

  it("shows quick action buttons on the active row", () => {
    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    // Use exact label to avoid matching RELIANCEPP buttons as well
    expect(screen.getByLabelText("Open RELIANCE chart")).toBeInTheDocument();
    expect(screen.getByLabelText("Buy RELIANCE")).toBeInTheDocument();
    expect(screen.getByLabelText("Ask AI about RELIANCE")).toBeInTheDocument();
  });

  it("quick action chart button calls onSelectSymbol with chart action", () => {
    const onSelect = vi.fn();
    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={0}
        onSelectSymbol={onSelect}
        onActiveIndexChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByLabelText("Open RELIANCE chart"));
    expect(onSelect).toHaveBeenCalledWith("RELIANCE", "NSE", "chart");
  });

  it("quick action buy button calls onSelectSymbol with buy action", () => {
    const onSelect = vi.fn();
    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={0}
        onSelectSymbol={onSelect}
        onActiveIndexChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByLabelText("Buy RELIANCE"));
    expect(onSelect).toHaveBeenCalledWith("RELIANCE", "NSE", "buy");
  });

  it("quick action AI button calls onSelectSymbol with ai action", () => {
    const onSelect = vi.fn();
    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={0}
        onSelectSymbol={onSelect}
        onActiveIndexChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByLabelText("Ask AI about RELIANCE"));
    expect(onSelect).toHaveBeenCalledWith("RELIANCE", "NSE", "ai");
  });

  // ----------------------------------------------------------------
  // Mouse hover triggers onActiveIndexChange
  // ----------------------------------------------------------------

  it("calls onActiveIndexChange on row mouse enter", () => {
    const onIndexChange = vi.fn();
    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={onIndexChange}
      />,
    );
    // Hover over the second result (RELIANCEPP at index 1)
    const options = screen.getAllByRole("option");
    fireEvent.mouseEnter(options[1]);
    expect(onIndexChange).toHaveBeenCalledWith(1);
  });

  // ----------------------------------------------------------------
  // ARIA attributes
  // ----------------------------------------------------------------

  it("renders a listbox with correct aria-selected on active row", () => {
    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={1}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "false");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
  });

  it("passes the query string to useSymbolSearch", () => {
    render(
      <SymbolSearchTab
        query="INFY"
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(mockUseSymbolSearch).toHaveBeenCalledWith("INFY");
  });
});
