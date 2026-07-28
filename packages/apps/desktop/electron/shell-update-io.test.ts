import { mkdtemp, mkdir, readFile, readdir, realpath, rename, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";

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
  function releaseResponse(
    body: BodyInit,
    url = FLINTTRADE_RELEASES_API,
    headers: HeadersInit = { "content-type": "application/json; charset=utf-8" },
  ): Response {
    const result = new Response(body, { headers });
    Object.defineProperty(result, "url", { value: url });
    return result;
  }

  it("accepts only bounded official GitHub release metadata", async () => {
    const response = releaseResponse(JSON.stringify([{
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
      redirect: "error",
      signal: expect.any(AbortSignal),
    }));
  });

  it("accepts Electron net.fetch responses that omit Response.url", async () => {
    const chunk = vm.runInNewContext("new Uint8Array([91, 93])") as Uint8Array;
    expect(chunk).not.toBeInstanceOf(Uint8Array);
    expect(ArrayBuffer.isView(chunk)).toBe(true);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(chunk);
        controller.close();
      },
    });
    const response = releaseResponse(body, "");
    const fetcher = vi.fn(async () => response);

    await expect(
      createGithubShellReleaseSource(fetcher).list(new AbortController().signal),
    ).resolves.toEqual([]);
    expect(fetcher).toHaveBeenCalledWith(FLINTTRADE_RELEASES_API, expect.objectContaining({
      redirect: "error",
    }));
  });

  it("rejects non-byte views even when Symbol.toStringTag impersonates Uint8Array", async () => {
    const spoofed = new Uint16Array([0x5d5b]);
    Object.defineProperty(spoofed, Symbol.toStringTag, { value: "Uint8Array" });
    expect(Object.prototype.toString.call(spoofed)).toBe("[object Uint8Array]");
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(spoofed as unknown as Uint8Array);
        controller.close();
      },
    });

    await expect(
      createGithubShellReleaseSource(async () => releaseResponse(body))
        .list(new AbortController().signal),
    ).rejects.toThrow(/non-byte body/i);
  });

  it("rejects redirects, extra or duplicate query parameters, and fragments", async () => {
    for (const url of [
      "https://attacker.example/releases",
      FLINTTRADE_RELEASES_API.replace("api.github.com", "api.github.com:443"),
      `${FLINTTRADE_RELEASES_API}&page=2`,
      `${FLINTTRADE_RELEASES_API}&per_page=30`,
      `${FLINTTRADE_RELEASES_API}#fragment`,
    ]) {
      await expect(
        createGithubShellReleaseSource(async () => releaseResponse("[]", url))
          .list(new AbortController().signal),
      ).rejects.toThrow(/official GitHub release metadata/i);
    }
  });

  it("rejects wrong content types, invalid or oversized lengths, and oversized streamed bodies", async () => {
    const cases = [
      releaseResponse("[]", FLINTTRADE_RELEASES_API, { "content-type": "text/plain" }),
      releaseResponse("[]", FLINTTRADE_RELEASES_API, {
        "content-length": "invalid",
        "content-type": "application/json",
      }),
      releaseResponse("[]", FLINTTRADE_RELEASES_API, {
        "content-length": String(2 * 1024 * 1024 + 1),
        "content-type": "application/json",
      }),
      releaseResponse(new Uint8Array(2 * 1024 * 1024 + 1), FLINTTRADE_RELEASES_API),
    ];
    for (const candidate of cases) {
      await expect(
        createGithubShellReleaseSource(async () => candidate).list(new AbortController().signal),
      ).rejects.toThrow();
    }
  });

  it("aborts and non-blockingly cancels every rejected post-header body", async () => {
    for (const headers of [
      { "content-type": "text/plain" },
      { "content-length": "invalid", "content-type": "application/json" },
      { "content-length": String(2 * 1024 * 1024 + 1), "content-type": "application/json" },
    ]) {
      const cancelStarted = vi.fn();
      const stream = new ReadableStream<Uint8Array>({
        cancel() {
          cancelStarted();
          return new Promise<void>(() => undefined);
        },
        pull() {
          return new Promise<void>(() => undefined);
        },
      }, { highWaterMark: 0 });
      let requestSignal: AbortSignal | undefined;
      const source = createGithubShellReleaseSource(async (_url, init) => {
        requestSignal = init.signal as AbortSignal;
        return releaseResponse(stream, FLINTTRADE_RELEASES_API, headers);
      });

      await expect(source.list(new AbortController().signal)).rejects.toThrow();
      expect(requestSignal?.aborted).toBe(true);
      expect(cancelStarted).toHaveBeenCalledOnce();
    }
  });

  it("bounds stalled response headers and bodies with one independent deadline", async () => {
    vi.useFakeTimers();
    try {
      const stalledHeaders = createGithubShellReleaseSource(
        async () => await new Promise<Response>(() => undefined),
        { timeoutMs: 25 },
      ).list(new AbortController().signal);
      const headersRejected = expect(stalledHeaders).rejects.toThrow(/timed out/i);
      await vi.advanceTimersByTimeAsync(26);
      await headersRejected;

      const stalledStream = new ReadableStream<Uint8Array>({
        cancel() {
          return new Promise<void>(() => undefined);
        },
        start(controller) {
          controller.enqueue(new TextEncoder().encode("["));
        },
      });
      const stalledBody = createGithubShellReleaseSource(
        async () => releaseResponse(stalledStream),
        { timeoutMs: 25 },
      ).list(new AbortController().signal);
      const bodyRejected = expect(stalledBody).rejects.toThrow(/timed out/i);
      await vi.advanceTimersByTimeAsync(26);
      await bodyRejected;
    } finally {
      vi.useRealTimers();
    }
  });

  it("lets outer shutdown abort a never-closing streamed body", async () => {
    let bodyStarted!: () => void;
    const started = new Promise<void>((resolve) => { bodyStarted = resolve; });
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        return new Promise<void>(() => undefined);
      },
      pull() {
        bodyStarted();
        return new Promise<void>(() => undefined);
      },
    }, { highWaterMark: 0 });
    const controller = new AbortController();
    const pending = createGithubShellReleaseSource(
      async () => releaseResponse(stream),
      { timeoutMs: 1_000 },
    ).list(controller.signal);

    await started;
    controller.abort(new DOMException("application quitting", "AbortError"));
    await expect(pending).rejects.toThrow(/application quitting/i);
  });

  it("requires a bounded release metadata deadline", () => {
    expect(() => createGithubShellReleaseSource(async () => releaseResponse("[]"), { timeoutMs: 0 }))
      .toThrow(/between 1 and 60000/i);
  });
});

describe("shell installer environment", () => {
  it("drops release overrides, credentials and build-mode knobs", () => {
    const environment = shellInstallerEnvironment({
      APPIMAGE: "/attacker/FlintTrade.AppImage",
      FLINTTRADE_ALLOW_LOCAL_ASSET: "1",
      FLINTTRADE_BUILD_FROM_SOURCE: "1",
      FLINTTRADE_GITHUB_RELEASES_API: "https://attacker.example/releases",
      FLINTTRADE_UPDATE_ASSET_NAME: "attacker.exe",
      FLINTTRADE_UPDATE_ASSET_SHA256: "0".repeat(64),
      FLINTTRADE_UPDATE_STAGE_DIR: "/attacker/stage",
      FLINTTRADE_UPDATE_STAGE_ROOT: "/attacker/root",
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

  it.runIf(process.platform !== "win32")("keeps a durable owner-only installer failure trail and stage", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "flinttrade-shell-log-"));
    const privateRoot = path.join(root, "private");
    const resourcesDirectory = path.join(root, "resources");
    try {
      await mkdir(privateRoot, { mode: 0o700 });
      await mkdir(path.join(resourcesDirectory, "install"), { recursive: true });
      await writeFile(
        path.join(resourcesDirectory, "install", "flinttrade-install.sh"),
        "#!/bin/bash\n" +
          "printf 'ASSET_NAME=%s\\nASSET_SHA256=%s\\n' \"$FLINTTRADE_UPDATE_ASSET_NAME\" " +
          "\"$FLINTTRADE_UPDATE_ASSET_SHA256\" >&2\n" +
          "printf 'deliberate installer failure\\n' >&2\nexit 7\n",
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
      });
      const marker = await handoff.createMarker();
      const assetName = process.platform === "darwin"
        ? "FlintTrade-1.2.3-mac-universal.dmg"
        : "FlintTrade-1.2.3-linux-x64.AppImage";
      const attempt = await handoff.launch({
        assetName,
        digest: `sha256:${"a".repeat(64)}`,
        marker,
        releaseTag: "v1.2.3",
      });

      await expect(attempt.exited).resolves.toBe(7);
      const logPath = path.join(privateRoot, "shell-updates", "logs", "installer.log");
      const failureLog = await readFile(logPath, "utf8");
      const stagingRoot = await realpath(path.join(privateRoot, "shell-updates", "staging"));
      const stagedEntries = await readdir(stagingRoot);
      expect(stagedEntries).toHaveLength(1);
      const stagedPath = path.join(stagingRoot, stagedEntries[0]!);
      expect(failureLog).toContain(`ASSET_NAME=${assetName}\n`);
      expect(failureLog).toContain(`ASSET_SHA256=${"a".repeat(64)}\n`);
      expect(path.dirname(stagedPath)).toBe(stagingRoot);
      expect(path.basename(stagedPath)).toMatch(/^flinttrade-shell-update-.+/);
      expect((await stat(stagedPath)).mode & 0o077).toBe(0);

      const capturedStage = `${stagedPath}.captured`;
      await rename(stagedPath, capturedStage);
      await mkdir(stagedPath);
      await writeFile(path.join(stagedPath, "foreign-sentinel"), "preserve me");
      await expect(attempt.cleanup()).resolves.toBeUndefined();
      await expect(readFile(path.join(stagedPath, "foreign-sentinel"), "utf8")).resolves.toBe("preserve me");
      await expect(stat(capturedStage)).resolves.toMatchObject({ mode: expect.any(Number) });
      await expect(readFile(logPath, "utf8")).resolves.toMatch(/v1\.2\.3[\s\S]*deliberate installer failure/);
      expect((await readdir(stagingRoot)).sort()).toEqual([
        path.basename(capturedStage),
        path.basename(stagedPath),
      ].sort());
      expect((await stat(logPath)).mode & 0o077).toBe(0);
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  it.runIf(process.platform !== "win32")("preserves a successful private installer stage", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "flinttrade-shell-success-stage-"));
    const privateRoot = path.join(root, "private");
    const resourcesDirectory = path.join(root, "resources");
    try {
      await mkdir(privateRoot, { mode: 0o700 });
      await mkdir(path.join(resourcesDirectory, "install"), { recursive: true });
      await writeFile(
        path.join(resourcesDirectory, "install", "flinttrade-install.sh"),
        "#!/bin/bash\nprintf 'successful installer\\n' >&2\nexit 0\n",
        { mode: 0o700 },
      );
      let currentExecutablePath: string | undefined;
      let currentLinuxAppDir: string | undefined;
      let currentLinuxAppImage: string | undefined;
      if (process.platform === "darwin") {
        currentExecutablePath = path.join(root, "FlintTrade.app", "Contents", "MacOS", "FlintTrade");
        await mkdir(path.dirname(currentExecutablePath), { recursive: true });
        await writeFile(currentExecutablePath, "test executable", { mode: 0o700 });
      } else {
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
      });
      const marker = await handoff.createMarker();
      const attempt = await handoff.launch({
        assetName: process.platform === "darwin"
          ? "FlintTrade-1.2.3-mac-universal.dmg"
          : "FlintTrade-1.2.3-linux-x64.AppImage",
        digest: `sha256:${"a".repeat(64)}`,
        marker,
        releaseTag: "v1.2.3",
      });

      await expect(attempt.exited).resolves.toBe(0);
      await attempt.cleanup();
      const stagingRoot = path.join(privateRoot, "shell-updates", "staging");
      const stages = await readdir(stagingRoot);
      expect(stages).toHaveLength(1);
      await expect(stat(path.join(stagingRoot, stages[0]!, "flinttrade-install.sh"))).resolves.toMatchObject({
        mode: expect.any(Number),
      });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  it.runIf(process.platform !== "win32")("preserves a cancelled private installer stage", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "flinttrade-shell-cancel-stage-"));
    const privateRoot = path.join(root, "private");
    const resourcesDirectory = path.join(root, "resources");
    try {
      await mkdir(privateRoot, { mode: 0o700 });
      await mkdir(path.join(resourcesDirectory, "install"), { recursive: true });
      await writeFile(
        path.join(resourcesDirectory, "install", "flinttrade-install.sh"),
        "#!/bin/bash\nexec /bin/sleep 30\n",
        { mode: 0o700 },
      );
      let currentExecutablePath: string;
      let currentLinuxAppDir: string | undefined;
      let currentLinuxAppImage: string | undefined;
      if (process.platform === "darwin") {
        currentExecutablePath = path.join(root, "FlintTrade.app", "Contents", "MacOS", "FlintTrade");
        await mkdir(path.dirname(currentExecutablePath), { recursive: true });
        await writeFile(currentExecutablePath, "test executable", { mode: 0o700 });
      } else {
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
      });
      const marker = await handoff.createMarker();
      const attempt = await handoff.launch({
        assetName: process.platform === "darwin"
          ? "FlintTrade-1.2.3-mac-universal.dmg"
          : "FlintTrade-1.2.3-linux-x64.AppImage",
        digest: `sha256:${"a".repeat(64)}`,
        marker,
        releaseTag: "v1.2.3",
      });

      await attempt.cancel();
      await expect(attempt.exited).resolves.toBe(-1);
      await attempt.cleanup();
      const stagingRoot = path.join(privateRoot, "shell-updates", "staging");
      const stages = await readdir(stagingRoot);
      expect(stages).toHaveLength(1);
      await expect(stat(path.join(stagingRoot, stages[0]!, "flinttrade-install.sh"))).resolves.toMatchObject({
        mode: expect.any(Number),
      });
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
      });
      const marker = await handoff.createMarker();
      const attempt = await handoff.launch({
        assetName: "FlintTrade-1.2.3-linux-x64.AppImage",
        digest: `sha256:${"a".repeat(64)}`,
        marker,
        releaseTag: "v1.2.3",
      });
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
