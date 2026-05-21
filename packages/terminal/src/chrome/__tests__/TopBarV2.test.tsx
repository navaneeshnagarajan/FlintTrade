/**
 * TopBarV2.test.tsx
 *
 * Tests for the redesigned glass TopBarV2 chrome component.
 * Verifies: logo, search button, absence of AI pill, live badge, ticker area.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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
        setStatus: vi.fn(),
      }),
  ),
}));

vi.mock("@/hooks/useMarketStatus", () => ({
  useTimings: vi.fn(() => ({ data: undefined, isLoading: false, error: null })),
}));

vi.mock("@/services/api", () => ({
  ping: vi.fn().mockRejectedValue(new Error("not connected")),
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
    expect(link).toHaveAttribute("href", "/trade");
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

  it("renders the live market badge", () => {
    renderTopBarV2();
    expect(screen.getByTestId("live-badge")).toBeInTheDocument();
  });

  it("live badge has accessible market status label", () => {
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

  it("renders the fullscreen button", () => {
    renderTopBarV2();
    expect(screen.getByTestId("fullscreen-btn")).toBeInTheDocument();
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

  it("has correct glass background style", () => {
    renderTopBarV2();
    const bar = screen.getByTestId("topbar-v2");
    // background is applied via inline style
    expect(bar).toHaveStyle({ background: "rgba(12, 12, 20, 0.85)" });
  });

  it("has banner role for accessibility", () => {
    renderTopBarV2();
    // TopBarV2 uses data-testid="topbar-v2" on its root div; role="banner"
    // was removed (commit ab0b595) to avoid a11y conflicts with the <header>
    // landmark it is nested inside.
    expect(screen.getByTestId("topbar-v2")).toBeInTheDocument();
  });
});
