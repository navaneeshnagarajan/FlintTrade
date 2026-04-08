/**
 * AppLayout.test.tsx
 *
 * Smoke tests for the shared app chrome layout.
 * Verifies header/main landmarks, mode banners, and child Outlet rendering.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router-dom", () => ({
  Outlet: () => <div data-testid="outlet-content">Page Content</div>,
  useLocation: () => ({ pathname: "/trade" }),
  useNavigate: () => mockNavigate,
}));

vi.mock("@/chrome/TopBar", () => ({
  default: () => <div data-testid="topbar">TopBar</div>,
}));

vi.mock("@/chrome/TickerBar", () => ({
  default: () => <div data-testid="tickerbar">TickerBar</div>,
}));

vi.mock("@/components/motion/PageTransition", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/welcome/DailyWelcome", () => ({
  default: () => null,
}));

vi.mock("@/components/NoConnectionOverlay", () => ({
  NoConnectionOverlay: () => null,
}));

vi.mock("@/components/LockScreen", () => ({
  LockScreen: () => null,
}));

vi.mock("@/hooks/useWsBridge", () => ({
  useWsBridge: vi.fn(),
}));

vi.mock("@/hooks/useTickerFallback", () => ({
  useTickerFallback: vi.fn(),
}));

vi.mock("@/hooks/usePrevClose", () => ({
  usePrevClose: vi.fn(),
}));

// Default: live mode (no banner). vi.hoisted so the variable is available in the
// hoisted vi.mock factory.
const { mockModeStore } = vi.hoisted(() => ({
  mockModeStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({ mode: "live" }),
  ),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: mockModeStore,
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(
    vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
      selector({ status: "authenticated" }),
    ),
    { getState: () => ({ checkIdle: vi.fn(), touchActivity: vi.fn() }), setState: vi.fn() },
  ),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import AppLayout from "../AppLayout";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AppLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset sessionStorage so DailyWelcome / small screen overlays don't interfere
    sessionStorage.clear();
    // Ensure window.innerWidth is large enough to skip small screen overlay
    Object.defineProperty(window, "innerWidth", { value: 1920, writable: true });
  });

  it("renders header with TopBar and TickerBar, and a main landmark", () => {
    render(<AppLayout />);

    expect(screen.getByTestId("topbar")).toBeInTheDocument();
    expect(screen.getByTestId("tickerbar")).toBeInTheDocument();
    // <main> landmark with aria-label from route title
    expect(screen.getByRole("main", { name: /trading workspace/i })).toBeInTheDocument();
  });

  it("renders child route content via Outlet", () => {
    render(<AppLayout />);

    expect(screen.getByTestId("outlet-content")).toBeInTheDocument();
    expect(screen.getByText("Page Content")).toBeInTheDocument();
  });

  it("shows practice mode disclaimer banner when mode is practice", () => {
    mockModeStore.mockImplementation((selector: (s: Record<string, unknown>) => unknown) =>
      selector({ mode: "practice" }),
    );

    render(<AppLayout />);

    expect(screen.getByText(/practice mode/i)).toBeInTheDocument();
    expect(screen.getByText(/simulated/i)).toBeInTheDocument();
  });
});
