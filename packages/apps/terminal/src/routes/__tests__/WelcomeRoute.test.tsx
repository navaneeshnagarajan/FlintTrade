/**
 * WelcomeRoute.test.tsx
 *
 * Smoke tests for the cinematic welcome screen.
 * Mocks framer-motion, stores, Magic UI, and Aceternity UI.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const {
  mockNavigate,
  mockSetMode,
  mockSetLoggedIn,
  mockSetSetupRequired,
  mockSetLoggedOut,
  authState,
} = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockSetMode: vi.fn(),
  mockSetLoggedIn: vi.fn(),
  mockSetSetupRequired: vi.fn(),
  mockSetLoggedOut: vi.fn(),
  authState: { status: "setup-required" as string },
}));

vi.mock("react-router", () => ({
  useNavigate: () => mockNavigate,
  Link: ({ children, to, ...props }: Record<string, unknown>) => (
    <a href={String(to)} {...props}>{children as React.ReactNode}</a>
  ),
}));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, variants: _v, transition: _t, whileHover: _w, layout: _l, ...rest } = props;
      return <div {...rest}>{children as React.ReactNode}</div>;
    },
    span: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <span {...rest}>{children as React.ReactNode}</span>;
    },
    button: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <button {...rest}>{children as React.ReactNode}</button>;
    },
    p: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, transition: _t, ...rest } = props;
      return <p {...rest}>{children as React.ReactNode}</p>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0.1, normal: 0.2, slow: 0.3 },
    ease: { enter: [0, 0, 1, 1], exit: [0, 0, 1, 1] },
    transitions: { fade: { duration: 0.2 } },
  },
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      activeThemeId: "default",
      mode: "dark",
      setMode: vi.fn(),
    }),
  ),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(
    vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
      selector({ status: authState.status }),
    ),
    {
      getState: () => ({
        status: authState.status,
        setSetupRequired: mockSetSetupRequired,
        setLoggedOut: mockSetLoggedOut,
        setLoggedIn: mockSetLoggedIn,
      }),
      setState: vi.fn(),
    },
  ),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: Object.assign(() => ({}), {
    getState: () => ({ setMode: mockSetMode }),
    setState: vi.fn(),
  }),
}));

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg data-testid="logo-icon" width={size} height={size} />
  ),
}));

vi.mock("@/components/magicui/particles", () => ({
  Particles: () => <div data-testid="particles" />,
}));

vi.mock("@/components/magicui/shimmer-button", () => ({
  ShimmerButton: ({ children, ...props }: Record<string, unknown>) => (
    <button {...props}>{children as React.ReactNode}</button>
  ),
}));

vi.mock("@/components/aceternity/meteors", () => ({
  Meteors: () => <div data-testid="meteors" />,
}));

vi.mock("@/routes/LoginRoute", () => ({
  default: () => <div data-testid="login-route" />,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { waitFor } from "@testing-library/react";
import { BRAND_REVEAL_TIMELINE, BRAND_SLOGAN_WORDS } from "@flinttrade/design-system/brand";

import WelcomeRoute, { CINEMATIC_STEP_SCHEDULE, SLOGAN } from "../WelcomeRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WelcomeRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.status = "setup-required";
  });

  it("renders the welcome heading", () => {
    render(<WelcomeRoute />);

    expect(screen.getByRole("heading", { name: "FlintTrade" })).toBeInTheDocument();
  });

  it("shows Get Started and Explore CTAs for setup-required users", () => {
    render(<WelcomeRoute />);

    expect(screen.getByText("Get Started")).toBeInTheDocument();
    expect(screen.getByLabelText("Try with sample data without creating an account")).toBeInTheDocument();
  });

  it("Try with sample data enters Home in Explore mode (not ExploreRoute landing)", () => {
      render(<WelcomeRoute />);

      fireEvent.click(screen.getByLabelText("Try with sample data without creating an account"));

      expect(mockSetMode).toHaveBeenCalledWith("explore");
      expect(mockSetLoggedIn).toHaveBeenCalledWith("demo-user", "Explorer", "");
      expect(mockNavigate).toHaveBeenCalledWith("/home");
      expect(mockNavigate).not.toHaveBeenCalledWith("/explore");
    });

  it("degrades gracefully when the backend auth probe fails (no infinite 'Checking workspace…')", async () => {
    // Regression: previously the .catch only recovered in DEV, so a production
    // build with an unreachable backend hung on "Checking workspace…" forever
    // with no path to Explore. The probe must now surface the setup/Explore
    // actions in every build on failure.
    authState.status = "unknown";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new Error("backend unreachable"));

    render(<WelcomeRoute />);

    await waitFor(() => expect(mockSetSetupRequired).toHaveBeenCalled());
    expect(fetchSpy).toHaveBeenCalledWith(
      "/ft-api/v1/auth/status",
      expect.objectContaining({ signal: expect.anything() }),
    );

    fetchSpy.mockRestore();
  });

  it("ignores an auth probe aborted by effect cleanup", async () => {
    authState.status = "unknown";
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      }),
    );

    const { unmount } = render(<WelcomeRoute />);
    unmount();
    await Promise.resolve();
    await Promise.resolve();

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(mockSetSetupRequired).not.toHaveBeenCalled();
    expect(mockSetLoggedOut).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});

describe("WelcomeRoute brand parity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.status = "setup-required";
  });

  it("derives the slogan words from the design-system brand copy", () => {
    expect(SLOGAN.map((word) => word.text)).toEqual([...BRAND_SLOGAN_WORDS]);
  });

  it("renders every brand slogan word in the cinematic reveal", () => {
    render(<WelcomeRoute />);

    for (const word of BRAND_SLOGAN_WORDS) {
      expect(
        screen.getByText(
          (_, element) =>
            element?.tagName === "SPAN" &&
            (element.textContent === word || element.textContent === `${word}.`),
        ),
      ).toBeInTheDocument();
    }
  });

  it("describes public testing as simulated, not sandbox", () => {
    render(<WelcomeRoute />);
    expect(screen.getByText(/simulated testing/i)).toBeInTheDocument();
    expect(screen.queryByText(/sandbox testing/i)).not.toBeInTheDocument();
  });

  it("derives the step machine schedule from the shared reveal timeline", () => {
    expect(CINEMATIC_STEP_SCHEDULE).toEqual([
      [1, BRAND_REVEAL_TIMELINE.sequenceStartMs],
      [2, BRAND_REVEAL_TIMELINE.logoMs],
      [3, BRAND_REVEAL_TIMELINE.wordmarkMs],
      [4, BRAND_REVEAL_TIMELINE.sloganMs],
      [5, BRAND_REVEAL_TIMELINE.contentMs],
    ]);
    // Pin the millisecond values so a design-system timing change is a
    // conscious, reviewed decision on both surfaces.
    expect(CINEMATIC_STEP_SCHEDULE.map(([, ms]) => ms)).toEqual([1000, 2200, 3280, 4200, 5080]);
  });

  it("schedules the cinematic step timers with the timeline delays", () => {
    const timeoutSpy = vi.spyOn(globalThis, "setTimeout");

    render(<WelcomeRoute />);

    const delays = timeoutSpy.mock.calls.map((call) => call[1]);
    for (const [, ms] of CINEMATIC_STEP_SCHEDULE) {
      expect(delays).toContain(ms);
    }
    timeoutSpy.mockRestore();
  });
});
