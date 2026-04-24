/**
 * AppLayout.test.tsx
 *
 * Smoke tests for the shared app chrome layout.
 * Verifies header/main landmarks, mode banners, and child Outlet rendering.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router-dom", () => ({
  Outlet: () => <div data-testid="outlet-content">Page Content</div>,
  useLocation: () => ({ pathname: "/trade" }),
  useNavigate: () => mockNavigate,
}));

vi.mock("@/chrome/TopBarV2", () => ({
  default: () => <div data-testid="topbar">TopBar</div>,
}));

vi.mock("@/chrome/DockSidebar", () => ({
  default: () => null,
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

vi.mock("@/components/tour/InteractiveTour", () => ({
  default: ({ onComplete }: { onComplete: () => void }) => (
    <div data-testid="interactive-tour">
      <button onClick={onComplete}>Skip Tour</button>
    </div>
  ),
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

vi.mock("@/hooks/useGlobalKeys", () => ({
  default: vi.fn(),
}));

vi.mock("@/components/KeyboardShortcuts/KeyboardShortcutsDialog", () => ({
  default: () => null,
}));

// useTradingStoreSync calls useFunds + usePositions internally; stub it so
// those hooks don't need a real QueryClient when the outer test does supply one.
vi.mock("@/hooks/useTradingStoreSync", () => ({
  useTradingStoreSync: vi.fn(),
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
// Test helpers
// ---------------------------------------------------------------------------

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
}

function renderApp() {
  const queryClient = createTestQueryClient();
  return render(
    React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(AppLayout),
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AppLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset sessionStorage so DailyWelcome / small screen overlays don't interfere
    sessionStorage.clear();
    // Reset localStorage so tour state is fresh per test
    localStorage.clear();
    // Ensure window.innerWidth is large enough to skip small screen overlay
    Object.defineProperty(window, "innerWidth", { value: 1920, writable: true });
  });

  it("renders header with TopBar and TickerBar, and a main landmark", () => {
    renderApp();

    expect(screen.getByTestId("topbar")).toBeInTheDocument();
    expect(screen.getByTestId("tickerbar")).toBeInTheDocument();
    // <main> landmark with aria-label from route title
    expect(screen.getByRole("main", { name: /trading workspace/i })).toBeInTheDocument();
  });

  it("renders child route content via Outlet", () => {
    renderApp();

    expect(screen.getByTestId("outlet-content")).toBeInTheDocument();
    expect(screen.getByText("Page Content")).toBeInTheDocument();
  });

  it("shows practice mode disclaimer banner when mode is practice", () => {
    mockModeStore.mockImplementation((selector: (s: Record<string, unknown>) => unknown) =>
      selector({ mode: "practice" }),
    );

    renderApp();

    expect(screen.getByText(/practice mode/i)).toBeInTheDocument();
    expect(screen.getByText(/simulated/i)).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Interactive tour tests
  // -------------------------------------------------------------------------

  it("shows InteractiveTour on /trade when tour has not been completed", () => {
    // localStorage is already clear from beforeEach — tour has not been seen
    renderApp();

    expect(screen.getByTestId("interactive-tour")).toBeInTheDocument();
  });

  it("does not show InteractiveTour when tour has already been completed", () => {
    localStorage.setItem("flinttrade:tourComplete", "true");

    renderApp();

    expect(screen.queryByTestId("interactive-tour")).not.toBeInTheDocument();
  });

  it("hides InteractiveTour after onComplete is called", () => {
    renderApp();

    expect(screen.getByTestId("interactive-tour")).toBeInTheDocument();

    // Simulate tour completion via the Skip button exposed by the mock.
    // Wrapped in act() because the click triggers a React state update (setShowTour).
    act(() => {
      screen.getByRole("button", { name: /skip tour/i }).click();
    });

    expect(screen.queryByTestId("interactive-tour")).not.toBeInTheDocument();
  });
});
