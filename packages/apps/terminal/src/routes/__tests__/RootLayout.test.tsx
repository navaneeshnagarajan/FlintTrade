/**
 * RootLayout.test.tsx
 *
 * Smoke tests for the root layout wrapper.
 * Verifies that Outlet content is rendered and global overlays are present.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-router-dom", () => ({
  Outlet: () => <div data-testid="outlet-content">Child Route</div>,
  useLocation: () => ({ pathname: "/trade" }),
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ applyTheme: vi.fn() }),
  ),
}));

vi.mock("@/components/help/AITutorPill", () => ({
  AITutorPill: () => <div data-testid="ai-tutor-pill" />,
}));

vi.mock("@/components/help/UpgradeSuggestion", () => ({
  UpgradeSuggestionHost: () => <div data-testid="upgrade-suggestion" />,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import RootLayout from "../RootLayout";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RootLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders children via Outlet", () => {
    render(<RootLayout />);

    expect(screen.getByTestId("outlet-content")).toBeInTheDocument();
    expect(screen.getByText("Child Route")).toBeInTheDocument();
  });

  it("renders global overlay components (AITutorPill, UpgradeSuggestionHost)", () => {
    render(<RootLayout />);

    expect(screen.getByTestId("ai-tutor-pill")).toBeInTheDocument();
    expect(screen.getByTestId("upgrade-suggestion")).toBeInTheDocument();
  });
});
