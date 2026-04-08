/**
 * SipTab.test.tsx — Render tests for the SIP calculator tab.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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

// DisabledActionButton
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
  it("renders the SIP calculator heading and inputs", () => {
    render(<SipTab />);
    // "SIP" is wrapped in a GlossaryTooltip span, so text is split across elements
    expect(screen.getByText(/Calculator/)).toBeInTheDocument();
    expect(screen.getByText("Monthly SIP (INR)")).toBeInTheDocument();
    expect(screen.getByText("Expected Return (%/yr)")).toBeInTheDocument();
    expect(screen.getByText("Duration (years)")).toBeInTheDocument();
  });

  it("displays default calculation results", () => {
    render(<SipTab />);
    // Default values are 5000/month, 12%/yr, 10 years — should show results
    expect(screen.getByText("Total Invested")).toBeInTheDocument();
    expect(screen.getByText("Est. Returns")).toBeInTheDocument();
    expect(screen.getByText("Maturity Value")).toBeInTheDocument();
  });
});
