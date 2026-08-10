/**
 * SetupAccountRoute.test.tsx — the setup wizard's mode-completion step.
 *
 * Pins the Phase 1 G1 setup-wizard half: `/auth/setup` mints an EXPLORE JWT,
 * so choosing Practice at the end of setup MUST route through the server's
 * mode-transition endpoint (downgradeMode → updateToken) before the UI flips
 * to Practice — otherwise the first sandbox order is rejected 403
 * `mode_blocked` under a PRACTICE badge. On transition failure the wizard
 * must NOT finish with a mismatched UI mode; it shows a visible notice and
 * lets the user retry or pick Explore.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { AppMode } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  downgradeMode: vi.fn(),
  persistSetupChoices: vi.fn(() => "/trade"),
  setupFlintTradeAccount: vi.fn(),
}));

vi.mock("react-router", () => ({
  useNavigate: () => mocks.navigate,
  Link: ({ children, to, ...props }: Record<string, unknown>) => (
    <a href={String(to)} {...props}>{children as React.ReactNode}</a>
  ),
}));

vi.mock("@/lib/modeAuth", () => ({
  downgradeMode: mocks.downgradeMode,
}));

vi.mock("@/routes/setup/applySetupChoices", () => ({
  persistSetupChoices: mocks.persistSetupChoices,
}));

vi.mock("@/lib/setupAccountApi", () => ({
  AccountSetupError: class AccountSetupError extends Error {
    kind: string;

    constructor(message: string, kind: string) {
      super(message);
      this.kind = kind;
    }
  },
  setupFlintTradeAccount: mocks.setupFlintTradeAccount,
}));

// Keep the shell light — Meteors/Particles animate on canvas.
vi.mock("@/components/layout/PublicRouteShell", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// Stub the mode picker: the wizard's contract is its `onSelect(mode)` callback.
vi.mock("@/routes/ModeSelectRoute", () => ({
  __esModule: true,
  default: ({
    onSelect,
    initialMode,
  }: {
    onSelect: (mode: AppMode, token?: string) => void;
    initialMode?: AppMode;
  }) => (
    <div>
      <output aria-label="Initial setup mode">{initialMode ?? "explore"}</output>
      <button onClick={() => onSelect("explore")}>pick-explore</button>
      <button onClick={() => onSelect("practice")}>pick-practice</button>
      <button onClick={() => onSelect("live", "live-token")}>pick-live</button>
    </div>
  ),
}));

import SetupAccountRoute, { clearSessionRecoveryMaterialForTests } from "../SetupAccountRoute";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";

const PROGRESS_KEY = "flinttrade:setup-progress";

/** Seed persisted wizard progress so the route renders the final mode step. */
function seedModeStepProgress(): void {
  localStorage.setItem(
    PROGRESS_KEY,
    JSON.stringify({
      accountCreated: true,
      totpUri: "otpauth://totp/x?secret=ABC",
      backupCodes: ["AAAA1111"],
      persona: "trader",
      connection: {
        host: "http://localhost:5000",
        port: "5000",
        apiKey: "legacy-browser-secret",
        wsPort: "8765",
      },
      trading: null,
      risk: null,
      mode: null,
      displayName: "nav",
      currentStep: 6,
    }),
  );
}

function submitAccountCreation(): void {
  fireEvent.change(screen.getByLabelText("Choose a username"), {
    target: { value: "alice" },
  });
  fireEvent.change(screen.getByLabelText("Enter your email address"), {
    target: { value: "alice@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Create a strong password"), {
    target: { value: "Strong1!" },
  });
  fireEvent.change(screen.getByLabelText("Confirm your password"), {
    target: { value: "Strong1!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
}

describe("SetupAccountRoute — mode completion (Phase 1 G1, setup half)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    clearSessionRecoveryMaterialForTests();
    mocks.navigate.mockReset();
    mocks.downgradeMode.mockReset();
    mocks.persistSetupChoices.mockClear();
    mocks.setupFlintTradeAccount.mockReset();
    seedModeStepProgress();
    useModeStore.getState().setMode("explore");
    useAuthStore.getState().setLoggedIn("setup-explore-token", "nav", "");
  });

  it("restores a valid canonical mode deep link on the current mode step", () => {
    render(<SetupAccountRoute requestedStep={6} requestedMode="practice" />);

    expect(screen.getByLabelText("Initial setup mode")).toHaveTextContent("practice");
  });

  it("restores a valid completed-step deep link without skipping unfinished steps", () => {
    render(<SetupAccountRoute requestedStep={3} />);

    expect(screen.getByRole("tablist", { name: "Connection mode" })).toBeInTheDocument();
    expect(screen.queryByText("pick-practice")).not.toBeInTheDocument();
  });

  it("does not let a deep link skip account creation", () => {
    localStorage.clear();
    useAuthStore.getState().setSetupRequired();

    render(<SetupAccountRoute requestedStep={6} requestedMode="live" />);

    expect(screen.getByLabelText("Choose a username")).toBeInTheDocument();
    expect(screen.queryByLabelText("Initial setup mode")).not.toBeInTheDocument();
  });

  it("upgrades the JWT to practice via the mode-transition endpoint before finishing", async () => {
    mocks.downgradeMode.mockResolvedValue("practice-token");

    render(<SetupAccountRoute />);
    fireEvent.click(screen.getByText("pick-practice"));

    await waitFor(() =>
      expect(mocks.downgradeMode).toHaveBeenCalledWith("practice", "setup-explore-token"),
    );
    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith("/welcome", { replace: true }),
    );
    expect(useAuthStore.getState().token).toBe("practice-token");
    expect(useModeStore.getState().mode).toBe("practice");
    // Setup finished — persisted progress cleared.
    expect(localStorage.getItem(PROGRESS_KEY)).toBeNull();
  });

  it("does not finish setup when the Practice response belongs to a logged-out session", async () => {
    let finishDowngrade: ((token: string) => void) | undefined;
    mocks.downgradeMode.mockReturnValue(
      new Promise<string>((resolve) => {
        finishDowngrade = resolve;
      }),
    );

    render(<SetupAccountRoute />);
    fireEvent.click(screen.getByText("pick-practice"));
    await waitFor(() => expect(mocks.downgradeMode).toHaveBeenCalledOnce());

    act(() => useAuthStore.getState().setLoggedOut());
    await act(async () => {
      finishDowngrade?.("late-practice-token");
      await Promise.resolve();
    });

    expect(useAuthStore.getState()).toMatchObject({
      status: "logged-out",
      token: null,
      username: null,
    });
    expect(useModeStore.getState().mode).toBe("explore");
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it("removes recovery material and broker credentials from persisted progress", async () => {
    render(<SetupAccountRoute />);

    await waitFor(() => {
      const progress = JSON.parse(localStorage.getItem(PROGRESS_KEY) ?? "{}");
      expect(progress).not.toHaveProperty("totpUri");
      expect(progress).not.toHaveProperty("backupCodes");
      expect(progress.connection).toEqual({
        host: "http://localhost:5000",
        port: "5000",
        wsPort: "8765",
      });
      expect(JSON.stringify(progress)).not.toContain("legacy-browser-secret");
      expect(JSON.stringify(progress)).not.toContain("AAAA1111");
      expect(JSON.stringify(progress)).not.toContain("secret=ABC");
    });
  });

  it("requires password-backed 2FA regeneration after a recovery-step reload", () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      totpUri: "otpauth://totp/x?secret=LEGACY",
      backupCodes: ["LEGACY01"],
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "nav",
      currentStep: 1,
    }));

    render(<SetupAccountRoute />);

    expect(screen.getByRole("alert")).toHaveTextContent(/not retained/i);
    expect(screen.getByRole("button", { name: /show QR code/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reset 2FA/i })).toBeEnabled();
  });

  it("does not finish setup under a Practice badge when the transition fails", async () => {
    mocks.downgradeMode.mockRejectedValue(new Error("mode downgrade to practice failed (503)"));

    render(<SetupAccountRoute />);
    fireEvent.click(screen.getByText("pick-practice"));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/Practice mode could not be enabled/i),
    );
    // No navigation, no mode flip, token untouched — UI and JWT stay in lockstep.
    expect(mocks.navigate).not.toHaveBeenCalled();
    expect(useModeStore.getState().mode).toBe("explore");
    expect(useAuthStore.getState().token).toBe("setup-explore-token");
    // Progress kept so the user can retry or pick Explore.
    expect(localStorage.getItem(PROGRESS_KEY)).not.toBeNull();
  });

  it("finishes in explore without calling the mode-transition endpoint", async () => {
    render(<SetupAccountRoute />);
    fireEvent.click(screen.getByText("pick-explore"));

    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith("/welcome", { replace: true }),
    );
    expect(mocks.downgradeMode).not.toHaveBeenCalled();
    expect(useModeStore.getState().mode).toBe("explore");
  });

  it("installs the live session token and lands on the workspace for live", async () => {
    render(<SetupAccountRoute />);
    fireEvent.click(screen.getByText("pick-live"));

    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith("/trade", { replace: true }),
    );
    expect(mocks.downgradeMode).not.toHaveBeenCalled();
    expect(useAuthStore.getState().token).toBe("live-token");
    expect(useModeStore.getState().mode).toBe("live");
  });

  it("rejects a Live unlock response after the setup session is terminated", async () => {
    render(<SetupAccountRoute />);
    act(() => useAuthStore.getState().setLoggedOut());

    fireEvent.click(screen.getByText("pick-live"));
    await act(async () => Promise.resolve());

    expect(useAuthStore.getState()).toMatchObject({
      status: "logged-out",
      token: null,
      username: null,
    });
    expect(useModeStore.getState().mode).toBe("explore");
    expect(mocks.navigate).not.toHaveBeenCalled();
    expect(localStorage.getItem(PROGRESS_KEY)).not.toBeNull();
  });

  it("keeps the fresh QR seed through a route remount after account creation", async () => {
    // Installing the session token right after account creation flips the
    // auth store and remounts the route. Recovery material is never written
    // to browser storage, so before the in-memory session cache a brand-new
    // account landed on step 2 with the QR button disabled and the
    // misleading "closed or refreshed" message.
    localStorage.clear();
    useAuthStore.getState().setSetupRequired();
    mocks.setupFlintTradeAccount.mockResolvedValue({
      token: "fresh-setup-token",
      totpUri: "otpauth://totp/FlintTrade:alice?secret=FRESHSEED",
      backupCodes: ["FRESH001", "FRESH002"],
    });
    const first = render(<SetupAccountRoute />);
    submitAccountCreation();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /show QR code/i })).toBeEnabled(),
    );

    first.unmount();
    render(<SetupAccountRoute />);

    expect(screen.getByRole("button", { name: /show QR code/i })).toBeEnabled();
    expect(screen.queryByText(/not retained/i)).not.toBeInTheDocument();
  });

  it("does not install a late account-setup session or advance the wizard", async () => {
    localStorage.clear();
    useAuthStore.getState().setSetupRequired();
    let finishSetup: ((result: {
      token: string;
      totpUri: string;
      backupCodes: string[];
    }) => void) | undefined;
    mocks.setupFlintTradeAccount.mockReturnValue(
      new Promise((resolve) => {
        finishSetup = resolve;
      }),
    );
    render(<SetupAccountRoute />);
    submitAccountCreation();
    await waitFor(() => expect(mocks.setupFlintTradeAccount).toHaveBeenCalledOnce());
    act(() => useAuthStore.getState().setLoggedOut());

    await act(async () => {
      finishSetup?.({
        token: "late-setup-token",
        totpUri: "otpauth://totp/late",
        backupCodes: ["LATE0001"],
      });
      await Promise.resolve();
    });

    expect(useAuthStore.getState()).toMatchObject({
      status: "logged-out",
      token: null,
      username: null,
    });
    expect(screen.getByLabelText("Choose a username")).toBeInTheDocument();
  });

  it("does not let a late tokenless setup response log out a newer session", async () => {
    localStorage.clear();
    useAuthStore.getState().setSetupRequired();
    let finishSetup: ((result: {
      token: string;
      totpUri: string;
      backupCodes: string[];
    }) => void) | undefined;
    mocks.setupFlintTradeAccount.mockReturnValue(
      new Promise((resolve) => {
        finishSetup = resolve;
      }),
    );
    render(<SetupAccountRoute />);
    submitAccountCreation();
    await waitFor(() => expect(mocks.setupFlintTradeAccount).toHaveBeenCalledOnce());
    act(() => useAuthStore.getState().setLoggedIn("newer-token", "bob", ""));

    await act(async () => {
      finishSetup?.({ token: "", totpUri: "", backupCodes: [] });
      await Promise.resolve();
    });

    expect(useAuthStore.getState()).toMatchObject({
      status: "logged-in",
      token: "newer-token",
      username: "bob",
    });
    expect(screen.getByLabelText("Choose a username")).toBeInTheDocument();
  });
});
