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
const { mockLocation } = vi.hoisted(() => ({
  mockLocation: { pathname: "/trade" },
}));

vi.mock("react-router", () => ({
  Outlet: () => <div data-testid="outlet-content">Page Content</div>,
  useLocation: () => ({ pathname: mockLocation.pathname }),
  useNavigate: () => mockNavigate,
}));

vi.mock("@/chrome/TopBarV2", () => ({
  default: () => <div data-testid="topbar">TopBar</div>,
}));

vi.mock("@/chrome/AppNavigation", () => ({
  AppNavigation: () => <nav aria-label="Apps" />,
  SystemStatusBar: () => <footer>System</footer>,
}));
vi.mock("@/routes/UnifiedAppsHost", () => ({ UnifiedAppsHost: () => null }));

vi.mock("@/chrome/TickerBar", () => ({
  default: () => <div data-testid="ticker-strip">TickerStrip</div>,
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

const { mockUseBrokerAccounts } = vi.hoisted(() => ({
  mockUseBrokerAccounts: vi.fn(),
}));

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: mockUseBrokerAccounts,
}));

vi.mock("@/hooks/usePrevClose", () => ({
  usePrevClose: vi.fn(),
}));

const { mockBrokerConnected } = vi.hoisted(() => ({
  mockBrokerConnected: { value: true },
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockBrokerConnected.value,
  useDirectBrokerConnected: () => mockBrokerConnected.value,
}));

vi.mock("@/services/ftApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi")>();
  return {
    ...actual,
    getSafetyConfig: vi.fn().mockResolvedValue({
      kill_switch_active: false,
      daily_loss_hard_stop_active: false,
      daily_loss_pause_active: false,
    }),
  };
});

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

// Keep auth/mode hooks and imperative receipt guards on the same real stores.
// Partial hook mocks cannot supply their subscription and retirement contract.

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import AppLayout from "../AppLayout";
import useGlobalKeys from "@/hooks/useGlobalKeys";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useDeskChromeStore } from "@/stores/deskChromeStore";
import { useTradingStore } from "@/stores/tradingStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { PRIMARY_NATIVE_ACCOUNT, PRIMARY_SCOPE } from "@/test-utils/accountQueryHarness";

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
    useAuthStore.setState((state) => ({
      ...useAuthStore.getInitialState(),
      status: "logged-in",
      token: "synthetic-app-layout-session",
      username: "synthetic-operator",
      sessionGeneration: state.sessionGeneration + 1,
      lastActivity: Date.now(),
    }));
    useModeStore.getState().setMode("live");
    // Reset sessionStorage so DailyWelcome / small screen overlays don't interfere
    sessionStorage.clear();
    // Reset localStorage so tour state is fresh per test
    localStorage.clear();
    // Ensure window.innerWidth is large enough to skip small screen overlay
    Object.defineProperty(window, "innerWidth", { value: 1920, writable: true });
    useSettingsStore.setState({
      density: "comfortable",
      tickerMode: "marquee",
      riskLimits: { ...useSettingsStore.getState().riskLimits, mtmStoploss: 0 },
    });
    useDeskChromeStore.setState({ toolsExpanded: false, tickerForcedOnNarrow: false });
    mockBrokerConnected.value = true;
    useOperatorSignalStore.setState({ decisionStatus: "ready" });
    useTradingStore.getState().resetSessionState();
    useBrokerStore.getState().resetSessionState();
    mockLocation.pathname = "/trade";
  });

  it("keeps compact apps usable without a blocking desktop warning", () => {
    Object.defineProperty(window, "innerWidth", { value: 390, writable: true });
    renderApp();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });

  it("renders header with TopBar and one ticker strip, and a main landmark", () => {
    renderApp();

    expect(screen.getByTestId("topbar")).toBeInTheDocument();
    expect(screen.getAllByTestId("ticker-strip")).toHaveLength(1);
    expect(screen.queryByTestId("tickerbar")).not.toBeInTheDocument();
    // <main> landmark named after the route, matching its sidebar label
    expect(screen.getByRole("main", { name: "Terminal" })).toBeInTheDocument();
    // The shell leaves the single H1 to the route itself
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });

  it("keeps route-local icon SVG markup out of the layout source", () => {
    expect(appLayoutSource()).not.toContain("<" + "svg");
  });

  it("renders child route content via Outlet", () => {
    renderApp();

    expect(screen.getByTestId("outlet-content")).toBeInTheDocument();
    expect(screen.getByText("Page Content")).toBeInTheDocument();
  });

  it("shows the Practice Mode line and leaves the incident slot empty", () => {
    useModeStore.getState().setMode("practice");

    renderApp();

    const bar = screen.getByTestId("mode-honesty-bar");
    expect(bar).toHaveAttribute("data-mode", "practice");
    expect(bar).toHaveTextContent(
      "Practice — simulated fills, no real money.",
    );
    expect(screen.queryByTestId("incident-strip")).not.toBeInTheDocument();
  });

  it("shows the Explore Mode line and never an incident strip", () => {
    useModeStore.getState().setMode("explore");

    renderApp();

    const bar = screen.getByTestId("mode-honesty-bar");
    expect(bar).toHaveAttribute("data-mode", "explore");
    expect(bar).toHaveTextContent(
      "Example data. No broker is connected and no orders are sent.",
    );
    expect(screen.queryByTestId("incident-strip")).not.toBeInTheDocument();
  });

  it("keeps the Live Mode line when the feed-disconnected incident is showing", () => {
    mockBrokerConnected.value = false;
    renderApp();

    const strip = screen.getByTestId("incident-strip");
    expect(strip).toHaveAttribute("data-banner-kind", "feed_disconnected");
    expect(strip).toHaveTextContent(/feed disconnected/i);
    const bar = screen.getByTestId("mode-honesty-bar");
    expect(bar).toHaveTextContent(
      "Live — real-money capable when a broker is Connected. Orders place only on a live session.",
    );
    const header = screen.getByRole("banner");
    const order = Array.from(header.querySelectorAll("[data-testid]")).map((node) =>
      node.getAttribute("data-testid"),
    );
    expect(order.indexOf("topbar")).toBeLessThan(order.indexOf("incident-strip"));
    expect(order.indexOf("incident-strip")).toBeLessThan(order.indexOf("mode-honesty-bar"));
    expect(order.indexOf("mode-honesty-bar")).toBeLessThan(order.indexOf("ticker-strip"));
  });

  it("shows Live risk above the Mode line when daily-loss is active", () => {
    mockBrokerConnected.value = false;
    useSettingsStore.setState({
      riskLimits: { ...useSettingsStore.getState().riskLimits, mtmStoploss: 5000 },
    });
    // The sync hook is mocked here: seed its complete scoped contract. A feed
    // outage must not hide a known loss from this selected account's cache.
    useBrokerStore.getState().setAccounts([PRIMARY_NATIVE_ACCOUNT]);
    useBrokerStore.getState().setActiveAccount(brokerAccountKey(PRIMARY_NATIVE_ACCOUNT));
    useTradingStore.setState({
      scopeKey: PRIMARY_SCOPE,
      positionsStatus: "stale",
      totalPnl: -2500,
    });
    renderApp();

    const strip = screen.getByTestId("incident-strip");
    expect(strip).toHaveAttribute("data-banner-kind", "live_risk");
    expect(strip).toHaveTextContent(/Live risk/i);
    expect(screen.getByTestId("mode-honesty-bar")).toHaveTextContent(
      "Live — real-money capable when a broker is Connected. Orders place only on a live session.",
    );
  });

  it("does not promote another account's cached loss into the current Live risk banner", () => {
    mockBrokerConnected.value = false;
    useSettingsStore.setState({
      riskLimits: { ...useSettingsStore.getState().riskLimits, mtmStoploss: 5000 },
    });
    // No account is selected. The old account's otherwise valid cached loss
    // must not outrank the current disconnected-feed incident.
    useTradingStore.setState({
      scopeKey: PRIMARY_SCOPE,
      positionsStatus: "stale",
      totalPnl: -2500,
    });
    renderApp();

    expect(screen.getByTestId("incident-strip")).toHaveAttribute("data-banner-kind", "feed_disconnected");
    expect(screen.getByTestId("incident-strip")).not.toHaveTextContent(/Live risk/i);
  });

  it("hides the ticker strip on Compact desk until desk tools expand", () => {
    useSettingsStore.setState({ density: "compact" });
    renderApp();

    expect(screen.queryByTestId("ticker-strip")).not.toBeInTheDocument();

    act(() => {
      useDeskChromeStore.getState().setToolsExpanded(true);
    });
    expect(screen.getByTestId("ticker-strip")).toBeInTheDocument();
  });

  it("keeps the ticker on Compact Home — disclosure is Trade-only", () => {
    mockLocation.pathname = "/home";
    useSettingsStore.setState({ density: "compact" });
    renderApp();

    expect(screen.getByTestId("ticker-strip")).toBeInTheDocument();
  });

  it("does not show the greeting toast on Home or Trade", () => {
    mockLocation.pathname = "/trade";
    const { unmount } = renderApp();
    expect(screen.queryByTestId("daily-welcome")).not.toBeInTheDocument();
    unmount();

    mockLocation.pathname = "/home";
    renderApp();
    expect(screen.queryByTestId("daily-welcome")).not.toBeInTheDocument();
  });

  it("does not show the daily welcome card in explore mode", () => {
    useModeStore.getState().setMode("explore");

    renderApp();

    expect(screen.queryByTestId("daily-welcome")).not.toBeInTheDocument();
    expect(mockUseBrokerAccounts).toHaveBeenCalledWith(false);
  });

  it("polls native accounts for an authenticated non-Explore session", () => {
    renderApp();

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

  it("Trade route body is a flex-fill shell under TopBar and ticker strip", () => {
    renderApp();

    const header = document.querySelector("header");
    expect(header?.className).toMatch(/flex/);
    expect(header?.className).toMatch(/flex-col/);
    expect(screen.getByTestId("topbar").compareDocumentPosition(screen.getByTestId("ticker-strip"))
      & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const body = screen.getByTestId("route-body");
    expect(body.className).toMatch(/flex-1/);
    expect(body.className).toMatch(/min-h-0/);
    expect(screen.getByRole("main").className).toMatch(/flex-col/);
    expect(screen.getByRole("main").className).toMatch(/min-h-0/);
  });

  it("hides the dedicated ticker strip when ticker mode is off", () => {
    useSettingsStore.setState({ tickerMode: "off" });
    renderApp();

    expect(screen.queryByTestId("ticker-strip")).not.toBeInTheDocument();
  });

  it("source-guard: TopBar is not a second quote rail", () => {
    const src = appLayoutSource();
    expect(src).toMatch(/showTickerStrip/);
    expect(src).toMatch(/data-testid="route-body"/);
    expect(src).not.toMatch(/TickerMarquee/);
  });
});
