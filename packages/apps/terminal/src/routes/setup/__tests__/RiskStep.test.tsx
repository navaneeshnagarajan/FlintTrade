import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it, vi } from "vitest";

import { RiskStep } from "../RiskStep";

describe("RiskStep", () => {
  it("presents lot and order-rate values as local references, not enforced limits", () => {
    render(<RiskStep onComplete={vi.fn()} />);

    expect(screen.getByLabelText("Position lot reference")).toBeInTheDocument();
    expect(screen.getByLabelText("Order-rate reference per minute")).toBeInTheDocument();
    expect(screen.getByText(/stored locally for terminal reference/i)).toBeInTheDocument();
    expect(screen.getByText(/not backend or broker enforcement/i)).toBeInTheDocument();
    expect(screen.queryByText(/enforced by the safety engine/i)).not.toBeInTheDocument();
  });
});
