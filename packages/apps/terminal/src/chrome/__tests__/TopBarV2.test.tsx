/**
 * TopBarV2.test.tsx
 *
 * Tests for the redesigned glass TopBarV2 chrome component.
 * Verifies: logo, search button, absence of AI pill, live badge, Tools overflow.
 */

import { dirname, resolve } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const testDir = dirname(fileURLToPath(import.meta.url));
const topBarSource = () => readFileSync(resolve(testDir, "../TopBarV2.tsx"), "utf8");

const { mockSetConnectionStatus, mockDirectBrokerConnected, mockTimingsQuery } = vi.hoisted(() => ({
  mockSetConnectionStatus: vi.fn(),
  mockDirectBrokerConnected: { value: false },
  mockTimingsQuery: {
    data: undefined as Array<{ exchange: string; start_time: number; end_time: number }> | undefined,
    dataUpdatedAt: 0,
    isError: false,
    isLoading: false,
  },
}));

// ---------------------------------------------------------------------------
// Framer-motion stub
// ---------------------------------------------------------------------------
vi.mock("framer-motion", async (importOriginal) => {
  const actual = await importOriginal<typeof import("framer-motion")>();
  return {
    ...actual,
    motion: {
    div: ({ children, ...props }: Record<string, unknown>) => (
      <div {...props}>{children as React.ReactNode}</div>
    ),
  },
  };
});

// ---------------------------------------------------------------------------
// Child component stubs
// ---------------------------------------------------------------------------
vi.mock("@/components/NotificationCentre/NotificationCentre", () => ({
  default: () => (
    <button data-testid="notification-bell" aria-label="Notifications">
      <svg aria-hidden="true" />
    </button>
  ),
}));

vi.mock("../AccountSwitcher", () => ({
  default: () => <div data-testid="account-switcher" />,
}));

vi.mock("../WorkspaceSwitcher", () => ({
  default: () => <div data-testid="workspace-switcher" />,
}));

// ---------------------------------------------------------------------------
// Brand logo stub
// ---------------------------------------------------------------------------
vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg
      data-testid="logo-icon"
      width={size}
      height={size}
      aria-hidden="true"
    />
  ),
}));

// ---------------------------------------------------------------------------
// Store stubs
// ---------------------------------------------------------------------------
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: vi.fn(
    (selector: (state: Record<string, unknown>) => unknown) =>
      selector({
        status: "disconnected",
        setStatus: mockSetConnectionStatus,
      }),
  ),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useDirectBrokerConnected: () => mockDirectBrokerConnected.value,
}));

vi.mock("@/hooks/useMarketStatus", () => ({
  useTimings: vi.fn(() => mockTimingsQuery),
  MARKET_TIMINGS_MAX_AGE_MS: 5_000,
}));

vi.mock("@/services/api", () => ({
  ping: vi.fn().mockRejectedValue(new Error("not connected")),
}));

vi.mock("@/hooks/useSkillContent", () => ({
  useSkillContent: () => ({
    availableTools: ["trade-journal", "settings"],
  }),
}));

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

import { useSettingsStore } from "@/stores/settingsStore";
import { useDeskChromeStore } from "@/stores/deskChromeStore";
import { useModeStore } from "@/stores/modeStore";
import TopBarV2 from "../TopBarV2";

function renderTopBarV2(
  tickerMode?: "off" | "pinned" | "scroll" | "marquee",
  path = "/trade",
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <TopBarV2 tickerMode={tickerMode} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function setOpenMarketTestTime() {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-08-10T04:30:00.000Z")); // Monday, 10:00 IST
}

/** Pin wall-clock so IST calendar parts match the given instant. */
function setIstInstant(isoUtc: string) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(isoUtc));
}

function setExploreHhmmTimings() {
  mockTimingsQuery.data = [
    { exchange: "NSE", start_time: 915, end_time: 1530 },
    { exchange: "BSE", start_time: 915, end_time: 1530 },
    { exchange: "MCX", start_time: 900, end_time: 2330 },
  ];
  mockTimingsQuery.dataUpdatedAt = Date.now();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TopBarV2", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDirectBrokerConnected.value = false;
    mockTimingsQuery.data = undefined;
    mockTimingsQuery.dataUpdatedAt = 0;
    mockTimingsQuery.isError = false;
    mockTimingsQuery.isLoading = false;
    useSettingsStore.setState({ density: "comfortable", tickerMode: "marquee" });
    useDeskChromeStore.setState({ toolsExpanded: false, tickerForcedOnNarrow: false });
    useModeStore.setState({ mode: "explore" });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders without crashing", () => {
    const { container } = renderTopBarV2();
    expect(container).toBeTruthy();
  });

  it("renders the Flint logo icon", () => {
    renderTopBarV2();
    expect(screen.getByTestId("logo-icon")).toBeInTheDocument();
  });

  it('renders "Flint" wordmark text next to the logo', () => {
    renderTopBarV2();
    expect(screen.getByText("Flint")).toBeInTheDocument();
  });

  it('logo is wrapped in a link to "/trade"', () => {
    renderTopBarV2();
    const link = screen.getByRole("link", { name: /flint home/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/home");
  });

  it("renders the search button with accessible label", () => {
    renderTopBarV2();
    const searchBtn = screen.getByTestId("search-btn");
    expect(searchBtn).toBeInTheDocument();
    expect(searchBtn).toHaveAttribute("aria-label", expect.stringMatching(/search/i));
  });

  it("search button dispatches flinttrade:open-command-palette event on click", () => {
    renderTopBarV2();
    const listener = vi.fn();
    window.addEventListener("flinttrade:open-command-palette", listener);

    fireEvent.click(screen.getByTestId("search-btn"));

    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener("flinttrade:open-command-palette", listener);
  });

  it("leaves Ctrl+K handling to the route shortcut layer", () => {
    renderTopBarV2();
    const listener = vi.fn();
    window.addEventListener("flinttrade:open-command-palette", listener);

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener("flinttrade:open-command-palette", listener);
  });

  it("does NOT render an AI pill", () => {
    renderTopBarV2();
    // AI pill should not exist in the TopBar — it lives at bottom-right as a separate overlay
    expect(screen.queryByText(/ask ai/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("ai-pill")).not.toBeInTheDocument();
    expect(screen.queryByText(/ai assistant/i)).not.toBeInTheDocument();
  });

  it("reports the market session as unavailable until timing data is trustworthy", () => {
    renderTopBarV2();
    expect(screen.getByTestId("market-session-status")).toHaveTextContent("Market unavailable");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Live");
  });

  it("names a trustworthy in-session result Continuous rather than Live", () => {
    setOpenMarketTestTime();
    const now = Date.now();
    mockTimingsQuery.data = [{ exchange: "NSE", start_time: now - 60_000, end_time: now + 60_000 }];
    mockTimingsQuery.dataUpdatedAt = now;

    const { unmount } = renderTopBarV2();

    const chip = screen.getByTestId("market-session-status");
    expect(chip).toHaveTextContent("Continuous");
    expect(chip).toHaveAttribute("title", "Continuous · 09:15–15:15 (as of Aug 2026)");
    expect(chip).not.toHaveTextContent("Live");
    expect(chip).not.toHaveTextContent("Market open");
    unmount();
  });

  it("names a trustworthy weekday out-of-session result Closed", () => {
    setIstInstant("2026-08-10T12:30:00.000Z"); // Monday 18:00 IST
    const now = Date.now();
    mockTimingsQuery.data = [{ exchange: "NSE", start_time: now - 120_000, end_time: now - 60_000 }];
    mockTimingsQuery.dataUpdatedAt = now;

    const { unmount } = renderTopBarV2();

    expect(screen.getByTestId("market-session-status")).toHaveTextContent("Closed");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Live");
    unmount();
  });

  it("shows Continuous for Explore HHMM timings at Thursday mid-session IST", () => {
    // 10 Sep 2026 12:08 IST — the FT-TRADE-004 observation window.
    setIstInstant("2026-09-10T06:38:00.000Z");
    setExploreHhmmTimings();

    renderTopBarV2();

    expect(screen.getByTestId("market-session-status")).toHaveTextContent("Continuous");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Closed");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent(/demo/i);
  });

  it("shows Matching at 15:45 IST — not Closed and not green Continuous", () => {
    setIstInstant("2026-09-10T10:15:00.000Z"); // Thursday 15:45 IST
    setExploreHhmmTimings();

    renderTopBarV2();

    const chip = screen.getByTestId("market-session-status");
    expect(chip).toHaveTextContent("Matching");
    expect(chip).toHaveAttribute("title", "Matching · 15:35–15:50 (as of Aug 2026)");
    expect(chip).not.toHaveTextContent("Closed");
    expect(chip).not.toHaveTextContent("Continuous");
    expect(screen.queryByTestId("fo-session-status")).not.toBeInTheDocument();
  });

  it("shows CAS at 15:20 IST with the F&O secondary chip", () => {
    setIstInstant("2026-09-10T09:50:00.000Z"); // Thursday 15:20 IST
    setExploreHhmmTimings();

    renderTopBarV2();

    const chip = screen.getByTestId("market-session-status");
    expect(chip).toHaveTextContent("CAS");
    expect(chip).toHaveAttribute("title", "CAS · 15:15–15:35 (as of Aug 2026)");
    expect(chip).not.toHaveTextContent("Closed");
    expect(chip).not.toHaveTextContent("Continuous");
    expect(screen.getByTestId("fo-session-status")).toHaveTextContent("F&O open · till 15:40");
  });

  it("shows Closed for Explore HHMM timings on an IST weekend", () => {
    setIstInstant("2026-09-12T06:38:00.000Z"); // Saturday 12:08 IST
    setExploreHhmmTimings();

    renderTopBarV2();

    expect(screen.getByTestId("market-session-status")).toHaveTextContent("Closed");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Continuous");
  });

  it("uses the shared timing truth TTL rather than a drifting local limit", () => {
    setOpenMarketTestTime();
    const now = Date.now();
    mockTimingsQuery.data = [{ exchange: "NSE", start_time: now - 60_000, end_time: now + 60_000 }];
    mockTimingsQuery.dataUpdatedAt = now - 5_001;

    renderTopBarV2();

    expect(screen.getByTestId("market-session-status")).toHaveTextContent("Market unavailable");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Market open");
  });

  it("reports market timing refresh failures instead of retaining an authoritative state", () => {
    setOpenMarketTestTime();
    const now = Date.now();
    mockTimingsQuery.data = [{ exchange: "NSE", start_time: now - 60_000, end_time: now + 60_000 }];
    mockTimingsQuery.dataUpdatedAt = now;
    mockTimingsQuery.isError = true;

    renderTopBarV2();

    expect(screen.getByTestId("market-session-status")).toHaveTextContent("Market unavailable");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Market open");
  });

  it("market session status has an accessible label", () => {
    renderTopBarV2();
    expect(screen.getByLabelText(/market status/i)).toBeInTheDocument();
  });

  it("renders the IST clock", () => {
    renderTopBarV2();
    expect(screen.getByLabelText("Current time in IST")).toBeInTheDocument();
  });

  it("is not a quote rail — ticker strip lives under TopBar", () => {
    renderTopBarV2();
    expect(screen.queryByTestId("ticker-marquee")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Ticker prices" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Market indices" })).not.toBeInTheDocument();
  });

  it("shows a Sample feed-source chip in Explore (FT-CORE-002)", () => {
    useModeStore.setState({ mode: "explore" });
    renderTopBarV2();

    const chip = screen.getByTestId("feed-freshness-chip");
    expect(chip).toHaveTextContent("Sample");
    expect(chip).toHaveAttribute("data-state", "sample");
    expect(chip).not.toHaveTextContent("Live");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Sample");
  });

  it("renders the notification bell", () => {
    renderTopBarV2();
    expect(screen.getByTestId("notification-bell")).toBeInTheDocument();
  });

  it("renders the account switcher slot", () => {
    renderTopBarV2();
    expect(screen.getByTestId("account-switcher")).toBeInTheDocument();
  });

  it("keeps the terminal connected when a direct broker session exists and OpenAlgo ping fails", async () => {
    mockDirectBrokerConnected.value = true;
    useModeStore.setState({ mode: "live" });

    renderTopBarV2();

    await waitFor(() => {
      expect(mockSetConnectionStatus).toHaveBeenCalledWith("connected");
    });
  });

  it("never paints Connected in Explore even if a leftover broker session exists", async () => {
    mockDirectBrokerConnected.value = true;
    useModeStore.setState({ mode: "explore" });

    renderTopBarV2();

    await waitFor(() => {
      expect(mockSetConnectionStatus).toHaveBeenCalledWith("disconnected");
    });
    expect(mockSetConnectionStatus).not.toHaveBeenCalledWith("connected");
  });

  it("renders the fullscreen button", () => {
    renderTopBarV2();
    expect(screen.getByTestId("fullscreen-btn")).toBeInTheDocument();
  });

  it("opens the tools dropdown from the top bar", () => {
    renderTopBarV2();

    fireEvent.click(screen.getByRole("button", { name: /tools/i }));

    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /trade review/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /settings/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /p&l dashboard/i })).not.toBeInTheDocument();
  });

  it("dispatches the selected trade tool from the tools dropdown", () => {
    renderTopBarV2();
    const listener = vi.fn();
    window.addEventListener("flinttrade:open-tool", listener);

    fireEvent.click(screen.getByRole("button", { name: /tools/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /trade review/i }));

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener.mock.calls[0][0]).toMatchObject({
      detail: { toolId: "trade-journal" },
    });
    window.removeEventListener("flinttrade:open-tool", listener);
  });

  it("does not render a standalone Settings gear on the bar", () => {
    renderTopBarV2();
    expect(screen.queryByTestId("gear-btn")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^settings$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /quick settings/i })).not.toBeInTheDocument();
  });

  it("reaches Settings from the single Tools overflow", () => {
    renderTopBarV2();

    fireEvent.click(screen.getByRole("button", { name: /tools/i }));

    expect(screen.getAllByRole("menuitem", { name: /^settings$/i })).toHaveLength(1);
  });

  it("renders the user avatar button", () => {
    renderTopBarV2();
    expect(screen.getByTestId("avatar-btn")).toBeInTheDocument();
  });

  it("avatar button navigates to the Profile Manager (/settings#profile)", () => {
    // Mission: the Profile Manager must be reachable via the profile button AND
    // the quick-settings panel. This is the profile-button entry point; the
    // quick-settings entry point is covered in QuickAccessPanel.test.tsx.
    function LocationProbe() {
      const loc = useLocation();
      return <div data-testid="location-probe">{loc.pathname + loc.hash}</div>;
    }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/trade"]}>
          <TopBarV2 />
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("location-probe").textContent).toBe("/trade");
    fireEvent.click(screen.getByTestId("avatar-btn"));
    expect(screen.getByTestId("location-probe").textContent).toBe("/settings#profile");
  });

  it("mounts the trading mode indicator (Explore by default)", () => {
    renderTopBarV2();
    // ModeIndicator renders the EXPLORE pill when modeStore is at its default.
    expect(screen.getByText("EXPLORE")).toBeInTheDocument();
  });

  it("uses adaptive glass chrome tokens for the background", () => {
    renderTopBarV2();
    const bar = screen.getByTestId("topbar-v2");
    expect(bar.getAttribute("style")).toContain("--glass-chrome-bg");
    expect(bar.getAttribute("style")).toContain("--glass-chrome-border");
  });

  it("has banner role for accessibility", () => {
    renderTopBarV2();
    // TopBarV2 uses data-testid="topbar-v2" on its root div; role="banner"
    // was removed (commit ab0b595) to avoid a11y conflicts with the <header>
    // landmark it is nested inside.
    expect(screen.getByTestId("topbar-v2")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// FT-MOBILE-002 — defensive skinny-window chrome (~390px)
// ---------------------------------------------------------------------------

function stubViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    writable: true,
    value: width,
  });
  vi.spyOn(window, "matchMedia").mockImplementation((query: string) => {
    const max = /max-width:\s*(\d+)/.exec(query);
    const min = /min-width:\s*(\d+)/.exec(query);
    let matches = false;
    if (max) matches = width <= Number(max[1]);
    else if (min) matches = width >= Number(min[1]);
    return {
      matches,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    };
  });
}

describe("TopBarV2 skinny-window collapse (FT-MOBILE-002)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDirectBrokerConnected.value = false;
    mockTimingsQuery.data = undefined;
    mockTimingsQuery.dataUpdatedAt = 0;
    mockTimingsQuery.isError = false;
    mockTimingsQuery.isLoading = false;
    useSettingsStore.setState({ tickerMode: "marquee" });
    useDeskChromeStore.setState({ toolsExpanded: false, tickerForcedOnNarrow: false });
    stubViewportWidth(390);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    stubViewportWidth(1024);
    vi.useRealTimers();
  });

  it("keeps Mode visible and tappable at ~390px", () => {
    renderTopBarV2();

    const mode = screen.getByText("EXPLORE");
    expect(mode).toBeVisible();
    expect(mode.closest("button")).toBeEnabled();
  });

  it("does not use horizontal TopBar scroll at ~390px", () => {
    renderTopBarV2();

    const bar = screen.getByTestId("topbar-v2");
    expect(bar.className).not.toMatch(/overflow-x-auto/);
    expect(bar.className).toMatch(/overflow-x-hidden/);
  });

  it("does not host a ticker rail on the skinny TopBar", () => {
    renderTopBarV2();

    expect(screen.queryByTestId("ticker-marquee")).not.toBeInTheDocument();
    expect(useDeskChromeStore.getState().tickerForcedOnNarrow).toBe(false);
  });

  it("keeps Workspace off the inline bar and reachable from More", () => {
    renderTopBarV2();

    expect(screen.queryByTestId("workspace-switcher")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("topbar-more-btn"));

    const sheet = screen.getByTestId("topbar-more-sheet");
    expect(sheet).toBeVisible();
    expect(screen.getByTestId("workspace-switcher")).toBeVisible();
  });

  it("reaches account, Tools, search, fullscreen, and clock from More", () => {
    renderTopBarV2();

    expect(screen.queryByTestId("account-switcher")).not.toBeInTheDocument();
    expect(screen.queryByTestId("search-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tools-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("fullscreen-btn")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Current time in IST")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^more$/i }));

    expect(screen.getByTestId("account-switcher")).toBeVisible();
    expect(screen.getByTestId("search-btn")).toBeVisible();
    expect(screen.getByTestId("tools-btn")).toBeVisible();
    expect(screen.getByTestId("fullscreen-btn")).toBeVisible();
    expect(screen.getByLabelText("Current time in IST")).toBeVisible();
  });

  it("uses at least 44px hit targets on More sheet controls, not only the row", () => {
    renderTopBarV2();

    fireEvent.click(screen.getByTestId("topbar-more-btn"));

    const rows = screen.getAllByTestId("topbar-more-row");
    expect(rows.length).toBeGreaterThanOrEqual(4);
    for (const row of rows) {
      expect(row.className).toMatch(/min-h-11/);
      expect(row.className).toMatch(/\[&_button\]:min-h-11/);
    }
  });

  it("lets More re-enable the dedicated ticker strip under ~480px", () => {
    renderTopBarV2();
    expect(useDeskChromeStore.getState().tickerForcedOnNarrow).toBe(false);

    fireEvent.click(screen.getByTestId("topbar-more-btn"));
    fireEvent.click(screen.getByRole("button", { name: /show ticker/i }));

    expect(useDeskChromeStore.getState().tickerForcedOnNarrow).toBe(true);
    expect(screen.queryByTestId("ticker-marquee")).not.toBeInTheDocument();
  });

  it("re-enables the ticker from More when persisted mode is off", () => {
    useSettingsStore.setState({ tickerMode: "off" });
    renderTopBarV2();

    fireEvent.click(screen.getByTestId("topbar-more-btn"));
    fireEvent.click(screen.getByRole("button", { name: /show ticker/i }));

    expect(useDeskChromeStore.getState().tickerForcedOnNarrow).toBe(true);
    expect(useSettingsStore.getState().tickerMode).toBe("marquee");
    expect(screen.queryByTestId("ticker-marquee")).not.toBeInTheDocument();
  });

  it("collapses overflow at ~450px so hidden overflow cannot clip Mode", () => {
    stubViewportWidth(450);
    renderTopBarV2();

    expect(screen.queryByTestId("ticker-marquee")).not.toBeInTheDocument();
    expect(useDeskChromeStore.getState().tickerForcedOnNarrow).toBe(false);
    expect(screen.getByText("EXPLORE")).toBeVisible();
    expect(screen.getByTestId("topbar-more-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("workspace-switcher")).not.toBeInTheDocument();
  });

  it("reaches Settings from Tools in More without a second Settings row", () => {
    renderTopBarV2();

    fireEvent.click(screen.getByTestId("topbar-more-btn"));
    expect(screen.queryByTestId("gear-btn")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^settings$/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("tools-btn"));
    expect(screen.getAllByRole("menuitem", { name: /^settings$/i })).toHaveLength(1);
  });

  it("keeps the More sheet below nested account and notification portals", () => {
    renderTopBarV2();

    fireEvent.click(screen.getByTestId("topbar-more-btn"));

    const root = screen.getByTestId("topbar-more-root");
    expect(root.className).toMatch(/z-\[110]/);
    expect(root.className).not.toMatch(/z-\[121]/);
  });
});

describe("FT-UX-001 Compact desk chrome at 1280", () => {
  beforeEach(() => {
    useSettingsStore.setState({ density: "compact", tickerMode: "marquee" });
    useDeskChromeStore.setState({ toolsExpanded: false, tickerForcedOnNarrow: false });
    stubViewportWidth(1280);
  });

  afterEach(() => {
    vi.useRealTimers();
    stubViewportWidth(1024);
    useSettingsStore.setState({ density: "comfortable" });
    useDeskChromeStore.setState({ toolsExpanded: false });
  });

  it("keeps Mode and market-session copy distinct and hides the ticker", () => {
    setOpenMarketTestTime();
    setExploreHhmmTimings();
    mockTimingsQuery.dataUpdatedAt = Date.now();
    renderTopBarV2();

    expect(screen.getByText("EXPLORE")).toBeVisible();
    const session = screen.getByTestId("market-session-status");
    expect(session).toHaveAccessibleName(/market status: continuous/i);
    expect(session).toHaveTextContent(/continuous/i);
    expect(session).not.toHaveTextContent(/Live/i);
    expect(screen.queryByTestId("ticker-marquee")).not.toBeInTheDocument();
    expect(screen.getByTestId("topbar-desk-tools-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("tools-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workspace-switcher")).not.toBeInTheDocument();
  });

  it("Comfortable restores the tool ribbon without changing Mode honesty", () => {
    useSettingsStore.setState({ density: "comfortable" });
    renderTopBarV2();

    expect(screen.getByText("EXPLORE")).toBeVisible();
    expect(screen.getByTestId("tools-btn")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-switcher")).toBeInTheDocument();
    expect(screen.queryByTestId("topbar-desk-tools-btn")).not.toBeInTheDocument();
  });

  it("does not collapse the tool ribbon on Compact Home", () => {
    renderTopBarV2("marquee", "/home");

    expect(screen.getByTestId("tools-btn")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-switcher")).toBeInTheDocument();
    expect(screen.queryByTestId("topbar-desk-tools-btn")).not.toBeInTheDocument();
  });
});

describe("FT-UX-002 TopBar chrome consolidation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDirectBrokerConnected.value = false;
    mockTimingsQuery.data = undefined;
    mockTimingsQuery.dataUpdatedAt = 0;
    mockTimingsQuery.isError = false;
    mockTimingsQuery.isLoading = false;
    useSettingsStore.setState({ density: "comfortable", tickerMode: "marquee" });
    useDeskChromeStore.setState({ toolsExpanded: false, tickerForcedOnNarrow: false });
    useModeStore.setState({ mode: "explore" });
    stubViewportWidth(1280);
  });

  afterEach(() => {
    stubViewportWidth(1024);
    vi.useRealTimers();
  });

  it("source-guard: TopBar does not mount a ticker rail or Settings gear", () => {
    const src = topBarSource();
    expect(src).not.toContain("<TickerMarquee");
    expect(src).not.toContain("gear-btn");
    expect(src).not.toContain("QuickAccessPanel");
  });

  it("keeps one Tools overflow and no extra Settings chrome button", () => {
    renderTopBarV2();

    expect(screen.getAllByTestId("tools-btn")).toHaveLength(1);
    expect(screen.queryByTestId("gear-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ticker-marquee")).not.toBeInTheDocument();
  });
});
