import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ConnectionStep } from "./ConnectionStep";

let _nativeAccounts: Array<{ has_session?: boolean }> = [];

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: _nativeAccounts, isLoading: false, isError: false }),
}));

vi.mock("@/components/account/BrokerConnect", () => ({
  BrokerConnect: () => <div>Native brokers section</div>,
}));

vi.mock("@/services/ftApi.native", () => ({
  listNativeAccounts: vi.fn(),
}));

describe("ConnectionStep", () => {
  beforeEach(() => {
    _nativeAccounts = [];
  });

  it("defaults to FlintTrade's direct broker gateway", () => {
    render(<ConnectionStep onComplete={vi.fn()} />);

    expect(screen.getByRole("button", { name: /flinttrade gateway/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(/No separate OpenAlgo setup needed/i)).toBeInTheDocument();
    expect(screen.getByText("Native brokers section")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /connect at least one broker/i })).toBeDisabled();
  });

  it("allows continuing when a native broker has a live session", () => {
    _nativeAccounts = [{ has_session: true }];

    render(<ConnectionStep onComplete={vi.fn()} />);

    expect(screen.getByRole("button", { name: /^continue$/i })).toBeEnabled();
  });
});
