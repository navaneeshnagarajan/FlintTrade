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
  fetchSetupServerState: vi.fn(),
  resumeFlintTradeSetup: vi.fn(),
  completeFlintTradeSetup: vi.fn(),
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
    status?: number;

    constructor(message: string, kind: string, status?: number) {
      super(message);
      this.kind = kind;
      this.status = status;
    }
  },
  setupFlintTradeAccount: mocks.setupFlintTradeAccount,
  openFlintTradeVault: mocks.openFlintTradeVault,
  enableFlintTradeTotp: mocks.enableFlintTradeTotp,
  fetchSetupServerState: mocks.fetchSetupServerState,
  resumeFlintTradeSetup: mocks.resumeFlintTradeSetup,
  completeFlintTradeSetup: mocks.completeFlintTradeSetup,
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
import { AccountSetupError } from "@/lib/setupAccountApi";
import { writePersistedAuthSession } from "@/lib/homeEntry";
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

async function renderSetup(
  ui: React.ReactElement = <SetupAccountRoute />,
): Promise<ReturnType<typeof render>> {
  const view = render(ui);
  await act(async () => {
    await Promise.resolve();
  });
  return view;
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
    mocks.fetchSetupServerState.mockResolvedValue({
      isSetup: false,
      vaultOpen: false,
      setupFinished: false,
    });
    mocks.resumeFlintTradeSetup.mockReset();
    mocks.completeFlintTradeSetup.mockResolvedValue(undefined);
    seedPracticeDesk();
    useModeStore.getState().setMode("explore");
    useAuthStore.getState().setLoggedIn("setup-explore-token", "operator", "");
  });

  it("shows Step 3 of 3 on the Practice desk and does not offer a Live unlock", async () => {
    await renderSetup();

    expect(screen.getByText("Step 3 of 3 - Practice desk")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Practice desk" })).toBeInTheDocument();
    expect(screen.queryByText("Your vault is set up and secured on this machine.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /live/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /explore/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set up / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue without a broker" })).not.toBeInTheDocument();
    expect(screen.queryByText("Trading defaults")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Position lot reference")).not.toBeInTheDocument();
  });

  it("does not let an optional deep link skip the vault", async () => {
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

    await renderSetup(
      <SetupAccountRoute requestedStep={2} requestedOptional={"broker" satisfies OptionalSetupPanel} />,
    );

    expect(screen.getByRole("heading", { name: "Vault" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Practice desk" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Step \d+ of [4-9]/)).not.toBeInTheDocument();
  });

  it("does not let a deep link skip account creation", async () => {
    localStorage.clear();
    useAuthStore.getState().setSetupRequired();

    await renderSetup(<SetupAccountRoute requestedStep={2} requestedOptional="broker" />);

    expect(screen.getByText("Step 1 of 3 - Create operator")).toBeInTheDocument();
    expect(screen.getByLabelText("Choose a username")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Practice desk" })).not.toBeInTheDocument();
  });

  it("upgrades the JWT to practice and opens the Practice desk", async () => {
    mocks.downgradeMode.mockResolvedValue("practice-token");

    await renderSetup();
    fireEvent.click(screen.getByRole("button", { name: "Open Practice desk" }));

    await waitFor(() =>
      expect(mocks.downgradeMode).toHaveBeenCalledWith("practice", "setup-explore-token"),
    );
    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith("/trade", { replace: true }),
    );
    expect(useAuthStore.getState().token).toBe("practice-token");
    expect(mocks.completeFlintTradeSetup).toHaveBeenCalledOnce();
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

    await renderSetup();
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
    await renderSetup();

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

  it("does not open an optional deep link before the Practice affirm", async () => {
    await renderSetup(<SetupAccountRoute requestedOptional="totp" />);

    expect(screen.getByText("Step 3 of 3 - Practice desk")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Practice desk" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /set up later/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue without a broker" })).not.toBeInTheDocument();
    expect(screen.queryByText("Trading defaults")).not.toBeInTheDocument();
  });

  it("keeps Start over on the Practice affirm", async () => {
    await renderSetup();

    expect(screen.getByRole("button", { name: "Start over (deletes this unfinished operator)" })).toBeInTheDocument();
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
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", data: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await renderSetup();
    fireEvent.click(screen.getByRole("button", { name: "Start over (deletes this unfinished operator)" }));
    expect(fetchSpy).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Password to start over"), {
      target: { value: "Strong1!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete and start over" }));

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
    await renderSetup();

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

    await renderSetup();
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

  it("does not offer Explore or Live as a first-run finish", async () => {
    await renderSetup();

    expect(screen.queryByRole("button", { name: /explore/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /unlock live|choose live|^live$/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Live is not part of setup/i)).toBeInTheDocument();
  });

  it("does not count later setup in the required-step fraction", async () => {
    await renderSetup();

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
    const first = await renderSetup();
    submitAccountCreation();
    await waitFor(() =>
      expect(screen.getByLabelText("Master password")).toBeInTheDocument(),
    );
    expect(screen.getByText("Step 2 of 3 - Vault")).toBeInTheDocument();

    first.unmount();
    const second = await renderSetup();
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
    await renderSetup();
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
    await renderSetup();
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

  it("restores the setup session after a reload and counts two steps remaining", async () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      vaultOpened: false,
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "operator",
      currentStep: 1,
    }));
    act(() => {
      useAuthStore.setState({
        status: "unknown",
        token: null,
        username: null,
        expiresAt: null,
        reauthToken: null,
      });
    });
    writePersistedAuthSession({
      token: "setup-token",
      username: "operator",
      expiresAt: "",
    });

    await renderSetup();

    expect(await screen.findByLabelText("Master password")).toBeInTheDocument();
    expect(useAuthStore.getState().token).toBe("setup-token");
    expect(screen.getByText("Step 2 of 3 - Vault")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 completed - 2 remaining")).toBeInTheDocument();
    expect(screen.queryByText(/A setup session is required/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Operator password")).not.toBeInTheDocument();
  });

  it("asks the operator to sign in when a reload has no setup session, and Start over deletes the account", async () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      vaultOpened: false,
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "operator",
      currentStep: 1,
    }));
    act(() => {
      useAuthStore.setState({
        status: "logged-out",
        token: null,
        username: null,
        expiresAt: null,
        reauthToken: null,
      });
    });
    sessionStorage.clear();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", data: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await renderSetup();

    expect(await screen.findByLabelText("Operator password")).toBeInTheDocument();
    expect(screen.queryByLabelText("Master password")).not.toBeInTheDocument();
    expect(screen.queryByText(/A setup session is required/i)).not.toBeInTheDocument();
    expect(screen.getByText("1 of 3 completed - 2 remaining")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start over (deletes this unfinished operator)" }));
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getAllByText("Enter your password to delete this unfinished operator.")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Password to start over"), {
      target: { value: "Strong1!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete and start over" }));

    expect(await screen.findByLabelText("Choose a username")).toBeInTheDocument();
    const resetCall = fetchSpy.mock.calls.find(([url]) => String(url).includes("/auth/setup/reset"));
    expect(resetCall?.[1]).toEqual(expect.objectContaining({
      body: JSON.stringify({ password: "Strong1!" }),
    }));
    expect(localStorage.getItem(PROGRESS_KEY)).toBeNull();
    expect(useAuthStore.getState().status).toBe("setup-required");
    fetchSpy.mockRestore();
  });

  it("signs the operator back in and continues when the setup session was lost", async () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      vaultOpened: false,
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "operator",
      currentStep: 1,
    }));
    act(() => {
      useAuthStore.setState({
        status: "logged-out",
        token: null,
        username: null,
        expiresAt: null,
        reauthToken: null,
      });
    });
    mocks.resumeFlintTradeSetup.mockResolvedValue({
      token: "resumed-setup-token",
      username: "operator",
    });

    await renderSetup();
    fireEvent.change(await screen.findByLabelText("Operator password"), {
      target: { value: "Strong1!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue setup" }));

    expect(await screen.findByLabelText("Master password")).toBeInTheDocument();
    expect(mocks.resumeFlintTradeSetup).toHaveBeenCalledWith("Strong1!");
    expect(useAuthStore.getState().token).toBe("resumed-setup-token");
    expect(screen.queryByText(/A setup session is required/i)).not.toBeInTheDocument();
  });

  it("skips the vault step when the vault is already open", async () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      vaultOpened: false,
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "operator",
      currentStep: 1,
    }));
    mocks.fetchSetupServerState.mockResolvedValue({
      isSetup: true,
      vaultOpen: true,
      vaultPresecured: true,
      setupFinished: false,
    });

    await renderSetup();

    expect(await screen.findByText("Step 2 of 2 - Practice desk")).toBeInTheDocument();
    expect(screen.getByText("1 of 2 completed - last step")).toBeInTheDocument();
    expect(screen.queryByText(/of 3/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Master password")).not.toBeInTheDocument();
    expect(screen.queryByText("Step 2 of 3 - Vault")).not.toBeInTheDocument();
    const quietLine = screen.getByText("Your vault is set up and secured on this machine.");
    const openPractice = screen.getByRole("button", { name: "Open Practice desk" });
    expect(
      quietLine.compareDocumentPosition(openPractice) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByText("The credential vault on this machine is already secured.")).not.toBeInTheDocument();
  });

  it("asks a fresh browser to continue when the server already has an operator", async () => {
    localStorage.clear();
    sessionStorage.clear();
    act(() => {
      useAuthStore.setState({
        status: "logged-out",
        token: null,
        username: null,
        expiresAt: null,
        reauthToken: null,
      });
    });
    mocks.fetchSetupServerState.mockResolvedValue({
      isSetup: true,
      vaultOpen: false,
      vaultPresecured: false,
      setupFinished: false,
    });

    await renderSetup();

    expect(await screen.findByRole("heading", { name: "Continue setup" })).toBeInTheDocument();
    expect(screen.getByText("This machine already has an operator. Sign in to finish setup.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose a username")).not.toBeInTheDocument();
    expect(screen.queryByText("Step 1 of 3 - Create operator")).not.toBeInTheDocument();
    expect(mocks.setupFlintTradeAccount).not.toHaveBeenCalled();
  });

  it.each([
    {
      name: "HTTP 429",
      error: new AccountSetupError("rate limit", "server", 429),
      title: "FlintTrade is busy",
      body: "FlintTrade is busy right now. Wait a moment, then retry.",
    },
    {
      name: "HTTP 500",
      error: new AccountSetupError("unavailable", "server", 500),
      title: "Can't check setup status",
      body: "FlintTrade answered, but setup status couldn't be read. Retry in a moment.",
    },
    {
      name: "HTTP 404",
      error: new AccountSetupError("missing", "server", 404),
      title: "Can't check setup status",
      body: "FlintTrade answered, but setup status couldn't be read. Retry in a moment.",
    },
    {
      name: "malformed JSON",
      error: new AccountSetupError("unexpected setup status", "server", 200),
      title: "Can't check setup status",
      body: "FlintTrade answered, but setup status couldn't be read. Retry in a moment.",
    },
    {
      name: "a 200 with missing fields",
      error: new AccountSetupError("unexpected setup status", "server", 200),
      title: "Can't check setup status",
      body: "FlintTrade answered, but setup status couldn't be read. Retry in a moment.",
    },
    {
      name: "a network error",
      error: new AccountSetupError("offline", "network"),
      title: "FlintTrade backend unavailable",
      body: "The FlintTrade backend did not answer. Start or restart the local FlintTrade backend, then retry.",
    },
    {
      name: "a truncated status body",
      error: new AccountSetupError("FlintTrade backend responded with HTTP 200.", "server", 200),
      title: "Can't check setup status",
      body: "FlintTrade answered, but setup status couldn't be read. Retry in a moment.",
    },
  ])("shows $name and does not open the fresh-install form", async ({ error, title, body }) => {
    localStorage.clear();
    useAuthStore.getState().setSetupRequired();
    mocks.fetchSetupServerState.mockRejectedValue(error);

    await renderSetup();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAccessibleName(title);
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.getByText(body)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Retry connection" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Choose a username")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Enter your email address")).not.toBeInTheDocument();
    expect(screen.queryByText("Step 1 of 3 - Create operator")).not.toBeInTheDocument();
    expect(screen.queryByText("Step 1 of 2 - Create operator")).not.toBeInTheDocument();
  });

  it("keeps Step 3 of 3 after the vault opens when it was not secured at the start", async () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      vaultOpened: true,
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "operator",
      currentStep: 2,
    }));
    mocks.fetchSetupServerState.mockResolvedValue({
      isSetup: true,
      vaultOpen: true,
      vaultPresecured: false,
      setupFinished: false,
    });

    await renderSetup();

    expect(await screen.findByText("Step 3 of 3 - Practice desk")).toBeInTheDocument();
    expect(screen.getByText("2 of 3 completed - last step")).toBeInTheDocument();
    expect(screen.queryByText(/of 2/)).not.toBeInTheDocument();
    expect(screen.queryByText("Your vault is set up and secured on this machine.")).not.toBeInTheDocument();
  });

  it("shows Continue setup when the vault submit is refused for a missing setup session", async () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      vaultOpened: false,
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "operator",
      currentStep: 1,
    }));
    mocks.openFlintTradeVault.mockRejectedValue(
      new AccountSetupError("A setup session is required.", "server", 401),
    );

    await renderSetup();

    expect(await screen.findByLabelText("Master password")).toBeInTheDocument();
    expect(screen.queryByText("Checking the vault…")).not.toBeInTheDocument();
    expect(mocks.openFlintTradeVault).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Master password"), {
      target: { value: "VaultKey123!" },
    });
    fireEvent.change(screen.getByLabelText("Confirm master password"), {
      target: { value: "VaultKey123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open vault" }));

    expect(await screen.findByRole("heading", { name: "Continue setup" })).toBeInTheDocument();
    expect(screen.getByText("This machine already has an operator. Sign in to finish setup.")).toBeInTheDocument();
    expect(screen.queryByText("A setup session is required.")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Choose a username")).not.toBeInTheDocument();
    expect(mocks.openFlintTradeVault).toHaveBeenCalledTimes(1);
    expect(mocks.openFlintTradeVault).toHaveBeenCalledWith("VaultKey123!");

    await act(async () => {
      await Promise.resolve();
    });
    expect(mocks.openFlintTradeVault).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "Continue setup" })).toBeInTheDocument();
    expect(screen.queryByText("A setup session is required.")).not.toBeInTheDocument();
  });

  it("sends one vault open when the form is submitted twice", async () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      vaultOpened: false,
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "operator",
      currentStep: 1,
    }));
    let release: ((value: { opened: true; alreadyPresent: false }) => void) | undefined;
    mocks.openFlintTradeVault.mockImplementation((password: string) => {
      if (!password) {
        return Promise.reject(new Error("Enter a master password of at least 8 characters."));
      }
      return new Promise((resolve) => {
        release = resolve;
      });
    });

    await renderSetup();
    expect(await screen.findByLabelText("Master password")).toBeInTheDocument();
    expect(mocks.openFlintTradeVault).not.toHaveBeenCalled();
    mocks.openFlintTradeVault.mockClear();

    fireEvent.change(screen.getByLabelText("Master password"), {
      target: { value: "VaultKey123!" },
    });
    fireEvent.change(screen.getByLabelText("Confirm master password"), {
      target: { value: "VaultKey123!" },
    });
    const form = screen.getByLabelText("Master password").closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    fireEvent.submit(form!);

    await waitFor(() => expect(mocks.openFlintTradeVault).toHaveBeenCalledTimes(1));
    expect(mocks.openFlintTradeVault).toHaveBeenCalledWith("VaultKey123!");

    await act(async () => {
      release?.({ opened: true, alreadyPresent: false });
      await Promise.resolve();
    });
    expect(mocks.openFlintTradeVault).toHaveBeenCalledTimes(1);
  });

  it("shows one Start over prompt on the vault step", async () => {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      accountCreated: true,
      vaultOpened: false,
      persona: null,
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "operator",
      currentStep: 1,
    }));
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "error", message: "A setup session is required." }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await renderSetup();

    expect(await screen.findByLabelText("Master password")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete account/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Delete account & start over")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Start over (deletes this unfinished operator)" })).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Start over (deletes this unfinished operator)" }));

    expect(screen.getAllByText("Enter your password to delete this unfinished operator.")).toHaveLength(1);
    expect(screen.getAllByLabelText("Password to start over")).toHaveLength(1);
    expect(screen.queryByText("Enter your password to delete this operator and start again.")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Confirm password to delete the account")).not.toBeInTheDocument();
    const deleteButton = screen.getByRole("button", { name: "Delete and start over" });
    expect(deleteButton.className).toMatch(/destructive/);
    const cancelButton = screen.getByRole("button", { name: "Cancel" });
    expect(cancelButton.compareDocumentPosition(deleteButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(fetchSpy).not.toHaveBeenCalled();

    fireEvent.click(cancelButton);
    expect(screen.queryByText("Enter your password to delete this unfinished operator.")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Password to start over")).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("does not update AITutorPill while rendering setup", async () => {
    const errors: unknown[][] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      errors.push(args);
    });
    function AITutorPill() {
      const status = useAuthStore((state) => state.status);
      return <div>{status}</div>;
    }
    act(() => {
      useAuthStore.setState({
        status: "unknown",
        token: null,
        username: null,
        expiresAt: null,
        reauthToken: null,
      });
    });
    writePersistedAuthSession({
      token: "setup-token",
      username: "operator",
      expiresAt: "",
    });

    render(
      <>
        <AITutorPill />
        <SetupAccountRoute />
      </>,
    );
    await act(async () => {
      await Promise.resolve();
    });

    const warning = errors
      .map((args) => args.map((part) => String(part)).join(" "))
      .join("\n");
    expect(warning).not.toMatch(/Cannot update a component/);
    spy.mockRestore();
  });

  it("keeps the two-step total stable from Create operator through Practice", async () => {
    localStorage.clear();
    useAuthStore.getState().setSetupRequired();
    let resolveState: (state: { isSetup: boolean; vaultOpen: boolean; setupFinished: boolean }) => void =
      () => {};
    mocks.fetchSetupServerState.mockReturnValue(
      new Promise((resolve) => {
        resolveState = resolve;
      }),
    );
    mocks.setupFlintTradeAccount.mockResolvedValue({
      token: "fresh-setup-token",
      totpUri: "otpauth://totp/FlintTrade:alice?secret=FRESHSEED",
      backupCodes: ["FRESH001"],
    });

    await renderSetup();

    expect(screen.queryByText(/of 3/)).not.toBeInTheDocument();
    expect(screen.queryByText(/of 2/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Choose a username")).not.toBeInTheDocument();

    await act(async () => {
      resolveState({ isSetup: false, vaultOpen: true, setupFinished: false });
    });

    expect(await screen.findByText("Step 1 of 2 - Create operator")).toBeInTheDocument();
    expect(screen.queryByText(/of 3/)).not.toBeInTheDocument();
    expect(screen.queryByText("Your vault is set up and secured on this machine.")).not.toBeInTheDocument();

    submitAccountCreation();

    expect(await screen.findByText("Step 2 of 2 - Practice desk")).toBeInTheDocument();
    expect(screen.getByText("1 of 2 completed - last step")).toBeInTheDocument();
    expect(screen.queryByText(/of 3/)).not.toBeInTheDocument();
    expect(screen.queryByText("Step 2 of 3 - Vault")).not.toBeInTheDocument();
    const quietLine = screen.getByText("Your vault is set up and secured on this machine.");
    const openPractice = screen.getByRole("button", { name: "Open Practice desk" });
    expect(
      quietLine.compareDocumentPosition(openPractice) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("sends a signed-in operator to the desk after setup is complete", async () => {
    localStorage.clear();
    useAuthStore.getState().setLoggedIn("practice-token", "operator", "");
    mocks.fetchSetupServerState.mockResolvedValue({
      isSetup: true,
      vaultOpen: true,
      setupFinished: true,
    });

    await renderSetup();

    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith("/trade", { replace: true }),
    );
    expect(screen.queryByText("Step 1 of 3 - Create operator")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Choose a username")).not.toBeInTheDocument();
  });

  it("shows a completed state instead of step 1 when setup is finished and signed out", async () => {
    localStorage.clear();
    act(() => {
      useAuthStore.setState({
        status: "logged-out",
        token: null,
        username: null,
        expiresAt: null,
        reauthToken: null,
      });
    });
    mocks.fetchSetupServerState.mockResolvedValue({
      isSetup: true,
      vaultOpen: true,
      setupFinished: true,
    });

    await renderSetup();

    expect(await screen.findByText("Setup is complete. Sign in to open the desk.")).toBeInTheDocument();
    const signIn = screen.getByRole("link", { name: "Sign in" });
    expect(signIn).toHaveAttribute("href", "/welcome");
    expect(signIn.className).toContain("bg-primary");
    const settings = screen.getByRole("link", { name: "Open Settings" });
    expect(settings).toHaveAttribute("href", "/settings");
    expect(settings.className).toContain("border-border-default");
    expect(screen.queryByRole("link", { name: "Open the desk" })).not.toBeInTheDocument();
    expect(screen.queryByText("Step 1 of 3 - Create operator")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Choose a username")).not.toBeInTheDocument();
  });
});
