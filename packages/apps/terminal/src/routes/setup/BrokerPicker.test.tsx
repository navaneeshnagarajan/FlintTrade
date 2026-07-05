import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { BrokerPicker } from "./BrokerPicker";

vi.mock("@/components/account/BrokerConnect", () => ({
  BrokerConnect: () => <div data-testid="unified-broker-connect">Unified broker connect</div>,
}));

describe("BrokerPicker", () => {
  it("routes the retired setup picker through the unified broker connect surface", () => {
    render(<BrokerPicker onSelect={vi.fn()} />);

    expect(screen.getByTestId("unified-broker-connect")).toHaveTextContent("Unified broker connect");
  });
});
