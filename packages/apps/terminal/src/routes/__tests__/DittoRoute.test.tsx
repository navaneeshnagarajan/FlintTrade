import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DittoRoute from "../DittoRoute";
vi.mock("@/components/account/AccountStatusPanel", () => ({ AccountStatusPanel: () => <div>Native account status</div> }));
vi.mock("@/components/account/BrokerRateLimitsPanel", () => ({ BrokerRateLimitsPanel: () => <div>Native rate limits</div> }));
describe("Ditto transport retirement", () => {
  it("explains unavailable mirroring while preserving native session awareness", () => {
    render(<DittoRoute />);
    expect(screen.getByRole("status")).toHaveTextContent("Position mirroring and account-level Ditto risk controls are unavailable");
    expect(screen.getByText("Native account status")).toBeInTheDocument();
    expect(screen.getByText("Native rate limits")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add account|start mirror|kill all/i })).not.toBeInTheDocument();
  });
});
