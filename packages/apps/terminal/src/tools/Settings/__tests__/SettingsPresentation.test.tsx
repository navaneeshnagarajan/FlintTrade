import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { BrokerSummary } from "../BrokerSummary";
import { AboutSection } from "../AboutSection";
vi.mock("@/layout/widgetFactory", () => ({ widgetCatalog: [] }));
describe("Settings presentation", () => {
  it("describes the loaded broker snapshot without claiming connection enables orders", () => {
    render(<BrokerSummary connectedAccounts={0} />);
    expect(screen.getByText("No connected broker accounts are listed.")).toBeVisible();
    expect(screen.getByText(/connecting an account does not enable live orders/i)).toBeVisible();
  });
  it("describes the operator workflow without internal architecture copy", () => {
    render(<AboutSection />);
    expect(screen.getByText(/research markets, practise strategies/i)).toBeVisible();
    expect(screen.queryByText(/monorepo with|native gateway contract/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /GNU AGPL/i })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Runtime and dependency versions" })).toBeVisible();
  });
});
