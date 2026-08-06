/**
 * TopBarV2.test.tsx
 *
 * Tests for the redesigned glass TopBarV2 chrome component.
 * Verifies: logo, search button, absence of AI pill, live badge, ticker area.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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
vi.mock("../QuickAccessPanel", () => ({
  default: () => (
    <div role="dialog" aria-label="Quick settings" data-testid="quick-access-panel" />
  ),
}));

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

// TickerMarquee stub — renders a simple labelled region so ticker tests pass
vi.mock("../TickerMarquee", () => ({
  default: ({ mode }: { mode?: string }) =>
    mode === "off" ? null : (
      <div
        role="region"
        aria-label="Ticker prices"
        data-testid="ticker-marquee"
      />
    ),
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

import TopBarV2 from "../TopBarV2";

function renderTopBarV2(tickerMode?: "off" | "pinned" | "scroll" | "marquee") {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/trade"]}>
        <TopBarV2 tickerMode={tickerMode} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
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

  it("names a trustworthy in-session result Market open rather than Live", () => {
    const now = Date.now();
    mockTimingsQuery.data = [{ exchange: "NSE", start_time: now - 60_000, end_time: now + 60_000 }];
    mockTimingsQuery.dataUpdatedAt = now;

    renderTopBarV2();

    expect(screen.getByTestId("market-session-status")).toHaveTextContent("Market open");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Live");
  });

  it("names a trustworthy out-of-session result Market closed", () => {
    const now = Date.now();
    mockTimingsQuery.data = [{ exchange: "NSE", start_time: now - 120_000, end_time: now - 60_000 }];
    mockTimingsQuery.dataUpdatedAt = now;

    renderTopBarV2();

    expect(screen.getByTestId("market-session-status")).toHaveTextContent("Market closed");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Live");
  });

  it("does not present stale timing data as an authoritative open market", () => {
    const now = Date.now();
    mockTimingsQuery.data = [{ exchange: "NSE", start_time: now - 60_000, end_time: now + 60_000 }];
    mockTimingsQuery.dataUpdatedAt = now - 2 * 60 * 60_000;

    renderTopBarV2();

    expect(screen.getByTestId("market-session-status")).toHaveTextContent("Market unavailable");
    expect(screen.getByTestId("market-session-status")).not.toHaveTextContent("Market open");
  });

  it("reports market timing refresh failures instead of retaining an authoritative state", () => {
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

  it("renders the ticker area (marquee mode by default)", () => {
    renderTopBarV2();
    expect(screen.getByTestId("ticker-marquee")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Ticker prices" })).toBeInTheDocument();
  });

  it('ticker is hidden when mode is "off"', () => {
    renderTopBarV2("off");
    expect(screen.queryByTestId("ticker-marquee")).not.toBeInTheDocument();
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

    renderTopBarV2();

    await waitFor(() => {
      expect(mockSetConnectionStatus).toHaveBeenCalledWith("connected");
    });
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

  it("renders the gear/settings button", () => {
    renderTopBarV2();
    expect(screen.getByTestId("gear-btn")).toBeInTheDocument();
  });

  it("opens quick settings from the gear button", () => {
    renderTopBarV2();

    fireEvent.click(screen.getByTestId("gear-btn"));

    expect(screen.getByRole("dialog", { name: /quick settings/i })).toBeInTheDocument();
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
