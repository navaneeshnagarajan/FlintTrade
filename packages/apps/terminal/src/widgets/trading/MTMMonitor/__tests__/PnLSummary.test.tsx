import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it, vi } from "vitest";

import { PnLSummary } from "../PnLSummary";

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

vi.mock("@/services/ftApi", () => ({
  getPnLTracker: vi.fn().mockResolvedValue([
    { timestamp: 1, realized_pnl: 100, unrealized_pnl: 50, total_pnl: 150, trade_count: 1 },
    { timestamp: 2, realized_pnl: 120, unrealized_pnl: 20, total_pnl: 140, trade_count: 2 },
    { timestamp: 3, realized_pnl: 180, unrealized_pnl: 40, total_pnl: 220, trade_count: 3 },
  ]),
  getPnLSummary: vi.fn().mockResolvedValue({
    realized: 180,
    unrealized: 40,
    total: 220,
    max_total: 220,
    min_total: 100,
    trade_count: 3,
    data_points: 3,
  }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("PnLSummary", () => {
  it("renders realized P&L trend through the shared Flint primitive", async () => {
    render(<PnLSummary />, { wrapper });

    expect(await screen.findByText("P&L Tracker")).toBeInTheDocument();
    const sparkline = screen.getByRole("img", { name: "Realized P&L tracker trend" });
    expect(sparkline).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparkline.querySelector("polyline")).not.toBeInTheDocument();
    expect(sparkline.querySelectorAll("path").length).toBeGreaterThan(0);
  });
});
