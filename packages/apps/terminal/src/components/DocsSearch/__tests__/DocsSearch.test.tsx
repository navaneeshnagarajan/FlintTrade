/**
 * DocsSearch.test.tsx
 *
 * Tests for the in-app documentation search modal:
 *  - Renders when open, hidden when closed
 *  - Shows empty state before query
 *  - Shows loading indicator during search
 *  - Renders search results from API
 *  - No-results state
 *  - Keyboard navigation (ArrowDown/Up, Enter, Escape)
 *  - Calls onSelectDoc callback on selection
 *  - Clears query via clear button
 *  - searchDocs helper handles fetch errors gracefully
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockFetch = vi.fn();
global.fetch = mockFetch;

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({
    open,
    children,
  }: { open: boolean; children: React.ReactNode }) =>
    open ? <div data-testid="dialog">{children}</div> : null,
  DialogContent: ({
    children,
    ...rest
  }: { children: React.ReactNode; [key: string]: unknown }) => (
    <div data-testid="dialog-content" {...rest}>
      {children}
    </div>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DialogTitle: ({ children }: { children: React.ReactNode }) => (
    <h2>{children}</h2>
  ),
}));

vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input {...props} />
  ),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import DocsSearch, { searchDocs, type DocSearchResult } from "../DocsSearch";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_RESULTS: DocSearchResult[] = [
  {
    path: "guides/order-placement.md",
    title: "Order Placement Guide",
    snippet: "FlintTrade supports market, limit, and stop orders via OpenAlgo.",
    score: 0.95,
  },
  {
    path: "concepts/backtesting.md",
    title: "Backtesting Concepts",
    snippet: "Run historical simulations against OHLCV data with vectorised backtest engine.",
    score: 0.72,
  },
];

function mockFetchResults(results: DocSearchResult[] = MOCK_RESULTS) {
  mockFetch.mockResolvedValue({
    ok: true,
    json: async () => ({ query: "order", results, total: results.length }),
  } as Response);
}

const WAIT_OPTS = { timeout: 3000 };

// ---------------------------------------------------------------------------
// Component tests
// ---------------------------------------------------------------------------

describe("DocsSearch", () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
  };

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe("visibility", () => {
    it("renders dialog when isOpen is true", () => {
      render(<DocsSearch {...defaultProps} />);
      expect(screen.getByTestId("dialog")).toBeInTheDocument();
    });

    it("does not render when isOpen is false", () => {
      render(<DocsSearch {...defaultProps} isOpen={false} />);
      expect(screen.queryByTestId("dialog")).not.toBeInTheDocument();
    });

    it("shows dialog title", () => {
      render(<DocsSearch {...defaultProps} />);
      expect(screen.getByText("Search Docs")).toBeInTheDocument();
    });
  });

  describe("empty state", () => {
    it("shows empty state hint before any query", () => {
      render(<DocsSearch {...defaultProps} />);
      expect(screen.getByText(/type to search/i)).toBeInTheDocument();
    });

    it("shows no-results state when API returns empty", async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({ query: "xyz", results: [], total: 0 }),
      } as Response);

      render(<DocsSearch {...defaultProps} />);
      const input = screen.getByRole("combobox");
      fireEvent.change(input, { target: { value: "xyz" } });

      await waitFor(
        () => expect(screen.getByText(/no docs found/i)).toBeInTheDocument(),
        WAIT_OPTS,
      );
    });
  });

  describe("search and results", () => {
    it("renders results after query", async () => {
      mockFetchResults();
      render(<DocsSearch {...defaultProps} />);
      const input = screen.getByRole("combobox");
      fireEvent.change(input, { target: { value: "order" } });

      await waitFor(
        () => expect(screen.getByText("Order Placement Guide")).toBeInTheDocument(),
        WAIT_OPTS,
      );
      expect(screen.getByText("Backtesting Concepts")).toBeInTheDocument();
    });

    it("shows result count in footer", async () => {
      mockFetchResults();
      render(<DocsSearch {...defaultProps} />);
      const input = screen.getByRole("combobox");
      fireEvent.change(input, { target: { value: "order" } });

      await waitFor(
        () => expect(screen.getByText(/2 results/i)).toBeInTheDocument(),
        WAIT_OPTS,
      );
    });

    it("renders file path for each result", async () => {
      mockFetchResults();
      render(<DocsSearch {...defaultProps} />);
      const input = screen.getByRole("combobox");
      fireEvent.change(input, { target: { value: "order" } });

      await waitFor(
        () => expect(screen.getByText(/guides\/order-placement\.md/)).toBeInTheDocument(),
        WAIT_OPTS,
      );
    });
  });

  describe("keyboard navigation", () => {
    it("navigates down with ArrowDown", async () => {
      mockFetchResults();
      render(<DocsSearch {...defaultProps} />);
      const input = screen.getByRole("combobox");
      fireEvent.change(input, { target: { value: "order" } });

      await waitFor(() => screen.getByText("Order Placement Guide"), WAIT_OPTS);

      const options = screen.getAllByRole("option");
      expect(options[0]).toHaveAttribute("aria-selected", "true");

      fireEvent.keyDown(input, { key: "ArrowDown" });
      expect(options[1]).toHaveAttribute("aria-selected", "true");
    });

    it("selects result with Enter key", async () => {
      const onSelectDoc = vi.fn();
      mockFetchResults();
      render(<DocsSearch {...defaultProps} onSelectDoc={onSelectDoc} />);
      const input = screen.getByRole("combobox");
      fireEvent.change(input, { target: { value: "order" } });

      await waitFor(() => screen.getByText("Order Placement Guide"), WAIT_OPTS);

      fireEvent.keyDown(input, { key: "Enter" });
      expect(onSelectDoc).toHaveBeenCalledWith(MOCK_RESULTS[0]);
    });

    it("closes on Escape key", () => {
      const onClose = vi.fn();
      render(<DocsSearch {...defaultProps} onClose={onClose} />);
      const input = screen.getByRole("combobox");
      fireEvent.keyDown(input, { key: "Escape" });
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe("clear button", () => {
    it("clears query when clear button is clicked", async () => {
      mockFetchResults();
      render(<DocsSearch {...defaultProps} />);
      const input = screen.getByRole("combobox");
      fireEvent.change(input, { target: { value: "order" } });

      await waitFor(() => screen.getByLabelText(/clear search/i), WAIT_OPTS);
      fireEvent.click(screen.getByLabelText(/clear search/i));

      expect(input).toHaveValue("");
      expect(screen.getByText(/type to search/i)).toBeInTheDocument();
    });
  });

  describe("accessibility", () => {
    it("input has role combobox with aria-label", () => {
      render(<DocsSearch {...defaultProps} />);
      expect(
        screen.getByRole("combobox", { name: /search documentation/i }),
      ).toBeInTheDocument();
    });

    it("results list has role listbox", async () => {
      mockFetchResults();
      render(<DocsSearch {...defaultProps} />);
      const input = screen.getByRole("combobox");
      fireEvent.change(input, { target: { value: "order" } });

      await waitFor(
        () => expect(screen.getByRole("listbox")).toBeInTheDocument(),
        WAIT_OPTS,
      );
    });
  });
});

// ---------------------------------------------------------------------------
// searchDocs helper tests
// ---------------------------------------------------------------------------

describe("searchDocs", () => {
  afterEach(() => vi.clearAllMocks());

  it("returns empty array for empty query", async () => {
    const result = await searchDocs("");
    expect(result).toEqual([]);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("returns results on success", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ results: MOCK_RESULTS, total: 2, query: "order" }),
    } as Response);
    const result = await searchDocs("order");
    expect(result).toHaveLength(2);
  });

  it("returns empty array on non-ok response", async () => {
    mockFetch.mockResolvedValue({ ok: false } as Response);
    const result = await searchDocs("order");
    expect(result).toEqual([]);
  });

  it("returns empty array on network error", async () => {
    mockFetch.mockRejectedValue(new Error("Network failure"));
    const result = await searchDocs("order");
    expect(result).toEqual([]);
  });
});
