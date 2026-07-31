import { describe, expect, it, vi } from "vitest";

import { createShellUpdater, parseSemver, shellInstallerAssetName, type ShellRelease } from "./shell-updater";
import { createUpdateState } from "./state";

function asset(tag: string, name: string, overrides: Partial<{ digest: string | null; url: string }> = {}) {
  return {
    digest: overrides.digest === undefined ? `sha256:${"a".repeat(64)}` : overrides.digest,
    downloadUrl:
      overrides.url ?? `https://github.com/navaneeshnagarajan/FlintTrade/releases/download/${tag}/${name}`,
    name,
  };
}

function release(version: string, options: Partial<{ draft: boolean; prerelease: boolean }> = {}): ShellRelease {
  const tag = `v${version}`;
  return {
    assets: [
      asset(tag, `FlintTrade-${version}-mac-universal.dmg`),
      asset(tag, `FlintTrade-${version}-win-x64.exe`),
      asset(tag, `FlintTrade-${version}-linux-x64.AppImage`),
      asset(tag, `FlintTrade-${version}-linux-arm64.AppImage`),
      asset(tag, "SHA256SUMS.txt"),
    ],
    draft: options.draft ?? false,
    prerelease: options.prerelease ?? version.includes("-"),
    tagName: tag,
  };
}

function fixture(input: Partial<{
  currentVersion: string;
  marker: boolean;
  releases: readonly ShellRelease[];
}> = {}) {
  let marker = input.marker ?? false;
  let exitResolve!: (code: number) => void;
  const exited = new Promise<number>((resolve) => { exitResolve = resolve; });
  const installer = {
    cancel: vi.fn(async () => { exitResolve(143); }),
    cleanup: vi.fn(async () => undefined),
    exited,
  };
  const handoff = {
    createMarker: vi.fn(async () => "/workspace/shell-updates/handoff/marker"),
    launch: vi.fn(async () => installer),
    markerExists: vi.fn(async () => marker),
    removeMarker: vi.fn(async () => undefined),
  };
  const lifecycle = { requestQuit: vi.fn(async () => undefined) };
  const attestations = {
    verify: vi.fn(async ({
      assetName,
      digest,
      releaseTag,
    }: { assetName: string; digest: string; releaseTag: string; signal: AbortSignal }) => ({
      assetName,
      digest,
      releaseTag,
    })),
  };
  const state = createUpdateState("shell", input.currentVersion ?? "0.6.0-beta.13");
  const updater = createShellUpdater({
    arch: "arm64",
    attestations,
    currentVersion: input.currentVersion ?? "0.6.0-beta.13",
    enabled: true,
    handoff,
    heartbeatIntervalMs: 1,
    handoffTimeoutMs: 1_000,
    lifecycle,
    platform: "darwin",
    releases: { list: vi.fn(async () => input.releases ?? [release("0.6.0-beta.14")]) },
    state,
    wait: async (_milliseconds, signal) => {
      if (signal.aborted) throw new DOMException("cancelled", "AbortError");
      await new Promise((resolve) => setTimeout(resolve, 1));
      if (signal.aborted) throw new DOMException("cancelled", "AbortError");
    },
  });
  return {
    attestations,
    exit: exitResolve,
    handoff,
    installer,
    lifecycle,
    markVerified() { marker = true; },
    state,
    updater,
  };
}

// A release tag the GitHub API could hand the updater: a version starting
// "0.0.0-0." followed by many "--." groups. Under the published semver.org
// regex each "--" group matches two ways, so the cost quadruples per pair —
// twenty-eight groups took 110 seconds for a single rejection. Parsing must be
// linear, so a thousand rejections of thirty groups take single-digit
// milliseconds.
const HOSTILE_PRERELEASE_VERSION = `0.0.0-0.${"--.".repeat(30)}`;

describe("Electron shell semantic version parsing", () => {
  it("rejects a hostile prerelease tag in linear time", () => {
    const started = performance.now();
    let rejections = 0;
    for (let attempt = 0; attempt < 1_000; attempt += 1) {
      if (parseSemver(HOSTILE_PRERELEASE_VERSION) === null) rejections += 1;
    }
    const elapsedMs = performance.now() - started;

    expect(rejections).toBe(1_000);
    expect(elapsedMs).toBeLessThan(1_000);
  });

  it("ignores a release whose tag carries that prerelease without stalling the check", async () => {
    const hostile = release(HOSTILE_PRERELEASE_VERSION);
    const test = fixture({ releases: [hostile, release("0.6.0-beta.14")] });

    await expect(test.updater.check()).resolves.toMatchObject({
      status: "available",
      version: "0.6.0-beta.14",
    });
  });

  it("keeps the semantic versions the release policy depends on", () => {
    expect(parseSemver("1.2.3")?.prerelease).toEqual([]);
    expect(parseSemver("0.6.0-beta.13")?.prerelease).toEqual(["beta", "13"]);
    expect(parseSemver("1.2.3-x-y-z.--")?.prerelease).toEqual(["x-y-z", "--"]);
    expect(parseSemver("1.2.3-0.3.7+build.11.e0f985a")).toMatchObject({
      major: "1",
      prerelease: ["0", "3", "7"],
      version: "1.2.3-0.3.7+build.11.e0f985a",
    });
    expect(parseSemver("1.2.3-0a")?.prerelease).toEqual(["0a"]);
  });

  it("rejects the malformed versions the old expression rejected", () => {
    for (const value of [
      "",
      "1.2",
      "v1.2.3",
      "01.2.3",
      "1.2.3-",
      "1.2.3+",
      "1.2.3-01",
      "1.2.3-alpha..1",
      "1.2.3-alpha_1",
      "1.2.3+build+more",
      "1.2.3 ",
    ]) {
      expect(parseSemver(value)).toBeNull();
    }
  });
});

describe("Electron shell release policy", () => {
  it("uses the four canonical physical installer names", () => {
    expect(shellInstallerAssetName("darwin", "arm64", "1.2.3")).toBe("FlintTrade-1.2.3-mac-universal.dmg");
    expect(shellInstallerAssetName("win32", "arm64", "1.2.3")).toBe("FlintTrade-1.2.3-win-x64.exe");
    expect(shellInstallerAssetName("linux", "x64", "1.2.3")).toBe("FlintTrade-1.2.3-linux-x64.AppImage");
    expect(shellInstallerAssetName("linux", "arm64", "1.2.3")).toBe("FlintTrade-1.2.3-linux-arm64.AppImage");
    expect(shellInstallerAssetName("linux", "ia32", "1.2.3")).toBeNull();
  });

  it("selects the newest newer same-release asset only with SHA256SUMS", async () => {
    const test = fixture({
      releases: [release("0.6.0-beta.14"), release("0.7.0-beta.2"), release("0.7.0-beta.10")],
    });
    await expect(test.updater.check()).resolves.toMatchObject({
      currentVersion: "0.6.0-beta.13",
      status: "available",
      version: "0.7.0-beta.10",
    });
  });

  it("keeps stable builds off prerelease releases", async () => {
    const test = fixture({ currentVersion: "1.0.0", releases: [release("1.1.0-beta.1")] });
    await expect(test.updater.check()).resolves.toMatchObject({ status: "unavailable", version: null });
  });

  it("keeps beta builds off alpha, dev and rc channels while allowing stable promotion", async () => {
    const test = fixture({
      releases: [
        release("2.0.0-alpha.1"),
        release("2.0.0-dev.1"),
        release("2.0.0-rc.1"),
        release("0.6.0-beta.14"),
        release("1.0.0", { prerelease: false }),
      ],
    });
    await expect(test.updater.check()).resolves.toMatchObject({ status: "available", version: "1.0.0" });
  });

  it("compares arbitrarily large numeric prerelease identifiers without number rounding", async () => {
    const test = fixture({
      releases: [
        release("0.6.0-beta.9007199254740993"),
        release("0.6.0-beta.9007199254740992"),
      ],
    });
    await expect(test.updater.check()).resolves.toMatchObject({
      status: "available",
      version: "0.6.0-beta.9007199254740993",
    });
  });

  it("compares arbitrarily large core identifiers without number rounding", async () => {
    const test = fixture({
      currentVersion: "1.0.0-beta.1",
      releases: [
        release("9007199254740992.0.0-beta.1"),
        release("9007199254740993.0.0-beta.1"),
      ],
    });
    await expect(test.updater.check()).resolves.toMatchObject({
      status: "available",
      version: "9007199254740993.0.0-beta.1",
    });
  });

  it("rejects a release with a missing checksum, duplicate asset, or off-origin URL", async () => {
    const missingChecksum = release("0.6.0-beta.14");
    const duplicate = release("0.6.0-beta.15");
    const attacked = release("0.6.0-beta.16");
    const test = fixture({
      releases: [
        { ...missingChecksum, assets: missingChecksum.assets.filter((entry) => entry.name !== "SHA256SUMS.txt") },
        { ...duplicate, assets: [...duplicate.assets, duplicate.assets[0]!] },
        {
          ...attacked,
          assets: attacked.assets.map((entry) => entry.name.endsWith(".dmg")
            ? { ...entry, downloadUrl: "https://attacker.example/FlintTrade.dmg" }
            : entry),
        },
      ],
    });
    await expect(test.updater.check()).resolves.toMatchObject({ status: "unavailable", version: null });
  });
});

describe("Electron shell installer handoff", () => {
  it("passes the exact checked tag and quits only after verified handoff", async () => {
    const test = fixture();
    await test.updater.check();
    test.markVerified();

    await expect(test.updater.apply()).resolves.toMatchObject({
      progress: 100,
      status: "complete",
      version: "0.6.0-beta.14",
    });

    expect(test.handoff.launch).toHaveBeenCalledWith({
      assetName: "FlintTrade-0.6.0-beta.14-mac-universal.dmg",
      digest: `sha256:${"a".repeat(64)}`,
      marker: "/workspace/shell-updates/handoff/marker",
      releaseTag: "v0.6.0-beta.14",
    });
    expect(test.attestations.verify).toHaveBeenCalledBefore(test.handoff.createMarker);
    expect(test.handoff.removeMarker).toHaveBeenCalledBefore(test.lifecycle.requestQuit);
    expect(test.lifecycle.requestQuit).toHaveBeenCalledOnce();
    expect(test.installer.cancel).not.toHaveBeenCalled();
  });

  it("keeps FlintTrade running when signed release provenance cannot be verified", async () => {
    const test = fixture();
    test.attestations.verify.mockRejectedValueOnce(new Error("untrusted release writer"));
    await test.updater.check();

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: "Electron shell installation could not start. FlintTrade is still running.",
      status: "failed",
    });

    expect(test.handoff.createMarker).not.toHaveBeenCalled();
    expect(test.handoff.launch).not.toHaveBeenCalled();
    expect(test.lifecycle.requestQuit).not.toHaveBeenCalled();
  });

  it("settles external quit while the underlying Sigstore verifier never settles", async () => {
    let verificationStarted!: () => void;
    const started = new Promise<void>((resolve) => { verificationStarted = resolve; });
    const neverSettlingVerifier = new Promise<never>(() => undefined);
    void neverSettlingVerifier.catch(() => undefined);
    const test = fixture();
    test.attestations.verify.mockImplementationOnce(async ({ signal }) => {
      verificationStarted();
      const aborted = new Promise<never>((_resolve, reject) => {
        const abort = (): void => reject(signal.reason);
        if (signal.aborted) abort();
        else signal.addEventListener("abort", abort, { once: true });
      });
      return await Promise.race([neverSettlingVerifier, aborted]);
    });
    await test.updater.check();
    const applying = test.updater.apply();
    await started;

    await expect(test.updater.settleForQuit()).resolves.toBeUndefined();
    await expect(applying).resolves.toMatchObject({
      failure: "Electron shell update was cancelled before installation.",
      status: "failed",
    });
    expect(test.handoff.createMarker).not.toHaveBeenCalled();
    expect(test.lifecycle.requestQuit).not.toHaveBeenCalled();
  });

  it("keeps FlintTrade running when the installer exits before signalling verification", async () => {
    const test = fixture();
    await test.updater.check();
    test.exit(9);

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: "Electron shell installation could not start. FlintTrade is still running.",
      status: "failed",
    });

    expect(test.lifecycle.requestQuit).not.toHaveBeenCalled();
    expect(test.installer.cancel).toHaveBeenCalledOnce();
  });

  it("rejects a stale ready marker when the installer has already exited", async () => {
    const test = fixture({ marker: true });
    await test.updater.check();
    test.exit(9);
    await Promise.resolve();

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: "Electron shell installation could not start. FlintTrade is still running.",
      status: "failed",
    });

    expect(test.lifecycle.requestQuit).not.toHaveBeenCalled();
    expect(test.installer.cancel).toHaveBeenCalledOnce();
    expect(test.installer.cleanup).toHaveBeenCalledOnce();
  });

  it("cancels an installer still downloading when the app quits for another reason", async () => {
    const test = fixture();
    await test.updater.check();
    const applying = test.updater.apply();
    await vi.waitFor(() => expect(test.handoff.launch).toHaveBeenCalledOnce(), { timeout: 15_000 });

    await test.updater.settleForQuit();
    await expect(applying).resolves.toMatchObject({
      failure: "Electron shell update was cancelled before installation.",
      status: "failed",
    });
    expect(test.installer.cancel).toHaveBeenCalled();
    expect(test.lifecycle.requestQuit).not.toHaveBeenCalled();
  });

  it("gives an external quit ownership when verified handoff has not yet been observed", async () => {
    let resolveMarker!: (value: boolean) => void;
    const marker = new Promise<boolean>((resolve) => { resolveMarker = resolve; });
    const test = fixture();
    test.handoff.markerExists.mockImplementationOnce(async () => await marker);
    await test.updater.check();
    const applying = test.updater.apply();
    await vi.waitFor(() => expect(test.handoff.launch).toHaveBeenCalledOnce(), { timeout: 15_000 });

    const quitting = test.updater.settleForQuit();
    resolveMarker(true);
    await expect(Promise.all([applying, quitting])).resolves.toBeDefined();

    expect(test.lifecycle.requestQuit).not.toHaveBeenCalled();
    expect(test.installer.cancel).toHaveBeenCalledOnce();
    expect(test.state.getSnapshot()).toMatchObject({
      failure: "Electron shell update was cancelled before installation.",
      status: "failed",
    });
  });

  it("contains a verified installer when lifecycle drain rejects and permits a clean retry", async () => {
    const test = fixture();
    test.lifecycle.requestQuit.mockRejectedValueOnce(new Error("backend containment failed"));
    await test.updater.check();
    test.markVerified();

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: "Electron shell installation could not start. FlintTrade is still running.",
      status: "failed",
    });
    expect(test.installer.cancel).toHaveBeenCalledOnce();
    await expect(test.updater.settleForQuit()).resolves.toBeUndefined();

    test.handoff.launch.mockResolvedValueOnce({
      cancel: vi.fn(async () => undefined),
      cleanup: vi.fn(async () => undefined),
      exited: new Promise<number>(() => undefined),
    });
    await test.updater.check();
    await expect(test.updater.apply()).resolves.toMatchObject({ status: "complete" });
    expect(test.lifecycle.requestQuit).toHaveBeenCalledTimes(2);
    expect(test.installer.cancel).toHaveBeenCalledOnce();
  });

  it("fails closed when the verified installer exits during lifecycle drain", async () => {
    const test = fixture({ marker: true });
    test.lifecycle.requestQuit.mockImplementationOnce(async () => {
      await test.updater.settleForQuit();
      test.exit(12);
      await Promise.resolve();
      await test.updater.settleForQuit();
    });
    await test.updater.check();

    await expect(test.updater.apply()).resolves.toMatchObject({
      failure: "Electron shell installation could not start. FlintTrade is still running.",
      status: "failed",
    });

    expect(test.installer.cancel).toHaveBeenCalledOnce();
    expect(test.state.getSnapshot()).toMatchObject({ status: "failed" });
  });

  it("blocks external quit when installer process containment cannot be proved", async () => {
    const test = fixture();
    test.installer.cancel.mockRejectedValue(new Error("taskkill failed"));
    await test.updater.check();
    const applying = test.updater.apply();
    await vi.waitFor(() => expect(test.handoff.launch).toHaveBeenCalledOnce(), { timeout: 15_000 });

    await expect(test.updater.settleForQuit()).rejects.toThrow(/containment could not be proved/i);
    await expect(applying).rejects.toThrow(/containment could not be proved/i);
    await expect(test.updater.settleForQuit()).rejects.toThrow(/containment could not be proved/i);
    expect(test.state.getSnapshot()).toMatchObject({
      failure: "The shell installer could not be proven stopped. Quit is blocked.",
      status: "failed",
    });
    expect(test.lifecycle.requestQuit).not.toHaveBeenCalled();
    expect(test.installer.cancel).toHaveBeenCalledTimes(2);
  });

  it("allows quit after a later containment retry proves the installer stopped", async () => {
    const test = fixture();
    test.installer.cancel.mockRejectedValueOnce(new Error("first taskkill failed"));
    test.installer.cleanup.mockRejectedValue(new Error("temporary directory is busy"));
    await test.updater.check();
    const applying = test.updater.apply();
    await vi.waitFor(() => expect(test.handoff.launch).toHaveBeenCalledOnce(), { timeout: 15_000 });

    await expect(test.updater.settleForQuit()).rejects.toThrow(/containment could not be proved/i);
    await expect(applying).rejects.toThrow(/containment could not be proved/i);
    await expect(test.updater.settleForQuit()).resolves.toBeUndefined();
    await expect(test.updater.settleForQuit()).resolves.toBeUndefined();

    expect(test.installer.cancel).toHaveBeenCalledTimes(2);
    expect(test.lifecycle.requestQuit).not.toHaveBeenCalled();
  });
});
