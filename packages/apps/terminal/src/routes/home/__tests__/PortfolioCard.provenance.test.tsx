/**
 * PortfolioCard — Allocation always shows an inline Sample provenance badge
 * (illustrative mix), independent of Explore/Live mode. Hooks/query behaviour unchanged.
 */
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useFunds", () => ({ useFunds: () => ({ data: undefined }) }));
vi.mock("@/hooks/useHoldings", () => ({ useHoldings: () => ({ data: undefined }) }));
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => false,
}));

import { useModeStore } from "@/stores/modeStore";
import { PortfolioCard } from "../PortfolioCard";

afterEach(() => {
  useModeStore.setState({ mode: "live" });
});

describe("PortfolioCard allocation provenance (Slice 3)", () => {
  it("Allocation heading has inline visible Sample badge with data-provenance=Sample", () => {
    useModeStore.setState({ mode: "live" });
    render(<PortfolioCard />);

    expect(screen.getByText("Allocation")).toBeInTheDocument();
    const badge = screen.getByTestId("provenance-badge-inline");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Sample");
    expect(badge).toHaveAttribute("data-provenance", "Sample");
    expect(badge.className).not.toMatch(/\babsolute\b/);
    expect(badge).not.toHaveAttribute("role", "status");
    expect(badge).not.toHaveAttribute("aria-live");
  });
});
