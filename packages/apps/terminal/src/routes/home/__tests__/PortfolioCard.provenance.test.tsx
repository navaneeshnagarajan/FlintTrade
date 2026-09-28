/**
 * PortfolioCard — Allocation always shows an inline Sample provenance badge
 * (illustrative mix), independent of Explore/Live mode. Hooks/query behaviour unchanged.
 */
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const fundsQuery = vi.hoisted(() => ({
  data: undefined as { availableCash: number; usedMargin: number; totalBalance: number } | undefined,
}));

vi.mock("@/hooks/useFunds", () => ({ useFunds: () => ({ data: fundsQuery.data }) }));
vi.mock("@/hooks/useHoldings", () => ({ useHoldings: () => ({ data: undefined }) }));
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => true,
}));

import { useModeStore } from "@/stores/modeStore";
import { PortfolioCard } from "../PortfolioCard";

afterEach(() => {
  fundsQuery.data = undefined;
  useModeStore.setState({ mode: "live" });
});

describe("PortfolioCard allocation provenance (Slice 3)", () => {
  it("Allocation heading has inline visible Sample badge with data-provenance=Sample", () => {
    useModeStore.setState({ mode: "live" });
    render(<PortfolioCard />);

    expect(screen.getByText("Allocation")).toBeInTheDocument();
    expect(screen.getByTestId("allocation-example-label")).toHaveTextContent("Example");
    expect(screen.queryByText("Sample")).not.toBeInTheDocument();
    expect(screen.queryByTestId("portfolio-net-worth-example")).not.toBeInTheDocument();
  });

  it("uses the practice cash balance as the only net worth figure", () => {
    fundsQuery.data = { availableCash: 999_200, usedMargin: 800, totalBalance: 1_000_000 };
    useModeStore.setState({ mode: "practice" });
    render(<PortfolioCard />);

    expect(screen.getByTestId("portfolio-net-worth")).toHaveAttribute("data-value", "999200");
    expect(screen.queryByTestId("portfolio-net-worth-example")).not.toBeInTheDocument();
    expect(screen.getByTestId("allocation-example-label")).toHaveTextContent("Example");
  });
});
