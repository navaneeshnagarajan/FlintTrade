import { mkdtemp, mkdir, readFile, realpath, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  FLINTTRADE_RELEASES_API,
  cancelDetachedInstaller,
  createGithubShellReleaseSource,
  createNodeShellInstallerHandoff,
  macosBundlePathForExecutable,
  shellInstallerEnvironment,
  windowsInstallDirectoryForExecutable,
} from "./shell-update-io";

describe("GitHub shell release source", () => {
  it("accepts only bounded official GitHub release metadata", async () => {
    const response = new Response(JSON.stringify([{
      assets: [{
        browser_download_url:
          "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v1.0.0/SHA256SUMS.txt",
        digest: "sha256:" + "a".repeat(64),
        name: "SHA256SUMS.txt",
      }],
      draft: false,
      prerelease: false,
      tag_name: "v1.0.0",
    }]));
    Object.defineProperty(response, "url", { value: FLINTTRADE_RELEASES_API });
    const fetcher = vi.fn(async () => response);

    await expect(createGithubShellReleaseSource(fetcher).list(new AbortController().signal)).resolves.toEqual([{
      assets: [{
        digest: "sha256:" + "a".repeat(64),
        downloadUrl:
          "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v1.0.0/SHA256SUMS.txt",
        name: "SHA256SUMS.txt",
      }],
      draft: false,
      prerelease: false,
      tagName: "v1.0.0",
    }]);
    expect(fetcher).toHaveBeenCalledWith(FLINTTRADE_RELEASES_API, expect.objectContaining({
      redirect: "follow",
      signal: expect.any(AbortSignal),
    }));
  });

  it("rejects redirected metadata outside the official API endpoint", async () => {
    const response = new Response("[]");
    Object.defineProperty(response, "url", { value: "https://attacker.example/releases" });
    await expect(
      createGithubShellReleaseSource(async () => response).list(new AbortController().signal),
    ).rejects.toThrow(/official GitHub release metadata/i);
  });
});

describe("shell installer environment", () => {
  it("drops release overrides, credentials and build-mode knobs", () => {
    const environment = shellInstallerEnvironment({
      APPIMAGE: "/attacker/FlintTrade.AppImage",
      FLINTTRADE_ALLOW_LOCAL_ASSET: "1",
      FLINTTRADE_BUILD_FROM_SOURCE: "1",
      FLINTTRADE_GITHUB_RELEASES_API: "https://attacker.example/releases",
      GITHUB_TOKEN: "secret",
      HOME: "/home/operator",
      PATH: "/usr/bin",
    }, "linux", "/workspace/marker", 43127, undefined, "/apps/FlintTrade.AppImage");

    expect(environment).toEqual({
      APPIMAGE: "/apps/FlintTrade.AppImage",
      FLINTTRADE_UPDATE_HANDOFF: "/workspace/marker",
      FLINTTRADE_UPDATE_PARENT_PID: "43127",
      FLINTTRADE_YES: "1",
      HOME: "/home/operator",
      PATH: "/usr/bin",
    });
  });

  it("passes exactly one root-validated Linux target", () => {
    expect(shellInstallerEnvironment(
      { APPIMAGE: "/attacker/FlintTrade.AppImage", HOME: "/home/operator" },
      "linux",
      "/workspace/marker",
      43127,
      undefined,
      undefined,
      "/home/operator/.local/opt/flinttrade",
    )).toEqual({
      FLINTTRADE_UPDATE_HANDOFF: "/workspace/marker",
      FLINTTRADE_UPDATE_LINUX_EXTRACTED_ROOT: "/home/operator/.local/opt/flinttrade",
      FLINTTRADE_UPDATE_PARENT_PID: "43127",
      FLINTTRADE_YES: "1",
      HOME: "/home/operator",
    });
    expect(() => shellInstallerEnvironment(
      {},
      "linux",
      "/workspace/marker",
      43127,
      undefined,
      "/apps/FlintTrade.AppImage",
      "/home/operator/.local/opt/flinttrade",
    )).toThrow(/exactly one running shell target/i);
  });

  it("passes only the root-validated Windows installation directory", () => {
    expect(shellInstallerEnvironment(
      { FLINTTRADE_UPDATE_WINDOWS_INSTALL_DIR: "C:\\attacker" },
      "win32",
      "C:\\Users\\operator\\marker",
      43127,
      undefined,
      undefined,
      undefined,
      "D:\\Trading Apps\\FlintTrade",
    )).toMatchObject({
      FLINTTRADE_UPDATE_WINDOWS_INSTALL_DIR: "D:\\Trading Apps\\FlintTrade",
    });
  });

  it.runIf(process.platform !== "win32")("keeps a durable owner-only installer failure trail", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "flinttrade-shell-log-"));
    const privateRoot = path.join(root, "private");
    const resourcesDirectory = path.join(root, "resources");
    try {
      await mkdir(privateRoot, { mode: 0o700 });
      await mkdir(path.join(resourcesDirectory, "install"), { recursive: true });
      await writeFile(
        path.join(resourcesDirectory, "install", "flinttrade-install.sh"),
        "#!/bin/bash\nprintf 'deliberate installer failure\\n' >&2\nexit 7\n",
        { mode: 0o700 },
      );
      let currentExecutablePath: string | undefined;
      let currentLinuxAppDir: string | undefined;
      let currentLinuxAppImage: string | undefined;
      if (process.platform === "darwin") {
        currentExecutablePath = path.join(root, "Custom Apps", "FlintTrade.app", "Contents", "MacOS", "FlintTrade");
        await mkdir(path.dirname(currentExecutablePath), { recursive: true });
        await writeFile(currentExecutablePath, "test executable", { mode: 0o700 });
      } else if (process.platform === "linux") {
        currentLinuxAppImage = path.join(root, "FlintTrade.AppImage");
        await writeFile(currentLinuxAppImage, "test AppImage", { mode: 0o700 });
        currentLinuxAppDir = path.join(root, ".mount_FlintTrade");
        currentExecutablePath = path.join(currentLinuxAppDir, "FlintTrade");
        await mkdir(currentLinuxAppDir);
        await writeFile(currentExecutablePath, "test executable", { mode: 0o700 });
      }
      const handoff = createNodeShellInstallerHandoff({
        currentExecutablePath,
        currentLinuxAppDir,
        currentLinuxAppImage,
        platform: process.platform,
        privateRoot,
        resourcesDirectory,
        temporaryDirectory: root,
      });
      const marker = await handoff.createMarker();
      const attempt = await handoff.launch({ marker, releaseTag: "v1.2.3" });

      await expect(attempt.exited).resolves.toBe(7);
      await attempt.cleanup();
      const logPath = path.join(privateRoot, "shell-updates", "logs", "installer.log");
      await expect(readFile(logPath, "utf8")).resolves.toMatch(/v1\.2\.3[\s\S]*deliberate installer failure/);
      expect((await stat(logPath)).mode & 0o077).toBe(0);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });
});

describe("running shell target binding", () => {
  it("derives the exact FlintTrade bundle in user and custom application folders", () => {
    expect(macosBundlePathForExecutable(
      "/Users/operator/Applications/FlintTrade.app/Contents/MacOS/FlintTrade",
    )).toBe("/Users/operator/Applications/FlintTrade.app");
    expect(macosBundlePathForExecutable(
      "/Volumes/Trading Tools/Custom/FlintTrade.app/Contents/MacOS/FlintTrade",
    )).toBe("/Volumes/Trading Tools/Custom/FlintTrade.app");
  });

  it("rejects renamed and translocated macOS bundles", () => {
    expect(() => macosBundlePathForExecutable(
      "/Applications/FlintTrade Copy.app/Contents/MacOS/FlintTrade",
    )).toThrow(/not a supported FlintTrade/i);
    expect(() => macosBundlePathForExecutable(
      "/private/var/folders/AppTranslocation/session/d/FlintTrade.app/Contents/MacOS/FlintTrade",
    )).toThrow(/not a supported FlintTrade/i);
  });

  it("derives a legitimate custom Windows install but rejects unpacked executable names", () => {
    expect(windowsInstallDirectoryForExecutable(
      "D:\\Trading Apps\\FlintTrade\\FlintTrade.exe",
    )).toBe("D:\\Trading Apps\\FlintTrade");
    expect(() => windowsInstallDirectoryForExecutable(
      "D:\\qa\\win-unpacked\\electron.exe",
    )).toThrow(/not a supported FlintTrade/i);
  });

  it.runIf(process.platform !== "win32")("classifies managed AppRun as extracted, never as an AppImage", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "flinttrade-extracted-target-"));
    const homeDirectory = path.join(root, "home");
    const extractedRoot = path.join(homeDirectory, ".local", "opt", "flinttrade");
    const squashfsRoot = path.join(extractedRoot, "squashfs-root");
    const appRun = path.join(squashfsRoot, "AppRun");
    const executable = path.join(squashfsRoot, "FlintTrade");
    const privateRoot = path.join(root, "private");
    const resourcesDirectory = path.join(root, "resources");
    try {
      await mkdir(squashfsRoot, { recursive: true });
      await mkdir(privateRoot, { mode: 0o700 });
      await mkdir(path.join(resourcesDirectory, "install"), { recursive: true });
      await writeFile(appRun, "test AppRun", { mode: 0o700 });
      await writeFile(executable, "test executable", { mode: 0o700 });
      await writeFile(
        path.join(resourcesDirectory, "install", "flinttrade-install.sh"),
        "#!/bin/bash\nprintf 'APPIMAGE=%s\\nEXTRACTED=%s\\n' \"${APPIMAGE:-}\" \"${FLINTTRADE_UPDATE_LINUX_EXTRACTED_ROOT:-}\" >&2\nexit 7\n",
        { mode: 0o700 },
      );
      const handoff = createNodeShellInstallerHandoff({
        currentExecutablePath: executable,
        currentLinuxAppDir: squashfsRoot,
        currentLinuxAppImage: appRun,
        homeDirectory,
        platform: "linux",
        privateRoot,
        resourcesDirectory,
        temporaryDirectory: root,
      });
      const marker = await handoff.createMarker();
      const attempt = await handoff.launch({ marker, releaseTag: "v1.2.3" });
      await expect(attempt.exited).resolves.toBe(7);
      await attempt.cleanup();

      const log = await readFile(path.join(privateRoot, "shell-updates", "logs", "installer.log"), "utf8");
      expect(log).toContain("APPIMAGE=\n");
      expect(log).toContain(`EXTRACTED=${await realpath(extractedRoot)}\n`);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });
});

describe("detached installer cancellation proof", () => {
  function boundary() {
    return {
      alreadyExited: vi.fn(() => false),
      killPosixGroup: vi.fn(() => "sent" as const),
      killWindowsTree: vi.fn(async () => true),
      posixGroupExists: vi.fn(() => false),
      waitForExit: vi.fn(async () => true),
    };
  }

  it("rejects a failed Windows taskkill instead of abandoning a live updater", async () => {
    const process = boundary();
    process.killWindowsTree.mockResolvedValue(false);
    await expect(cancelDetachedInstaller("win32", process)).rejects.toThrow(/could not prove/i);
  });

  it("rejects a POSIX process group that survives SIGKILL", async () => {
    const process = boundary();
    process.waitForExit.mockResolvedValue(false);
    process.posixGroupExists.mockReturnValue(true);
    await expect(cancelDetachedInstaller("darwin", process)).rejects.toThrow(/survived forced termination/i);
    expect(process.killPosixGroup).toHaveBeenNthCalledWith(1, "SIGTERM");
    expect(process.killPosixGroup).toHaveBeenNthCalledWith(2, "SIGKILL");
  });
});
