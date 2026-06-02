/**
 * SipTab.test.tsx — Render tests for the enhanced SIP calculator tab.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({
        glass: { enabled: false, blur: 12, transparency: 20 },
        activeThemeId: "graphite",
        mode: "dark",
        customThemes: [],
        getActiveTheme: () => ({
          id: "graphite",
          name: "Graphite",
          dark: { colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" }, glass: { blur: 12, minOpacity: 0.8 } },
          light: { colors: { card: "#ffffff", border: "#e5e7eb", cardHover: "#f9fafb" }, glass: { blur: 12, minOpacity: 0.8 } },
        }),
        getResolvedMode: () => "dark",
      }),
    { getState: () => ({ glass: { enabled: false } }) },
  ),
}));

vi.mock("@/lib/cinematicThemes", () => ({
  getResolvedVariant: () => ({
    colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
    glass: { blur: 12, minOpacity: 0.8 },
  }),
}));

vi.mock("@/components/ui/GlossaryTooltip", () => ({
  GlossaryTooltip: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("@/components/motion/StaggeredList", () => ({
  StaggeredList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../../DisabledActionButton", () => ({
  DisabledActionButton: ({ label }: { label: string }) => (
    <button disabled>{label}</button>
  ),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { SipTab } from "../SipTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SipTab", () => {
  it("renders the SIP calculator heading", () => {
    render(<SipTab />);
    expect(screen.getByText(/Calculator/)).toBeInTheDocument();
  });

  it("renders all input fields", () => {
    render(<SipTab />);
    expect(screen.getByLabelText("SIP amount in rupees")).toBeInTheDocument();
    expect(screen.getByLabelText(/investment duration in years/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/annual step-up percentage/i)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /select sip frequency/i })).toBeInTheDocument();
  });

  it("displays three scenario comparison at default values", () => {
    render(<SipTab />);
    expect(screen.getByText("Projected Wealth — 3 Scenarios")).toBeInTheDocument();
    expect(screen.getByText("8%")).toBeInTheDocument();
    expect(screen.getByText("10%")).toBeInTheDocument();
    expect(screen.getByText("12%")).toBeInTheDocument();
  });

  it("displays detail result cards at 10% scenario", () => {
    render(<SipTab />);
    expect(screen.getByText("Total Invested")).toBeInTheDocument();
    expect(screen.getByText("Est. Returns (10%)")).toBeInTheDocument();
    expect(screen.getByText("Maturity Value")).toBeInTheDocument();
  });

  it("renders the Start SIP button (disabled — NAV not connected)", () => {
    render(<SipTab />);
    const btn = screen.getByRole("button", { name: /start sip/i });
    expect(btn).toBeDisabled();
  });

  it("renders the Add SIP button (disabled)", () => {
    render(<SipTab />);
    const addBtn = screen.getByRole("button", { name: /add sip/i });
    expect(addBtn).toBeDisabled();
  });

  it("shows wealth ratio text", () => {
    render(<SipTab />);
    expect(screen.getByText(/wealth ratio/i)).toBeInTheDocument();
  });

  it("renders the 10% wealth mix using the shared stacked bar primitive", () => {
    render(<SipTab />);
    expect(screen.getByRole("img", { name: /sip wealth breakdown/i })).toHaveAttribute(
      "data-flint-chart",
      "stacked-bar",
    );
  });

  it("step-up hint appears when step-up is set > 0", () => {
    render(<SipTab />);
    const stepUpInput = screen.getByLabelText(/annual step-up/i);
    fireEvent.change(stepUpInput, { target: { value: "10" } });
    expect(screen.getByText(/SIP grows 10% each year/i)).toBeInTheDocument();
  });

  it("renders active SIPs tracker section", () => {
    render(<SipTab />);
    expect(screen.getByText("Active SIPs")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /active sips/i })).toBeInTheDocument();
  });
});
