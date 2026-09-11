/**
 * Payoff tab summary cards — analytical max profit / loss / breakeven.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PayoffTab } from "../PayoffTab";
import { UNDERLYINGS, type Leg } from "../types";

const nifty = UNDERLYINGS[0];

function callLeg(premium: number | null, extra: Partial<Leg> = {}): Leg {
  return {
    id: "long-call",
    action: "BUY",
    optionType: "CE",
    strike: 22500,
    lots: 1,
    premium,
    ...extra,
  };
}

describe("PayoffTab", () => {
  it("shows em-dash cards and does not model payoff when premium is unset (FT-LAB-003)", () => {
    render(<PayoffTab legs={[callLeg(null)]} atm={22500} underlying={nifty} />);

    expect(screen.getByText("Max Profit").nextElementSibling).toHaveTextContent("—");
    expect(screen.getByText("Max Loss").nextElementSibling).toHaveTextContent("—");
    expect(screen.getByText("Net Premium").nextElementSibling).toHaveTextContent("—");
    expect(screen.getByText("BEP(s)").nextElementSibling).toHaveTextContent("—");
    expect(screen.getByText("Enter premium to model payoff")).toBeInTheDocument();
    expect(screen.queryByText("₹0.00")).not.toBeInTheDocument();
    expect(screen.queryByText("Unlimited")).not.toBeInTheDocument();
  });

  it("shows unbounded profit, zero max loss, and a free-cost warning for an explicit ₹0 long call", () => {
    render(<PayoffTab legs={[callLeg(0)]} atm={22500} underlying={nifty} />);

    expect(screen.getByText("Max Profit").nextElementSibling).toHaveTextContent("Unlimited");
    expect(screen.getByText("Max Loss").nextElementSibling).toHaveTextContent("₹0.00");
    expect(screen.getByText("BEP(s)").nextElementSibling).toHaveTextContent("22500");
    expect(screen.getByText("Premium is ₹0 — payoff treats cost as free")).toBeInTheDocument();
    expect(screen.queryByText("₹2,53,125.00")).not.toBeInTheDocument();
    expect(screen.queryByText("None")).not.toBeInTheDocument();
  });

  it("labels a sample-chain premium and still uses FT-LAB-001 max-loss maths", () => {
    render(
      <PayoffTab
        legs={[callLeg(45, { premiumSource: "sample" })]}
        atm={22500}
        underlying={nifty}
      />,
    );

    expect(screen.getByText("Sample premium — edit to model")).toBeInTheDocument();
    expect(screen.getByText("Max Profit").nextElementSibling).toHaveTextContent("Unlimited");
    expect(screen.getByText("Max Loss").nextElementSibling).toHaveTextContent("-₹3,375.00");
    expect(screen.getByText("BEP(s)").nextElementSibling).toHaveTextContent("22545");
  });

  it("keeps paid-premium long calls unbounded with max loss equal to the premium paid", () => {
    render(<PayoffTab legs={[callLeg(180)]} atm={22500} underlying={nifty} />);

    expect(screen.getByText("Max Profit").nextElementSibling).toHaveTextContent("Unlimited");
    expect(screen.getByText("Max Loss").nextElementSibling).toHaveTextContent("-₹13,500.00");
    expect(screen.getByText("BEP(s)").nextElementSibling).toHaveTextContent("22680");
  });
});
