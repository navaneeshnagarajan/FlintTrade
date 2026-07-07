/**
 * UpdatesSection.test.tsx — desktop in-app updater (Settings → Updates).
 *
 * Covers: hidden on web builds, running version shown, the newer-version
 * confirm flow invoking run_self_update, the missing-workspace one-liner
 * fallback, honest rate-limit errors, and the settingsConfig registration
 * (section present only for desktop builds).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be before imports
// ---------------------------------------------------------------------------

vi.mock("@/lib/desktopShell", () => ({
  isDesktopShell: vi.fn(() => false),
  invokeDesktopCommand: vi.fn(),
  openExternalUrl: vi.fn(),
}));

import { invokeDesktopCommand, isDesktopShell } from "@/lib/desktopShell";
import { UpdatesSection } from "../UpdatesSection";
import { buildSections } from "../settingsConfig";

const mockIsDesktopShell = vi.mocked(isDesktopShell);
const mockInvoke = vi.mocked(invokeDesktopCommand);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockShellState(state: { app_version: string; src_dir: string | null }) {
  mockInvoke.mockImplementation((command: string) => {
    if (command === "updater_state") return Promise.resolve(state);
    return Promise.resolve(undefined);
  });
}

function mockGitHubTags(names: string[]) {
  const response = {
    ok: true,
    status: 200,
    json: () => Promise.resolve(names.map((name) => ({ name }))),
  } as unknown as Response;
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));
}

async function checkForUpdates() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /check for updates/i }));
  return user;
}

beforeEach(() => {
  mockIsDesktopShell.mockReturnValue(true);
  mockShellState({ app_version: "0.6.0-beta.1", src_dir: "/home/op/.flinttrade/src/FlintTrade" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Visibility
// ---------------------------------------------------------------------------

describe("UpdatesSection visibility", () => {
  it("renders nothing on web builds", () => {
    mockIsDesktopShell.mockReturnValue(false);
    const { container } = render(<UpdatesSection />);
    expect(container.firstChild).toBeNull();
    expect(mockInvoke).not.toHaveBeenCalled();
  });

  it("is registered as a Settings section only for the desktop shell", () => {
    const desktopIds = buildSections(true).map((s) => s.id);
    const webIds = buildSections(false).map((s) => s.id);
    expect(desktopIds).toContain("updates");
    expect(webIds).not.toContain("updates");
    // Everything else is identical between the two builds.
    expect(webIds).toEqual(desktopIds.filter((id) => id !== "updates"));
  });
});

// ---------------------------------------------------------------------------
// Version display
// ---------------------------------------------------------------------------

describe("UpdatesSection version display", () => {
  it("shows the running version reported by the desktop shell", async () => {
    render(<UpdatesSection />);
    expect(await screen.findByText("v0.6.0-beta.1")).toBeInTheDocument();
    expect(mockInvoke).toHaveBeenCalledWith("updater_state");
  });
});

// ---------------------------------------------------------------------------
// Update flow
// ---------------------------------------------------------------------------

describe("UpdatesSection update flow", () => {
  it("invokes run_self_update after confirming when a newer tag exists", async () => {
    mockGitHubTags(["v0.7.0", "v0.6.0-beta.1", "v0.5.2"]);
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();
    await user.click(await screen.findByRole("button", { name: /update & rebuild/i }));

    // Confirm dialog states the build-on-device consequences.
    expect(await screen.findByText(/roughly 10–20 minutes/i)).toBeInTheDocument();
    expect(screen.getByText(/close whilst the build runs/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /rebuild and relaunch/i }));
    await waitFor(() => expect(mockInvoke).toHaveBeenCalledWith("run_self_update"));
    expect(await screen.findByText(/update started/i)).toBeInTheDocument();
  });

  it("treats a release tag as newer than its own beta prerelease", async () => {
    mockGitHubTags(["v0.6.0"]);
    mockShellState({ app_version: "0.6.0-beta.1", src_dir: "/src" });
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(await screen.findByRole("button", { name: /update & rebuild/i })).toBeInTheDocument();
  });

  it("reports being up to date when no newer tag exists", async () => {
    mockGitHubTags(["v0.6.0-beta.1", "v0.5.0"]);
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(await screen.findByText(/latest release/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /update & rebuild/i })).not.toBeInTheDocument();
  });

  it("surfaces the shell's refusal message when run_self_update fails", async () => {
    mockGitHubTags(["v0.7.0"]);
    mockInvoke.mockImplementation((command: string) => {
      if (command === "updater_state") {
        return Promise.resolve({ app_version: "0.6.0-beta.1", src_dir: "/src" });
      }
      return Promise.reject(new Error("No source workspace found on this machine"));
    });
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();
    await user.click(await screen.findByRole("button", { name: /update & rebuild/i }));
    await user.click(await screen.findByRole("button", { name: /rebuild and relaunch/i }));

    expect(await screen.findByText(/no source workspace found/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Missing-workspace fallback
// ---------------------------------------------------------------------------

describe("UpdatesSection missing-workspace fallback", () => {
  it("shows the copyable install one-liner instead of the rebuild button", async () => {
    mockShellState({ app_version: "0.6.0-beta.1", src_dir: null });
    mockGitHubTags(["v0.7.0"]);
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(
      await screen.findByText("curl -fsSL https://flinttrade.vercel.app/install.sh | bash"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy install command/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /update & rebuild/i })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Honest network / rate-limit errors
// ---------------------------------------------------------------------------

describe("UpdatesSection error handling", () => {
  it("reports the GitHub rate limit honestly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, status: 403 } as unknown as Response)),
    );
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(await screen.findByText(/rate limit reached/i)).toBeInTheDocument();
  });

  it("reports a network failure honestly", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(await screen.findByText(/could not reach github/i)).toBeInTheDocument();
  });
});
