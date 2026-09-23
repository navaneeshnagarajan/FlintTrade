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
import type { OptionalSetupPanel } from "@/routes/setupRouting";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  downgradeMode: vi.fn(),
  persistSetupChoices: vi.fn(() => "/trade"),
  setupFlintTradeAccount: vi.fn(),
  openFlintTradeVault: vi.fn(),
  enableFlintTradeTotp: vi.fn(),
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
  openFlintTradeVault: mocks.openFlintTradeVault,
  enableFlintTradeTotp: mocks.enableFlintTradeTotp,
}));

// Keep the shell light — Meteors/Particles animate on canvas.
vi.mock("@/components/layout/PublicRouteShell", () => ({
  __esModule: true,
  default: ({ children, subtitle }: { children: React.ReactNode; subtitle?: string }) => (
    <div>
      {subtitle ? <p>{subtitle}</p> : null}
      {children}
    </div>
  ),
}));

import SetupAccountRoute, {
  clearSessionRecoveryMaterialForTests,
  PRACTICE_LATER_KEY,
  PracticeLaterSetup,
} from "../SetupAccountRoute";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";

const PROGRESS_KEY = "flinttrade:setup-progress";

/** Seed persisted progress on the Practice desk, after the vault is open. */
function seedPracticeDesk(): void {
  localStorage.setItem(
    PROGRESS_KEY,
    JSON.stringify({
      accountCreated: true,
      vaultOpened: true,
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
      displayName: "operator",
      currentStep: 2,
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

describe("SetupAccountRoute — mandatory Practice path", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    clearSessionRecoveryMaterialForTests();
    mocks.navigate.mockReset();
    mocks.downgradeMode.mockReset();
    mocks.persistSetupChoices.mockClear();
    mocks.setupFlintTradeAccount.mockReset();
    mocks.enableFlintTradeTotp.mockReset();
    mocks.openFlintTradeVault.mockImplementation(async (password: string) => {
      if (!password) {
        throw new Error("Enter a master password of at least 8 characters.");
      }
      return { opened: true, alreadyPresent: false };
    });
    seedPracticeDesk();
    useModeStore.getState().setMode("explore");
    useAuthStore.getState().setLoggedIn("setup-explore-token", "operator", "");
  });

  it("shows Step 3 of 3 on the Practice desk and does not offer a Live unlock", () => {
    render(<SetupAccountRoute />);

    expect(screen.getByText("Step 3 of 3 - Practice desk")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Practice desk" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /live/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /explore/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set up / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue without a broker" })).not.toBeInTheDocument();
    expect(screen.queryByText("Trading defaults")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Position lot reference")).not.toBeInTheDocument();
  });

  it("does not let an optional deep link skip the vault", () => {
    localStorage.setItem(
      PROGRESS_KEY,
      JSON.stringify({
        accountCreated: true,
        vaultOpened: false,
        persona: null,
        connection: null,
        trading: null,
        risk: null,
        mode: null,
        displayName: "operator",
        currentStep: 6,
      }),
    );

    render(<SetupAccountRoute requestedStep={2} requestedOptional={"broker" satisfies OptionalSetupPanel} />);

    expect(screen.getByRole("heading", { name: "Vault" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Practice desk" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of [4-9]/)).not.toBeInTheDocument();
  });

  it("does not let a deep link skip account creation", () => {
    localStorage.clear();
    useAuthStore.getState().setSetupRequired();

    render(<SetupAccountRoute requestedStep={2} requestedOptional="broker" />);

    expect(screen.getByText("Step 1 of 3 - Create operator")).toBeInTheDocument();
    expect(screen.getByLabelText("Choose a username")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Practice desk" })).not.toBeInTheDocument();
  });

  it("upgrades the JWT to practice and opens the Practice desk", async () => {
    mocks.downgradeMode.mockResolvedValue("practice-token");

    render(<SetupAccountRoute />);
    fireEvent.click(screen.getByRole("button", { name: "Open Practice desk" }));

    await waitFor(() =>
      expect(mocks.downgradeMode).toHaveBeenCalledWith("practice", "setup-explore-token"),
    );
    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith("/trade", { replace: true }),
    );
    expect(useAuthStore.getState().token).toBe("practice-token");
    expect(useModeStore.getState().mode).toBe("practice");
    expect(localStorage.getItem(PROGRESS_KEY)).toBeNull();
    expect(localStorage.getItem(PRACTICE_LATER_KEY)).toBe("1");
    expect(mocks.downgradeMode).not.toHaveBeenCalledWith("live", expect.anything());
  });

  it("does not finish setup when the Practice response belongs to a logged-out session", async () => {
    let finishDowngrade: ((token: string) => void) | undefined;
    mocks.downgradeMode.mockReturnValue(
      new Promise<string>((resolve) => {
        finishDowngrade = resolve;
      }),
    );

    render(<SetupAccountRoute />);
    fireEvent.click(screen.getByRole("button", { name: "Open Practice desk" }));
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

  it("does not open an optional deep link before the Practice affirm", () => {
    render(<SetupAccountRoute requestedOptional="totp" />);

    expect(screen.getByText("Step 3 of 3 - Practice desk")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Practice desk" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /set up later/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue without a broker" })).not.toBeInTheDocument();
    expect(screen.queryByText("Trading defaults")).not.toBeInTheDocument();
  });

  it("keeps Start over on the Practice affirm", () => {
    render(<SetupAccountRoute />);

    expect(screen.getByRole("button", { name: "Start over" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /set up later/i })).not.toBeInTheDocument();
  });

  it("Start over wipes the unfinished account so setup can begin again", async () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      totpUri: "",
      backupCodes: [],
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "operator",
      currentStep: 1,
    }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", data: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<SetupAccountRoute />);
    fireEvent.click(screen.getByRole("button", { name: "Start over" }));

    await waitFor(() =>
      expect(screen.getByLabelText("Choose a username")).toBeInTheDocument(),
    );
    expect(fetchSpy.mock.calls.some(([url]) => String(url).includes("/auth/setup/reset"))).toBe(true);
    expect(localStorage.getItem(PROGRESS_KEY)).toBeNull();
    expect(useAuthStore.getState().status).toBe("setup-required");
    fetchSpy.mockRestore();
  });

  it("leaves optional setup for the Practice desk", async () => {
    mocks.downgradeMode.mockResolvedValue("practice-token");
    render(<SetupAccountRoute />);

    expect(screen.queryByRole("button", { name: "Skip Two-factor authentication" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip Broker connect" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Practice desk" }));

    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith("/trade", { replace: true }),
    );
    expect(localStorage.getItem(PRACTICE_LATER_KEY)).toBe("1");
  });

  it("does not finish setup under a Practice badge when the transition fails", async () => {
    mocks.downgradeMode.mockRejectedValue(new Error("mode downgrade to practice failed (503)"));

    render(<SetupAccountRoute />);
    fireEvent.click(screen.getByRole("button", { name: "Open Practice desk" }));

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

  it("does not offer Explore or Live as a first-run finish", () => {
    render(<SetupAccountRoute />);

    expect(screen.queryByRole("button", { name: /explore/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /unlock live|choose live|^live$/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Live is not part of setup/i)).toBeInTheDocument();
  });

  it("does not count later setup in the required-step fraction", () => {
    render(<SetupAccountRoute />);

    expect(screen.getByText("Step 3 of 3 - Practice desk")).toBeInTheDocument();
    expect(screen.queryByText("Optional")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set up Monitoring" })).not.toBeInTheDocument();
  });

  it("keeps the fresh QR seed through a route remount until authenticator setup", async () => {
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
      expect(screen.getByLabelText("Master password")).toBeInTheDocument(),
    );
    expect(screen.getByText("Step 2 of 3 - Vault")).toBeInTheDocument();

    first.unmount();
    const second = render(<SetupAccountRoute />);
    await waitFor(() =>
      expect(screen.getByLabelText("Master password")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("Master password"), {
      target: { value: "VaultKey123!" },
    });
    fireEvent.change(screen.getByLabelText("Confirm master password"), {
      target: { value: "VaultKey123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open vault" }));
    await waitFor(() =>
      expect(screen.getByText("Step 3 of 3 - Practice desk")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Set up Two-factor authentication" })).not.toBeInTheDocument();

    mocks.downgradeMode.mockResolvedValue("practice-token");
    fireEvent.click(screen.getByRole("button", { name: "Open Practice desk" }));
    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith("/trade", { replace: true }),
    );
    second.unmount();

    render(<PracticeLaterSetup />);
    fireEvent.click(screen.getByRole("button", { name: "Set up Two-factor authentication" }));

    expect(screen.getByRole("button", { name: /show QR code/i })).toBeEnabled();
    expect(screen.queryByText(/not retained/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of \d+/)).not.toBeInTheDocument();
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
