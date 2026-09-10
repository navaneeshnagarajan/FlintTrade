/**
 * Payoff tab summary cards — analytical max profit / loss / breakeven.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PayoffTab } from "../PayoffTab";
import { UNDERLYINGS, type Leg } from "../types";

const nifty = UNDERLYINGS[0];

function callLeg(premium: number): Leg {
  return {
    id: "long-call",
    action: "BUY",
    optionType: "CE",
    strike: 22500,
    lots: 1,
    premium,
  };
}

describe("PayoffTab", () => {
  it("shows unbounded profit, zero max loss, and strike breakeven for a zero-premium long call", () => {
    render(<PayoffTab legs={[callLeg(0)]} atm={22500} underlying={nifty} />);

    expect(screen.getByText("Max Profit").nextElementSibling).toHaveTextContent("Unlimited");
    expect(screen.getByText("Max Loss").nextElementSibling).toHaveTextContent("₹0.00");
    expect(screen.getByText("BEP(s)").nextElementSibling).toHaveTextContent("22500");
    expect(screen.queryByText("₹2,53,125.00")).not.toBeInTheDocument();
    expect(screen.queryByText("None")).not.toBeInTheDocument();
  });

  it("keeps paid-premium long calls unbounded with max loss equal to the premium paid", () => {
    render(<PayoffTab legs={[callLeg(180)]} atm={22500} underlying={nifty} />);

    expect(screen.getByText("Max Profit").nextElementSibling).toHaveTextContent("Unlimited");
    expect(screen.getByText("Max Loss").nextElementSibling).toHaveTextContent("-₹13,500.00");
    expect(screen.getByText("BEP(s)").nextElementSibling).toHaveTextContent("22680");
  });
});
