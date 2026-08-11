/**
 * AppLayout.test.tsx
 *
 * Smoke tests for the shared app chrome layout.
 * Verifies header/main landmarks, mode banners, and child Outlet rendering.
 */

import { dirname, resolve } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router", () => ({
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
  default: () => <div data-testid="daily-welcome" />,
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

const { mockUseOpenAlgoConfigHydration } = vi.hoisted(() => ({
  mockUseOpenAlgoConfigHydration: vi.fn(),
}));

const { mockUseBrokerAccounts } = vi.hoisted(() => ({
  mockUseBrokerAccounts: vi.fn(),
}));

vi.mock("@/hooks/useOpenAlgoConfigHydration", () => ({
  useOpenAlgoConfigHydration: mockUseOpenAlgoConfigHydration,
}));

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: mockUseBrokerAccounts,
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

vi.mock("@/components/CommandPalette/CommandPalette", () => ({
  default: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="command-palette" /> : null,
}));

vi.mock("@/components/DocsSearch/DocsSearch", () => ({
  default: ({ isOpen, initialQuery }: { isOpen: boolean; initialQuery?: string }) =>
    isOpen ? <div data-testid="docs-search">Docs search {initialQuery}</div> : null,
}));

vi.mock("@/components/Changelog/ChangelogViewer", () => ({
  default: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="changelog-viewer">Changelog</div> : null,
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
      selector({ status: "logged-in" }),
    ),
    { getState: () => ({ checkIdle: vi.fn(), touchActivity: vi.fn() }), setState: vi.fn() },
  ),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import AppLayout from "../AppLayout";
import useGlobalKeys from "@/hooks/useGlobalKeys";

const testDir = dirname(fileURLToPath(import.meta.url));
const appLayoutSource = () =>
  readFileSync(resolve(testDir, "../AppLayout.tsx"), "utf8");
const useGlobalKeysSource = () =>
  readFileSync(resolve(testDir, "../../hooks/useGlobalKeys.ts"), "utf8");

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
    mockModeStore.mockImplementation((selector: (s: Record<string, unknown>) => unknown) =>
      selector({ mode: "live" }),
    );
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

  it("keeps route-local icon SVG markup out of the layout source", () => {
    expect(appLayoutSource()).not.toContain("<" + "svg");
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

  it("does not show the daily welcome card in explore mode", () => {
    mockModeStore.mockImplementation((selector: (s: Record<string, unknown>) => unknown) =>
      selector({ mode: "explore" }),
    );

    renderApp();

    expect(screen.queryByTestId("daily-welcome")).not.toBeInTheDocument();
    expect(mockUseOpenAlgoConfigHydration).toHaveBeenCalledWith(false);
    expect(mockUseBrokerAccounts).toHaveBeenCalledWith(false);
  });

  it("hydrates broker config for an authenticated non-Explore session", () => {
    renderApp();

    expect(mockUseOpenAlgoConfigHydration).toHaveBeenCalledWith(true);
    expect(mockUseBrokerAccounts).toHaveBeenCalledWith(true);
  });

  it("does not render the removed legacy dot tour overlay", () => {
    renderApp();

    expect(screen.queryByRole("dialog", { name: /interactive tour/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /skip tour/i })).not.toBeInTheDocument();
  });

  it("opens the command palette from the top-bar custom event", () => {
    renderApp();

    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:open-command-palette"));
    });

    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
  });

  it("navigates when the global navigation event uses a path string", () => {
    renderApp();

    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:navigate", { detail: "/ai" }));
    });

    expect(mockNavigate).toHaveBeenCalledWith("/ai");
  });

  it("navigates when the global navigation event uses a structured path detail", () => {
    renderApp();

    act(() => {
      window.dispatchEvent(
        new CustomEvent("flinttrade:navigate", { detail: { path: "/lab" } }),
      );
    });

    expect(mockNavigate).toHaveBeenCalledWith("/lab");
  });

  it("opens docs search from the global shell event", () => {
    renderApp();

    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:search-docs"));
    });

    expect(screen.getByTestId("docs-search")).toBeInTheDocument();
  });

  it("opens the changelog from the global shell event", () => {
    renderApp();

    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:show-changelog"));
    });

    expect(screen.getByTestId("changelog-viewer")).toBeInTheDocument();
  });

  it("routes a selected docs search result into Learn", () => {
    renderApp();

    act(() => {
      window.dispatchEvent(
        new CustomEvent("flinttrade:openDoc", { detail: { path: "USER_GUIDE.md" } }),
      );
    });

    expect(mockNavigate).toHaveBeenCalledWith("/learn", {
      state: { selectedDocPath: "USER_GUIDE.md" },
    });
  });

  it("wires onGoHome / onGoTrade into the single useGlobalKeys mount", () => {
    renderApp();

    expect(useGlobalKeys).toHaveBeenCalled();
    const calls = vi.mocked(useGlobalKeys).mock.calls;
    expect(calls.length).toBeGreaterThanOrEqual(1);
    const handlers = calls[0]?.[0] as {
      onGoHome?: () => void;
      onGoTrade?: () => void;
    };
    expect(typeof handlers.onGoHome).toBe("function");
    expect(typeof handlers.onGoTrade).toBe("function");

    act(() => {
      handlers.onGoHome?.();
    });
    expect(mockNavigate).toHaveBeenCalledWith("/home");

    act(() => {
      handlers.onGoTrade?.();
    });
    expect(mockNavigate).toHaveBeenCalledWith("/trade");
  });

  it("source-guard: AppLayout is the sole useGlobalKeys mount and handles Alt+H/T", () => {
    const layout = appLayoutSource();
    const hook = useGlobalKeysSource();

    // Exactly one hook call site in AppLayout (single mount).
    const mountMatches = layout.match(/useGlobalKeys\s*\(/g) ?? [];
    expect(mountMatches).toHaveLength(1);
    expect(layout).toMatch(/onGoHome\s*:/);
    expect(layout).toMatch(/onGoTrade\s*:/);
    expect(layout).toMatch(/navigate\(\s*[\\\"']\/home[\\\"']\s*\)/);
    expect(layout).toMatch(/navigate\(\s*[\\\"']\/trade[\\\"']\s*\)/);

    // Real handlers exist in the hook (not dialog-only advertising).
    expect(hook).toMatch(/onGoHome/);
    expect(hook).toMatch(/onGoTrade/);
    expect(hook).toMatch(/e\.altKey[\s\S]{0,80}[\\\"']h[\\\"']/);
    expect(hook).toMatch(/e\.altKey[\s\S]{0,80}[\\\"']t[\\\"']/);
  });

  it("normalises and safely merges validated palette context into an existing /ai query", () => {
    renderApp();
    act(() => {
      window.dispatchEvent(
        new CustomEvent("flinttrade:navigate", {
          detail: {
            path: "/ai?chat=saved%2Fchat#advisor",
            context: { symbol: " nifty-26mar-fut ", exchange: "nfo", source: "palette" },
          },
        }),
      );
    });

    expect(mockNavigate).toHaveBeenCalledWith(
      "/ai?chat=saved%2Fchat&symbol=NIFTY-26MAR-FUT&exchange=NFO&source=palette#advisor",
    );
  });

  it.each([
    ["another route", { path: "/lab?view=ai", context: { symbol: "RELIANCE", exchange: "NSE", source: "palette" } }],
    ["partial context", { path: "/ai?chat=one", context: { symbol: "RELIANCE", exchange: "NSE" } }],
    ["invalid symbol", { path: "/ai", context: { symbol: "RELIANCE<script>", exchange: "NSE", source: "palette" } }],
    ["unknown exchange", { path: "/ai", context: { symbol: "RELIANCE", exchange: "FAKE", source: "palette" } }],
    ["untrusted source", { path: "/ai", context: { symbol: "RELIANCE", exchange: "NSE", source: "url" } }],
  ])("does not append symbol context for %s", (_case, detail) => {
    renderApp();
    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:navigate", { detail }));
    });

    expect(mockNavigate).toHaveBeenCalledWith(detail.path);
  });
});
