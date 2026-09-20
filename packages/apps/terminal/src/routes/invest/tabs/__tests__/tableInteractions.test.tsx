import type { HTMLAttributes } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StockFundamentals } from "@/hooks/useStockScan";

vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
}));

vi.mock("@/components/data/CompanySnapshot", () => ({
  CompanySnapshot: ({ data }: { data: StockFundamentals }) => (
    <section aria-label="Selected company">{data.name}</section>
  ),
}));

vi.mock("@/hooks/useStockScan", () => ({
  useStockScan: () => ({
    data: {
      stocks: [
        {
          symbol: "ALPHA", name: "Alpha Industries", exchange: "NSE", market_cap: 2,
          pe_ratio: 10, pb_ratio: 2, roe: 12, roce: 14, dividend_yield: 1, sector: "Industrials",
        },
        {
          symbol: "BETA", name: "Beta Industries", exchange: "NSE", market_cap: 10,
          pe_ratio: 20, pb_ratio: 3, roe: 15, roce: 18, dividend_yield: 2, sector: "Industrials",
        },
      ] satisfies StockFundamentals[],
      sectors: ["Industrials"],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

import { IpoTab } from "../IpoTab";
import { StocksTab } from "../StocksTab";

describe("investment table interactions", () => {
  it("preserves numeric IPO gain sorting in both directions", () => {
    render(<IpoTab />);
    const table = screen.getByRole("table", { name: /recent indian ipos/i });
    const bodyRows = () => within(table).getAllByRole("row").slice(1);
    const gainHeader = within(table).getByRole("columnheader", { name: /listing gain/i });

    fireEvent.click(gainHeader);
    expect(gainHeader).toHaveAttribute("aria-sort", "descending");
    expect(bodyRows()[0]).toHaveTextContent("Unimech Aerospace");
    expect(bodyRows().at(-1)).toHaveTextContent("Carraro India");

    fireEvent.click(gainHeader);
    expect(gainHeader).toHaveAttribute("aria-sort", "ascending");
    expect(bodyRows()[0]).toHaveTextContent("Carraro India");
    expect(bodyRows().at(-1)).toHaveTextContent("Unimech Aerospace");
  });

  it("keeps the selected company attached to its row after sorting", () => {
    render(<StocksTab />);
    const table = screen.getByRole("table", { name: /stock fundamentals screener/i });
    const firstBodyRow = () => within(table).getAllByRole("row")[1];
    expect(firstBodyRow()).toHaveTextContent("Beta Industries");

    fireEvent.click(firstBodyRow());
    expect(screen.getByRole("region", { name: "Selected company" })).toHaveTextContent("Beta Industries");

    fireEvent.click(within(table).getByRole("columnheader", { name: /mkt cap/i }));
    expect(firstBodyRow()).toHaveTextContent("Alpha Industries");
    expect(screen.getByRole("region", { name: "Selected company" })).toHaveTextContent("Beta Industries");

    fireEvent.click(firstBodyRow());
    expect(screen.getByRole("region", { name: "Selected company" })).toHaveTextContent("Alpha Industries");
    fireEvent.click(screen.getByRole("button", { name: "Close company snapshot" }));
    expect(screen.queryByRole("region", { name: "Selected company" })).not.toBeInTheDocument();
  });
});
