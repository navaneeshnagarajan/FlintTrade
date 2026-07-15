/**
 * UpdatesSection.test.tsx — desktop in-app updater (Settings -> Updates).
 *
 * Covers: hidden on web builds, running version shown, the signed native
 * one-click update flow (preferred when the shell check succeeds, silent
 * fallback when it rejects), the managed backend payload flow (one-click
 * apply, graceful silence when the check rejects, offered alongside the
 * shell update), the binary installer update flow, the source-rebuild
 * fallback, missing-updater one-liner fallback, honest rate-limit errors,
 * and desktop-only section registration.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

vi.mock("@/lib/desktopShell", () => ({
  isDesktopShell: vi.fn(() => false),
  invokeDesktopCommand: vi.fn(),
  openExternalUrl: vi.fn(),
}));

import { invokeDesktopCommand, isDesktopShell } from "@/lib/desktopShell";
import { UpdatesSection, matchingPlatformAsset } from "../UpdatesSection";
import { buildSections } from "../settingsConfig";

const mockIsDesktopShell = vi.mocked(isDesktopShell);
const mockInvoke = vi.mocked(invokeDesktopCommand);

function releaseManifest(tag = "v0.7.0"): Parameters<typeof matchingPlatformAsset>[0] {
  return {
    tag,
    version: tag.replace(/^v/, ""),
    channel: "beta",
    prerelease: true,
    html_url: "https://github.com/navaneeshnagarajan/FlintTrade/releases/tag/v0.7.0",
    assets: [
      {
        os: "windows",
        arch: "x64",
        kind: "nsis",
        name: "FlintTrade_0.7.0_x64-setup.exe",
        size: 200,
        url: "https://example.invalid/win.exe",
      },
      {
        os: "macos",
        arch: "arm64",
        kind: "dmg",
        name: "FlintTrade_0.7.0_aarch64.dmg",
        size: 100,
        url: "https://example.invalid/mac.dmg",
      },
      {
        os: "linux",
        arch: "x64",
        kind: "appimage",
        name: "FlintTrade_0.7.0_amd64.AppImage",
        size: 300,
        url: "https://example.invalid/linux.AppImage",
      },
    ],
  };
}

function mockShellState(
  state: {
    app_version: string;
    platform_os?: string | null;
    platform_arch?: string | null;
    src_dir: string | null;
    installer_script?: string | null;
  } = {
    app_version: "0.6.0-beta.1",
    platform_os: "windows",
    platform_arch: "x64",
    src_dir: "/home/op/.flinttrade/src/FlintTrade",
    installer_script: "/Applications/FlintTrade.app/Contents/Resources/flinttrade-install.sh",
  },
) {
  mockInvoke.mockImplementation((command: string) => {
    if (command === "updater_state") return Promise.resolve(state);
    // Default shell: no signed native updater (unsigned/dev build or an older
    // shell without the command) — the section must fall back silently.
    if (command === "check_native_update") return Promise.reject(new Error("updater unavailable"));
    return Promise.resolve(undefined);
  });
}

function mockNativeShell(
  check: { available: boolean; version: string | null; notes: string | null },
  apply: () => Promise<unknown> = () => new Promise(() => {}),
) {
  mockInvoke.mockImplementation((command: string) => {
    if (command === "updater_state") {
      return Promise.resolve({
        app_version: "0.6.0-beta.1",
        platform_os: "windows",
        platform_arch: "x64",
        src_dir: null,
        installer_script: null,
      });
    }
    if (command === "check_native_update") return Promise.resolve(check);
    // A successful apply restarts the app, so its promise never resolves.
    if (command === "apply_native_update") return apply();
    return Promise.resolve(undefined);
  });
}

function mockPayloadShell(
  options: {
    native?: { available: boolean; version: string | null; notes: string | null };
    payloadCheck: { available: boolean; version: string | null; size: number | null } | Error;
    apply?: () => Promise<unknown>;
  },
) {
  const native = options.native ?? { available: false, version: null, notes: null };
  const apply = options.apply ?? (() => new Promise(() => {}));
  mockInvoke.mockImplementation((command: string) => {
    if (command === "updater_state") {
      return Promise.resolve({
        app_version: "0.6.0-beta.1",
        platform_os: "windows",
        platform_arch: "x64",
        src_dir: null,
        installer_script: null,
      });
    }
    if (command === "check_native_update") return Promise.resolve(native);
    if (command === "check_payload_update") {
      return options.payloadCheck instanceof Error
        ? Promise.reject(options.payloadCheck)
        : Promise.resolve(options.payloadCheck);
    }
    // A successful apply restarts the app, so its promise never resolves.
    if (command === "apply_payload_update") return apply();
    return Promise.resolve(undefined);
  });
}

function mockRelease(manifest = releaseManifest()) {
  const response = {
    ok: true,
    status: 200,
    json: () => Promise.resolve(manifest),
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
  mockShellState();
  vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue("Windows");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

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
    expect(webIds).toEqual(desktopIds.filter((id) => id !== "updates"));
  });
});

describe("UpdatesSection platform asset matching", () => {
  it("selects platform-specific installer assets from the manifest", () => {
    const manifest = releaseManifest();
    expect(matchingPlatformAsset(manifest, "Windows NT")?.name).toMatch(/setup\.exe$/);
    expect(matchingPlatformAsset(manifest, "Macintosh; arm64")?.name).toMatch(/aarch64\.dmg$/);
    expect(matchingPlatformAsset(manifest, "X11; Linux x86_64")?.name).toMatch(/AppImage$/);
  });

  it("prefers shell-reported platform hints over ambiguous webview user agents", () => {
    const manifest = releaseManifest();
    expect(
      matchingPlatformAsset(
        manifest,
        { platform_os: "macos", platform_arch: "arm64" },
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      )?.name,
    ).toMatch(/aarch64\.dmg$/);
  });
});

describe("UpdatesSection version display", () => {
  it("shows the running version reported by the desktop shell", async () => {
    render(<UpdatesSection />);
    expect(await screen.findByText("v0.6.0-beta.1")).toBeInTheDocument();
    expect(mockInvoke).toHaveBeenCalledWith("updater_state");
  });
});

describe("UpdatesSection binary update flow", () => {
  it("invokes run_binary_update after confirming when a newer desktop release exists", async () => {
    mockRelease();
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();
    await user.click(await screen.findByRole("button", { name: /download & install update/i }));

    expect(await screen.findByText(/download the matching desktop package/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /install and relaunch/i }));
    await waitFor(() => expect(mockInvoke).toHaveBeenCalledWith("run_binary_update", { tag: "v0.7.0" }));
    expect(await screen.findByText(/installer update started/i)).toBeInTheDocument();
  });

  it("reports being up to date when the manifest tag is not newer", async () => {
    mockRelease(releaseManifest("v0.6.0-beta.1"));
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(await screen.findByText(/latest desktop release/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download & install update/i })).not.toBeInTheDocument();
  });

  it("surfaces the shell's refusal message when run_binary_update fails", async () => {
    mockRelease();
    mockInvoke.mockImplementation((command: string) => {
      if (command === "updater_state") {
        return Promise.resolve({
          app_version: "0.6.0-beta.1",
          src_dir: "/src",
          installer_script: "/resources/flinttrade-install.sh",
        });
      }
      return Promise.reject(new Error("No packaged installer script found"));
    });
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();
    await user.click(await screen.findByRole("button", { name: /download & install update/i }));
    await user.click(await screen.findByRole("button", { name: /install and relaunch/i }));

    expect(await screen.findByText(/no packaged installer script found/i)).toBeInTheDocument();
  });
});

describe("UpdatesSection native one-click flow", () => {
  it("prefers the shell's signed updater and never fetches the manifest when it succeeds", async () => {
    mockNativeShell({ available: true, version: "0.7.0", notes: "Bug fixes and improvements." });
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();

    const updateBtn = await screen.findByRole("button", { name: /update and restart/i });
    expect(screen.getByText(/v0\.7\.0/)).toBeInTheDocument();
    expect(screen.getByText("Bug fixes and improvements.")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();

    await user.click(updateBtn);
    await waitFor(() => expect(mockInvoke).toHaveBeenCalledWith("apply_native_update"));
    // Busy state: the apply promise never resolves (the shell restarts the app).
    expect(await screen.findByText(/updating — the app will restart itself\./i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /update and restart/i })).not.toBeInTheDocument();
  });

  it("reports up to date from the native check without fetching the manifest", async () => {
    mockNativeShell({ available: false, version: null, notes: null });
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(await screen.findByText(/latest desktop release/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("falls back to the channel release manifest when the native check rejects", async () => {
    // Default mockShellState rejects check_native_update (unsigned/dev build).
    mockRelease();
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();

    expect(await screen.findByRole("button", { name: /download & install update/i })).toBeInTheDocument();
    // v0.6.0-beta.1 carries a pre-release suffix, so the beta channel is used.
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/updater-beta/flinttrade-desktop-manifest.json",
      { headers: { Accept: "application/json" } },
    );
  });

  it("surfaces the shell's redacted message and re-offers the action when the install fails", async () => {
    mockNativeShell({ available: true, version: "0.7.0", notes: null }, () =>
      Promise.reject("The update could not be downloaded and verified — nothing was changed. Please try again."),
    );
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();
    await user.click(await screen.findByRole("button", { name: /update and restart/i }));

    expect(await screen.findByText(/could not be downloaded and verified/i)).toBeInTheDocument();
    // The busy state clears so the operator can retry.
    expect(screen.getByRole("button", { name: /update and restart/i })).toBeInTheDocument();
  });
});

describe("UpdatesSection managed backend payload flow", () => {
  it("offers the one-click backend update and invokes apply_payload_update", async () => {
    mockPayloadShell({ payloadCheck: { available: true, version: "0.7.1", size: 64 * 1024 * 1024 } });
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();

    const updateBtn = await screen.findByRole("button", { name: /update backend \(v0\.7\.1\)/i });
    // The shell itself is current — the payload path is offered alongside.
    expect(await screen.findByText(/latest desktop release/i)).toBeInTheDocument();
    expect(screen.getByText(/~64 MB/)).toBeInTheDocument();

    await user.click(updateBtn);
    await waitFor(() => expect(mockInvoke).toHaveBeenCalledWith("apply_payload_update"));
    // Busy state: the apply promise never resolves (the shell restarts the app).
    expect(
      await screen.findByText(/updating the backend — the app will restart itself\./i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /update backend/i })).not.toBeInTheDocument();
  });

  it("offers the shell update and the backend payload update together", async () => {
    mockPayloadShell({
      native: { available: true, version: "0.7.0", notes: null },
      payloadCheck: { available: true, version: "0.7.1", size: null },
    });
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();

    expect(await screen.findByRole("button", { name: /update and restart/i })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /update backend \(v0\.7\.1\)/i })).toBeInTheDocument();
  });

  it("ignores a rejected payload check gracefully", async () => {
    mockPayloadShell({ payloadCheck: new Error("payload updater unavailable") });
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();

    // The native check still resolves the outcome; no payload UI, no error.
    expect(await screen.findByText(/latest desktop release/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /update backend/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/payload updater unavailable/i)).not.toBeInTheDocument();
  });

  it("surfaces the shell's redacted message and re-offers the action when the payload apply fails", async () => {
    mockPayloadShell({
      payloadCheck: { available: true, version: "0.7.1", size: null },
      apply: () =>
        Promise.reject(
          "The backend update could not be downloaded and verified — nothing was changed. Please try again.",
        ),
    });
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();
    await user.click(await screen.findByRole("button", { name: /update backend/i }));

    expect(await screen.findByText(/could not be downloaded and verified/i)).toBeInTheDocument();
    // The busy state clears so the operator can retry.
    expect(screen.getByRole("button", { name: /update backend/i })).toBeInTheDocument();
  });
});

describe("UpdatesSection resilient update paths", () => {
  it("does not claim up to date when a version tag cannot be parsed", async () => {
    // Fail safe: an unparseable manifest tag must not be reported as current
    // (that would silently hide a real update).
    mockRelease(releaseManifest("nightly"));
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();

    expect(screen.queryByText(/latest desktop release/i)).not.toBeInTheDocument();
    expect(await screen.findByText(/could not determine/i)).toBeInTheDocument();
    // The update path is still offered rather than hidden.
    expect(screen.getByRole("button", { name: /download & install update/i })).toBeInTheDocument();
  });

  it("offers the one-click update when the client cannot match a platform asset but a script is present", async () => {
    // Shell reports linux/arm64; the manifest only ships linux x64, so the
    // client-side asset match fails — but the bundled installer script resolves
    // the correct asset server-side, so the update must not be hidden.
    mockShellState({
      app_version: "0.6.0-beta.1",
      platform_os: "linux",
      platform_arch: "arm64",
      src_dir: null,
      installer_script: "/opt/flinttrade/flinttrade-install.sh",
    });
    mockRelease();
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();

    const installBtn = await screen.findByRole("button", { name: /download & install update/i });
    expect(installBtn).toBeInTheDocument();
    // The website one-liner fallback must NOT be shown — there is an update path.
    expect(screen.queryByRole("button", { name: /copy install command/i })).not.toBeInTheDocument();
    // Generic copy is used since the client could not name the asset.
    expect(
      screen.getByText(/the bundled installer script will download the matching desktop package for this machine/i),
    ).toBeInTheDocument();

    await user.click(installBtn);
    await user.click(await screen.findByRole("button", { name: /install and relaunch/i }));
    await waitFor(() => expect(mockInvoke).toHaveBeenCalledWith("run_binary_update", { tag: "v0.7.0" }));
  });
});

describe("UpdatesSection source rebuild fallback", () => {
  it("keeps rebuild-from-source available when a source workspace exists", async () => {
    mockShellState({
      app_version: "0.6.0-beta.1",
      src_dir: "/home/op/.flinttrade/src/FlintTrade",
      installer_script: null,
    });
    mockRelease();
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    const user = await checkForUpdates();
    await user.click(await screen.findByRole("button", { name: /rebuild from source/i }));
    await user.click(await screen.findByRole("button", { name: /rebuild and relaunch/i }));

    await waitFor(() => expect(mockInvoke).toHaveBeenCalledWith("run_self_update"));
  });

  it("shows the copyable install one-liner when no update path is available", async () => {
    mockShellState({ app_version: "0.6.0-beta.1", src_dir: null, installer_script: null });
    mockRelease();
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(
      await screen.findByText("irm https://flinttrade.vercel.app/install.ps1 | iex"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy install command/i })).toBeInTheDocument();
  });
});

describe("UpdatesSection error handling", () => {
  it("reports release lookup rate limits honestly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, status: 403 } as unknown as Response)),
    );
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(await screen.findByText(/rate limited/i)).toBeInTheDocument();
  });

  it("reports a network failure honestly", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    render(<UpdatesSection />);
    await screen.findByText("v0.6.0-beta.1");

    await checkForUpdates();
    expect(await screen.findByText(/could not reach the flinttrade release manifest/i)).toBeInTheDocument();
  });
});
