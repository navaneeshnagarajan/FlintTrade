import type { createUpdateState, UpdateSnapshot } from "./state";
import type { ShellAttestationVerifier } from "./shell-attestation";

const CHECKSUM_ASSET_NAME = "SHA256SUMS.txt";
const RELEASE_DOWNLOAD_PREFIX = "/navaneeshnagarajan/FlintTrade/releases/download/";
const SEMVER_PATTERN =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

type ShellUpdateState = ReturnType<typeof createUpdateState>;

export interface ShellReleaseAsset {
  digest: string | null;
  downloadUrl: string;
  name: string;
}

export interface ShellRelease {
  assets: readonly ShellReleaseAsset[];
  draft: boolean;
  prerelease: boolean;
  tagName: string;
}

export interface ShellReleaseSource {
  list(signal: AbortSignal): Promise<readonly ShellRelease[]>;
}

export interface ShellInstallerAttempt {
  cancel(): Promise<void>;
  cleanup(): Promise<void>;
  exited: Promise<number>;
}

export interface ShellInstallerHandoff {
  createMarker(): Promise<string>;
  launch(input: {
    assetName: string;
    digest: string;
    marker: string;
    releaseTag: string;
  }): Promise<ShellInstallerAttempt>;
  markerExists(marker: string): Promise<boolean>;
  removeMarker(marker: string): Promise<void>;
}

export interface ShellUpdaterOptions {
  arch: string;
  attestations: ShellAttestationVerifier;
  currentVersion: string;
  enabled: boolean;
  handoff: ShellInstallerHandoff;
  heartbeatIntervalMs?: number;
  handoffTimeoutMs?: number;
  lifecycle: { requestQuit(): Promise<void> };
  now?: () => number;
  platform: NodeJS.Platform;
  releases: ShellReleaseSource;
  state: ShellUpdateState;
  wait?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
}

export interface ShellUpdater {
  apply(): Promise<Readonly<UpdateSnapshot>>;
  check(): Promise<Readonly<UpdateSnapshot>>;
  settleForQuit(): Promise<void>;
}

interface Semver {
  major: string;
  minor: string;
  patch: string;
  prerelease: readonly string[];
  version: string;
}

interface CheckedRelease {
  asset: ShellReleaseAsset;
  checksum: ShellReleaseAsset;
  release: ShellRelease;
  semver: Semver;
}

function parseSemver(value: string): Semver | null {
  const match = SEMVER_PATTERN.exec(value);
  if (!match) return null;
  return {
    major: match[1]!,
    minor: match[2]!,
    patch: match[3]!,
    prerelease: match[4]?.split(".") ?? [],
    version: value,
  };
}

function compareNumericIdentifier(left: string, right: string): number {
  if (left.length !== right.length) return left.length < right.length ? -1 : 1;
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function compareSemver(left: Semver, right: Semver): number {
  for (const field of ["major", "minor", "patch"] as const) {
    const difference = compareNumericIdentifier(left[field], right[field]);
    if (difference !== 0) return difference;
  }
  if (left.prerelease.length === 0 || right.prerelease.length === 0) {
    return left.prerelease.length === right.prerelease.length ? 0 : left.prerelease.length === 0 ? 1 : -1;
  }
  const length = Math.max(left.prerelease.length, right.prerelease.length);
  for (let index = 0; index < length; index += 1) {
    const leftPart = left.prerelease[index];
    const rightPart = right.prerelease[index];
    if (leftPart === undefined || rightPart === undefined) return leftPart === undefined ? -1 : 1;
    if (leftPart === rightPart) continue;
    const leftNumeric = /^\d+$/.test(leftPart);
    const rightNumeric = /^\d+$/.test(rightPart);
    if (leftNumeric && rightNumeric) {
      return compareNumericIdentifier(leftPart, rightPart);
    }
    if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1;
    return leftPart < rightPart ? -1 : 1;
  }
  return 0;
}

export function shellInstallerAssetName(
  platform: NodeJS.Platform,
  arch: string,
  version: string,
): string | null {
  if (platform === "darwin" && (arch === "arm64" || arch === "x64")) {
    return `FlintTrade-${version}-mac-universal.dmg`;
  }
  if (platform === "win32" && (arch === "arm64" || arch === "x64")) {
    return `FlintTrade-${version}-win-x64.exe`;
  }
  if (platform === "linux" && (arch === "arm64" || arch === "x64")) {
    return `FlintTrade-${version}-linux-${arch}.AppImage`;
  }
  return null;
}

function trustedReleaseAsset(asset: ShellReleaseAsset, tagName: string): boolean {
  if (!asset.name || asset.name.includes("/") || asset.name.includes("\\")) return false;
  if (asset.digest !== null && !/^sha256:[0-9a-f]{64}$/.test(asset.digest)) return false;
  let url: URL;
  try {
    url = new URL(asset.downloadUrl);
  } catch {
    return false;
  }
  if (
    url.protocol !== "https:" ||
    url.hostname !== "github.com" ||
    url.port !== "" ||
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== "" ||
    !url.pathname.startsWith(RELEASE_DOWNLOAD_PREFIX)
  ) {
    return false;
  }
  const suffix = url.pathname.slice(RELEASE_DOWNLOAD_PREFIX.length);
  const separator = suffix.indexOf("/");
  if (separator <= 0) return false;
  try {
    return decodeURIComponent(suffix.slice(0, separator)) === tagName &&
      decodeURIComponent(suffix.slice(separator + 1)) === asset.name;
  } catch {
    return false;
  }
}

function exactUniqueAsset(release: ShellRelease, name: string): ShellReleaseAsset | null {
  const matches = release.assets.filter((asset) => asset.name === name && trustedReleaseAsset(asset, release.tagName));
  return matches.length === 1 ? matches[0]! : null;
}

function selectRelease(
  releases: readonly ShellRelease[],
  current: Semver,
  platform: NodeJS.Platform,
  arch: string,
): CheckedRelease | null {
  const stableChannel = current.prerelease.length === 0;
  const prereleaseChannel = current.prerelease[0] ?? null;
  const candidates: CheckedRelease[] = [];
  for (const release of releases) {
    if (release.draft || !release.tagName.startsWith("v")) continue;
    const semver = parseSemver(release.tagName.slice(1));
    if (!semver || release.prerelease !== (semver.prerelease.length > 0)) continue;
    if (stableChannel && release.prerelease) continue;
    if (!stableChannel && release.prerelease && semver.prerelease[0] !== prereleaseChannel) continue;
    if (compareSemver(semver, current) <= 0) continue;
    const expectedName = shellInstallerAssetName(platform, arch, semver.version);
    if (!expectedName) continue;
    const asset = exactUniqueAsset(release, expectedName);
    const checksum = exactUniqueAsset(release, CHECKSUM_ASSET_NAME);
    if (asset?.digest && checksum) candidates.push({ asset, checksum, release, semver });
  }
  candidates.sort((left, right) => compareSemver(right.semver, left.semver));
  return candidates[0] ?? null;
}

function abortError(): DOMException {
  return new DOMException("Shell update operation was cancelled.", "AbortError");
}

function defaultWait(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const onAbort = (): void => {
      clearTimeout(timeout);
      reject(abortError());
    };
    const timeout = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export function createShellUpdater(options: ShellUpdaterOptions): ShellUpdater {
  const current = parseSemver(options.currentVersion);
  if (!current) throw new Error("The Electron shell version must be valid semantic version metadata.");
  const expectedAsset = shellInstallerAssetName(options.platform, options.arch, current.version);
  const supported = expectedAsset !== null;
  const heartbeatIntervalMs = options.heartbeatIntervalMs ?? 2_000;
  const handoffTimeoutMs = options.handoffTimeoutMs ?? 30 * 60_000;
  if (!Number.isSafeInteger(heartbeatIntervalMs) || heartbeatIntervalMs <= 0) {
    throw new Error("Shell update heartbeat interval must be a positive safe integer.");
  }
  if (!Number.isSafeInteger(handoffTimeoutMs) || handoffTimeoutMs <= 0) {
    throw new Error("Shell update handoff timeout must be a positive safe integer.");
  }

  const now = options.now ?? Date.now;
  const wait = options.wait ?? defaultWait;
  let checked: CheckedRelease | null = null;
  let activeAbort: AbortController | null = null;
  let handoffReached = false;
  let handoffInstaller: ShellInstallerAttempt | null = null;
  let handoffInstallerExitCode: number | null = null;
  let retainedInstaller: ShellInstallerAttempt | null = null;
  let retainedContainmentFailure: Error | null = null;
  let operation: Promise<Readonly<UpdateSnapshot>> | null = null;

  const exclusive = (worker: (signal: AbortSignal) => Promise<Readonly<UpdateSnapshot>>) => {
    if (retainedInstaller || retainedContainmentFailure) {
      return Promise.reject(new Error("A detached shell installer is not yet proven stopped."));
    }
    if (operation) return Promise.resolve(options.state.getSnapshot());
    const controller = new AbortController();
    activeAbort = controller;
    const attempt = worker(controller.signal);
    const wrapped = attempt.finally(() => {
      if (activeAbort === controller) activeAbort = null;
      if (operation === wrapped) operation = null;
    });
    operation = wrapped;
    return wrapped;
  };

  const check = (): Promise<Readonly<UpdateSnapshot>> => exclusive(async (signal) => {
    const attempt = options.state.begin("checking", "Checking Electron shell updates");
    checked = null;
    if (!options.enabled || !supported) {
      options.state.unavailable(
        attempt,
        options.enabled ? "Electron shell updates are not published for this platform." : "Shell updates are available in packaged builds.",
        current.version,
      );
      return options.state.getSnapshot();
    }
    try {
      const releases = await options.releases.list(signal);
      if (signal.aborted) throw abortError();
      checked = selectRelease(releases, current, options.platform, options.arch);
      if (!checked) {
        options.state.unavailable(attempt, "Electron shell is up to date", current.version);
      } else {
        options.state.available(
          attempt,
          checked.semver.version,
          `Electron shell ${checked.semver.version} is available`,
          current.version,
        );
      }
    } catch {
      checked = null;
      options.state.fail(
        attempt,
        signal.aborted
          ? "Electron shell update check was cancelled."
          : "Electron shell update check failed. Check your connection and try again.",
      );
    }
    return options.state.getSnapshot();
  });

  const apply = (): Promise<Readonly<UpdateSnapshot>> => exclusive(async (signal) => {
    const snapshot = options.state.getSnapshot();
    if (
      !checked ||
      snapshot.status !== "available" ||
      snapshot.version !== checked.semver.version ||
      snapshot.currentVersion !== current.version
    ) {
      throw new Error("Check for an Electron shell update before installing it.");
    }
    const selected = checked;
    const attempt = options.state.begin(
      "applying",
      "Starting the verified Electron shell installer",
      selected.semver.version,
    );
    let marker: string | null = null;
    let installer: ShellInstallerAttempt | null = null;
    let quitCommitted = false;
    handoffReached = false;
    handoffInstaller = null;
    handoffInstallerExitCode = null;
    try {
      options.state.publishForAttempt(attempt, {
        message: "Verifying signed Electron shell provenance",
        progress: null,
        version: selected.semver.version,
      });
      const attested = await options.attestations.verify({
        assetName: selected.asset.name,
        digest: selected.asset.digest!,
        releaseTag: selected.release.tagName,
        signal,
      });
      if (signal.aborted) throw abortError();
      marker = await options.handoff.createMarker();
      if (signal.aborted) throw abortError();
      installer = await options.handoff.launch({
        assetName: attested.assetName,
        digest: attested.digest,
        marker,
        releaseTag: attested.releaseTag,
      });
      const startedAt = now();
      let exitCode: number | null = null;
      const launchedInstaller = installer;
      const exit = launchedInstaller.exited.then((code) => {
        exitCode = code;
        if (handoffInstaller === launchedInstaller) handoffInstallerExitCode = code;
      });
      for (;;) {
        const markerReady = await options.handoff.markerExists(marker);
        if (exitCode !== null) {
          throw new Error(`Installer exited before verified handoff (${exitCode}).`);
        }
        if (markerReady) {
          if (signal.aborted) throw abortError();
          handoffInstaller = launchedInstaller;
          handoffInstallerExitCode = null;
          handoffReached = true;
          break;
        }
        if (now() - startedAt >= handoffTimeoutMs) throw new Error("Installer handoff timed out.");
        options.state.publishForAttempt(attempt, {
          message: "Downloading and verifying the Electron shell installer",
          progress: null,
          version: selected.semver.version,
        });
        await Promise.race([exit, wait(heartbeatIntervalMs, signal)]);
      }
      await options.handoff.removeMarker(marker);
      marker = null;
      options.state.publishForAttempt(attempt, {
        message: "Installer verified; safely stopping FlintTrade",
        progress: 100,
        version: selected.semver.version,
      });
      await options.lifecycle.requestQuit();
      quitCommitted = true;
      options.state.complete(attempt, "Installer verified; restarting FlintTrade");
    } catch {
      let containmentFailure: unknown = null;
      if (!quitCommitted && installer) {
        handoffReached = false;
        try {
          await installer.cancel();
        } catch (error) {
          containmentFailure = error;
        }
      }
      const cancelled = signal.aborted;
      options.state.fail(
        attempt,
        containmentFailure
          ? "The shell installer could not be proven stopped. Quit is blocked."
          : cancelled
            ? "Electron shell update was cancelled before installation."
            : "Electron shell installation could not start. FlintTrade is still running.",
      );
      if (containmentFailure) {
        retainedInstaller = installer;
        retainedContainmentFailure = new Error(
          "Detached shell installer containment could not be proved.",
          { cause: containmentFailure },
        );
        throw retainedContainmentFailure;
      }
    } finally {
      if (marker) await options.handoff.removeMarker(marker).catch(() => undefined);
      await installer?.cleanup().catch(() => undefined);
      if (!quitCommitted && handoffInstaller === installer) {
        handoffInstaller = null;
        handoffInstallerExitCode = null;
      }
    }
    return options.state.getSnapshot();
  });

  return {
    apply,
    check,
    async settleForQuit(): Promise<void> {
      if (retainedInstaller) {
        try {
          await retainedInstaller.cancel();
          const containedInstaller = retainedInstaller;
          retainedInstaller = null;
          retainedContainmentFailure = null;
          await containedInstaller.cleanup().catch(() => undefined);
        } catch (error) {
          retainedContainmentFailure = new Error(
            "Detached shell installer containment could not be proved.",
            { cause: error },
          );
          throw retainedContainmentFailure;
        }
      } else if (retainedContainmentFailure) {
        throw retainedContainmentFailure;
      }
      if (handoffReached) {
        if (!handoffInstaller || handoffInstallerExitCode !== null) {
          throw new Error("The verified shell installer exited before application shutdown committed.");
        }
        return;
      }
      activeAbort?.abort();
      await operation;
    },
  };
}
