import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ConnectionSection } from "../ConnectionSection";
import { AboutSection } from "../AboutSection";
vi.mock("@/components/account/OpenAlgoConnectionForm", () => ({
  OpenAlgoConnectionForm: () => <div>Connection editor</div>,
}));
vi.mock("@/layout/widgetFactory", () => ({ widgetCatalog: [] }));
describe("Settings presentation", () => {
  it("keeps the bridge editor without a second onboarding shortcut", () => {
    render(<ConnectionSection settings={{ host: "", port: "5000", wsPort: "8765", apiKeyConfigured: false, apiKeyLast4: "" }} onSaved={vi.fn()} />);
    expect(screen.getByText("Connection editor")).toBeVisible();
    expect(screen.getByRole("heading", { name: "OpenAlgo bridge" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /setup wizard/i })).not.toBeInTheDocument();
  });
  it("describes the operator workflow without internal architecture copy", () => {
    render(<AboutSection />);
    expect(screen.getByText(/research markets, practise strategies/i)).toBeVisible();
    expect(screen.queryByText(/monorepo with|native gateway contract/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /GNU AGPL/i })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Runtime and dependency versions" })).toBeVisible();
  });
});
