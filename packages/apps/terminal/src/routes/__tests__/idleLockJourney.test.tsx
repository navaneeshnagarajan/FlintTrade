/**
 * Idle lock through the desk route: the idle timer locks the session, the
 * desk unmounts, Welcome shows Quick Unlock, and the PIN restores the session.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { ReactNode } from "react";

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, variants: _v, transition: _t, whileHover: _w, layout: _l, ...rest } = props;
      return <div {...rest}>{children as ReactNode}</div>;
    },
    span: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <span {...rest}>{children as ReactNode}</span>;
    },
    button: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <button type="button" {...rest}>{children as ReactNode}</button>;
    },
    p: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <p {...rest}>{children as ReactNode}</p>;
    },
  },
  AnimatePresence: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0, normal: 0, slow: 0 },
    ease: { enter: [0, 0, 1, 1], exit: [0, 0, 1, 1] },
    transitions: { fade: { duration: 0 } },
  },
}));

vi.mock("@/components/magicui/particles", () => ({ Particles: () => null }));
vi.mock("@/components/aceternity/meteors", () => ({ Meteors: () => null }));
vi.mock("@/components/magicui/shimmer-button", () => ({
  ShimmerButton: ({ children, ...props }: { children?: ReactNode }) => (
    <button type="button" {...props}>{children}</button>
  ),
}));
vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: () => <span data-testid="logo-icon" />,
}));

vi.mock("@/chrome/TopBarV2", () => ({
  default: () => <div data-testid="topbar">TopBar</div>,
}));
vi.mock("@/chrome/DockSidebar", () => ({ default: () => <div data-testid="dock">Dock</div> }));
vi.mock("@/chrome/TickerBar", () => ({
  default: () => <div data-testid="ticker-strip">Ticker</div>,
}));
vi.mock("@/chrome/ModeHonestyBar", () => ({
  default: () => <div data-testid="mode-honesty">Mode bar</div>,
}));
vi.mock("@/chrome/OperatorStatusStrip", () => ({ OperatorStatusStrip: () => null }));
vi.mock("@/chrome/OperatorIncidentProbes", () => ({ OperatorIncidentProbes: () => null }));
vi.mock("@/components/motion/PageTransition", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/welcome/DailyWelcome", () => ({ default: () => null }));
vi.mock("@/components/NoConnectionOverlay", () => ({ NoConnectionOverlay: () => null }));
vi.mock("@/components/CommandPalette/CommandPalette", () => ({ default: () => null }));
vi.mock("@/components/DocsSearch/DocsSearch", () => ({ default: () => null }));
vi.mock("@/components/Changelog/ChangelogViewer", () => ({ default: () => null }));
vi.mock("@/components/KeyboardShortcuts/KeyboardShortcutsDialog", () => ({ default: () => null }));
vi.mock("@/hooks/useGlobalKeys", () => ({ default: () => undefined }));
vi.mock("@/hooks/useWsBridge", () => ({ useWsBridge: () => undefined }));
vi.mock("@/hooks/useDemoFeed", () => ({ useDemoFeed: () => undefined }));
vi.mock("@/hooks/useTickerFallback", () => ({ useTickerFallback: () => undefined }));
vi.mock("@/hooks/usePrevClose", () => ({ usePrevClose: () => undefined }));
vi.mock("@/hooks/useTradingStoreSync", () => ({ useTradingStoreSync: () => undefined }));
vi.mock("@/hooks/useBrokerAccounts", () => ({ useBrokerAccounts: () => undefined }));
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  useNotificationFeed: () => undefined,
}));

import AppLayout from "../AppLayout";
import WelcomeRoute from "../WelcomeRoute";
import ProtectedRoute from "../ProtectedRoute";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { useSettingsStore } from "@/stores/settingsStore";

const DESK_MARKER = "Open position RELIANCE";

function sessionJwt(mode: string): string {
  const payload = btoa(JSON.stringify({ mode, type: "session" }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
  return `header.${payload}.sig`;
}

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function DeskPanel() {
  return <p>{DESK_MARKER}</p>;
}

function renderDesk() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter([
    { path: "/welcome", element: <WelcomeRoute /> },
    {
      element: <ProtectedRoute><AppLayout /></ProtectedRoute>,
      children: [
        { path: "/trade", element: <DeskPanel /> },
        { path: "/home", element: <DeskPanel /> },
      ],
    },
  ], { initialEntries: ["/trade"] });

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("idle lock route", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-10T02:26:00.000Z"));
    sessionStorage.clear();
    localStorage.clear();
    Object.defineProperty(window, "innerWidth", { value: 1920, writable: true });
    useAuthStore.setState({
      status: "unknown",
      token: null,
      reauthToken: null,
      username: null,
      expiresAt: null,
      lastActivity: Date.now(),
      sessionGeneration: 0,
      _expiryTimerId: null,
    });
    useModeStore.setState({ mode: "practice" });
    useSettingsStore.setState({ persona: "trader" });
  });

  afterEach(() => {
    const timerId = useAuthStore.getState()._expiryTimerId;
    if (timerId !== null) clearTimeout(timerId);
    vi.useRealTimers();
  });

  it("locks after the idle timeout, unmounts the desk, then PIN unlock restores the session", async () => {
    useAuthStore.getState().setLoggedIn(sessionJwt("practice"), "testuser", "2026-09-10T18:00:00.000Z");
    const expiryTimer = useAuthStore.getState()._expiryTimerId;
    if (expiryTimer !== null) clearTimeout(expiryTimer);
    useAuthStore.setState({ _expiryTimerId: null, lastActivity: Date.now() });

    renderDesk();
    expect(screen.getByText(DESK_MARKER)).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(6 * 60 * 1000);
    });

    expect(useAuthStore.getState().status).toBe("pin-required");
    expect(screen.queryByText(DESK_MARKER)).not.toBeInTheDocument();
    expect(screen.queryByTestId("topbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("dock")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ticker-strip")).not.toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    expect(screen.getByRole("heading", { name: "Practice desk locked" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Quick Unlock" })).not.toBeInTheDocument();
    expect(screen.getByText("Quick Unlock")).toBeInTheDocument();
    expect(useModeStore.getState().mode).toBe("practice");

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        status: "success",
        data: { token: "restored-practice-jwt", mode: "practice", live_mode_unlocked: false },
      }),
    );

    vi.useRealTimers();
    fireEvent.change(screen.getByLabelText("Quick Unlock"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlock Practice desk" }));

    await waitFor(() => expect(screen.getByText(DESK_MARKER)).toBeInTheDocument());
    expect(useAuthStore.getState().status).toBe("logged-in");
    expect(useAuthStore.getState().token).toBe("restored-practice-jwt");
    expect(useModeStore.getState().mode).toBe("practice");
    expect(screen.queryByRole("heading", { name: "Practice desk locked" })).not.toBeInTheDocument();
  });
});
