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
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { AppMode } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  downgradeMode: vi.fn(),
  persistSetupChoices: vi.fn(() => "/trade"),
}));

vi.mock("react-router-dom", () => ({
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

// Keep the shell light — Meteors/Particles animate on canvas.
vi.mock("@/components/layout/PublicRouteShell", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// Stub the mode picker: the wizard's contract is its `onSelect(mode)` callback.
vi.mock("@/routes/ModeSelectRoute", () => ({
  __esModule: true,
  default: ({ onSelect }: { onSelect: (mode: AppMode, token?: string) => void }) => (
    <div>
      <button onClick={() => onSelect("explore")}>pick-explore</button>
      <button onClick={() => onSelect("practice")}>pick-practice</button>
      <button onClick={() => onSelect("live", "live-token")}>pick-live</button>
    </div>
  ),
}));

import SetupAccountRoute from "../SetupAccountRoute";
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
      connection: null,
      trading: null,
      risk: null,
      mode: null,
      displayName: "nav",
      currentStep: 6,
    }),
  );
}

describe("SetupAccountRoute — mode completion (Phase 1 G1, setup half)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    mocks.navigate.mockReset();
    mocks.downgradeMode.mockReset();
    mocks.persistSetupChoices.mockClear();
    seedModeStepProgress();
    useModeStore.getState().setMode("explore");
    useAuthStore.getState().setLoggedIn("setup-explore-token", "nav", "");
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
});
