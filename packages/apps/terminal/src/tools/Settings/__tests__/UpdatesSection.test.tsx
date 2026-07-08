/**
 * UpdatesSection.test.tsx — desktop in-app updater (Settings -> Updates).
 *
 * Covers: hidden on web builds, running version shown, the binary installer
 * update flow, the source-rebuild fallback, missing-updater one-liner fallback,
 * honest rate-limit errors, and desktop-only section registration.
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
