import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { BrokerSummary } from "../BrokerSummary";

describe("Broker account snapshot summary", () => {
  it("does not claim a read connection for an empty snapshot", () => {
    render(<BrokerSummary connectedAccounts={0} />);
    expect(screen.getByText("No connected broker accounts are listed.")).toBeVisible();
    expect(screen.queryByText(/Connected \(read\)|API smoke/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Connecting an account does not enable live orders/)).toBeVisible();
  });

  it.each([[1, "1 connected broker account is listed."], [2, "2 connected broker accounts are listed."]] as const)(
    "describes the existing snapshot count %s without making an execution-readiness claim", (count, copy) => {
      render(<BrokerSummary connectedAccounts={count} />);
      expect(screen.getByText(copy)).toBeVisible();
      expect(screen.queryByText(/live orders are enabled/i)).not.toBeInTheDocument();
    },
  );
});
