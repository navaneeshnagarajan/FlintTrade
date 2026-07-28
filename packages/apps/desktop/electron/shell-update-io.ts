import { randomUUID } from "node:crypto";
import { constants } from "node:fs";
import {
  access,
  chmod,
  copyFile,
  lstat,
  mkdir,
  mkdtemp,
  open,
  realpath,
  unlink,
} from "node:fs/promises";
import path from "node:path";
import { spawn, type ChildProcess } from "node:child_process";

import { fetchBoundedResponse, type FetchLike } from "./bounded-response";
import type {
  ShellInstallerAttempt,
  ShellInstallerHandoff,
  ShellRelease,
  ShellReleaseAsset,
  ShellReleaseSource,
} from "./shell-updater";

export const FLINTTRADE_RELEASES_API =
  "https://api.github.com/repos/navaneeshnagarajan/FlintTrade/releases?per_page=30";
const MAX_RELEASE_RESPONSE_BYTES = 2 * 1024 * 1024;
const DEFAULT_RELEASE_RESPONSE_TIMEOUT_MS = 10_000;
const SHELL_UPDATE_STAGE_PREFIX = "flinttrade-shell-update-";
const INSTALLER_TAG_PATTERN =
  /^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const INSTALLER_DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;

function exactAttestedInstallerName(platform: NodeJS.Platform, releaseTag: string, assetName: string): boolean {
  const version = releaseTag.slice(1).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const suffix = platform === "darwin"
    ? "mac-universal\\.dmg"
    : platform === "win32"
      ? "win-x64\\.exe"
      : platform === "linux"
        ? "linux-(?:x64|arm64)\\.AppImage"
        : "(?!)";
  return new RegExp(`^FlintTrade-${version}-${suffix}$`).test(assetName);
}

function validReleaseApiResponseUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return value === FLINTTRADE_RELEASES_API &&
      url.href === FLINTTRADE_RELEASES_API &&
      url.protocol === "https:" &&
      url.hostname === "api.github.com" &&
      url.port === "" &&
      url.username === "" &&
      url.password === "" &&
      url.pathname === "/repos/navaneeshnagarajan/FlintTrade/releases" &&
      url.hash === "" &&
      url.searchParams.getAll("per_page").length === 1 &&
      [...url.searchParams.keys()].length === 1 &&
      url.searchParams.get("per_page") === "30";
  } catch {
    return false;
  }
}

function releaseAsset(value: unknown): ShellReleaseAsset | null {
  if (typeof value !== "object" || value === null) return null;
  const input = value as Record<string, unknown>;
  if (typeof input.name !== "string" || typeof input.browser_download_url !== "string") return null;
  const digest = input.digest;
  if (digest !== undefined && digest !== null && typeof digest !== "string") return null;
  return {
    digest: typeof digest === "string" ? digest : null,
    downloadUrl: input.browser_download_url,
    name: input.name,
  };
}

function release(value: unknown): ShellRelease | null {
  if (typeof value !== "object" || value === null) return null;
  const input = value as Record<string, unknown>;
  if (
    typeof input.tag_name !== "string" ||
    typeof input.draft !== "boolean" ||
    typeof input.prerelease !== "boolean" ||
    !Array.isArray(input.assets) ||
    input.assets.length > 128
  ) {
    return null;
  }
  const assets = input.assets.map(releaseAsset);
  if (assets.some((asset) => asset === null)) return null;
  return {
    assets: assets as ShellReleaseAsset[],
    draft: input.draft,
    prerelease: input.prerelease,
    tagName: input.tag_name,
  };
}

export function createGithubShellReleaseSource(
  fetcher: FetchLike,
  options: { timeoutMs?: number } = {},
): ShellReleaseSource {
  const timeoutMs = options.timeoutMs ?? DEFAULT_RELEASE_RESPONSE_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0 || timeoutMs > 60_000) {
    throw new Error("The GitHub release metadata timeout must be between 1 and 60000 milliseconds.");
  }
  return {
    async list(signal): Promise<readonly ShellRelease[]> {
      const bytes = await fetchBoundedResponse({
        fetcher,
        init: {
          headers: {
            Accept: "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
          },
          redirect: "error",
        },
        label: "The GitHub release metadata response",
        maximumBytes: MAX_RELEASE_RESPONSE_BYTES,
        signal,
        timeoutMs,
        url: FLINTTRADE_RELEASES_API,
        validateResponse(response) {
          if (
            response.status !== 200 ||
            // Electron's net.fetch() currently leaves Response.url blank even
            // for a successful direct request. The request URL is the exact
            // constant above and redirect:"error" rejects every redirect, so
            // an omitted response URL is safe; any reported URL must still
            // match the official endpoint exactly.
            (response.url !== "" && !validReleaseApiResponseUrl(response.url)) ||
            response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase() !== "application/json"
          ) {
            throw new Error("The official GitHub release metadata endpoint was unavailable.");
          }
        },
      });
      let input: unknown;
      try {
        input = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
      } catch (error) {
        throw new Error("The GitHub release metadata response was invalid UTF-8 JSON.", { cause: error });
      }
      if (!Array.isArray(input) || input.length > 30) {
        throw new Error("The GitHub release metadata response had an invalid shape.");
      }
      const releases = input.map(release);
      if (releases.some((candidate) => candidate === null)) {
        throw new Error("The GitHub release metadata response contained an invalid release.");
      }
      return releases as ShellRelease[];
    },
  };
}

const POSIX_ENVIRONMENT = [
  "DISPLAY",
  "HOME",
  "LANG",
  "LC_ALL",
  "PATH",
  "TMPDIR",
  "WAYLAND_DISPLAY",
  "XDG_CURRENT_DESKTOP",
  "XDG_DATA_DIRS",
  "XDG_RUNTIME_DIR",
] as const;
const WINDOWS_ENVIRONMENT = [
  "ALLUSERSPROFILE",
  "APPDATA",
  "CommonProgramFiles",
  "CommonProgramFiles(x86)",
  "HOMEDRIVE",
  "HOMEPATH",
  "LOCALAPPDATA",
  "Path",
  "PATHEXT",
  "PROCESSOR_ARCHITECTURE",
  "PROCESSOR_ARCHITEW6432",
  "ProgramData",
  "ProgramFiles",
  "ProgramFiles(x86)",
  "SystemDrive",
  "SystemRoot",
  "TEMP",
  "TMP",
  "USERPROFILE",
  "WINDIR",
] as const;

export function shellInstallerEnvironment(
  source: NodeJS.ProcessEnv,
  platform: NodeJS.Platform,
  marker: string,
  parentPid: number = process.pid,
  macosAppBundle?: string,
  linuxAppImage?: string,
  linuxExtractedRoot?: string,
  windowsInstallDirectory?: string,
): NodeJS.ProcessEnv {
  if (!Number.isSafeInteger(parentPid) || parentPid <= 0) {
    throw new Error("Shell installer parent PID must be a positive safe integer.");
  }
  const allowed = platform === "win32" ? WINDOWS_ENVIRONMENT : POSIX_ENVIRONMENT;
  const environment: NodeJS.ProcessEnv = {};
  for (const name of allowed) {
    const value = source[name];
    if (value !== undefined) environment[name] = value;
  }
  environment.FLINTTRADE_UPDATE_HANDOFF = marker;
  environment.FLINTTRADE_UPDATE_PARENT_PID = String(parentPid);
  environment.FLINTTRADE_YES = "1";
  if (platform === "darwin") {
    if (!macosAppBundle || macosBundlePathForExecutable(`${macosAppBundle}/Contents/MacOS/FlintTrade`) !== macosAppBundle) {
      throw new Error("The macOS shell updater requires the exact running FlintTrade.app bundle.");
    }
    environment.FLINTTRADE_UPDATE_MACOS_APP_BUNDLE = macosAppBundle;
  }
  if (platform === "linux") {
    if (Boolean(linuxAppImage) === Boolean(linuxExtractedRoot)) {
      throw new Error("The Linux shell updater requires exactly one running shell target.");
    }
    if (linuxAppImage) {
      if (!path.posix.isAbsolute(linuxAppImage)) {
        throw new Error("The Linux shell updater requires the exact running AppImage.");
      }
      environment.APPIMAGE = linuxAppImage;
    } else {
      if (!linuxExtractedRoot || !path.posix.isAbsolute(linuxExtractedRoot)) {
        throw new Error("The Linux shell updater requires the exact managed extracted root.");
      }
      environment.FLINTTRADE_UPDATE_LINUX_EXTRACTED_ROOT = linuxExtractedRoot;
    }
  }
  if (platform === "win32") {
    if (
      !windowsInstallDirectory ||
      windowsInstallDirectoryForExecutable(path.win32.join(windowsInstallDirectory, "FlintTrade.exe")) !==
        path.win32.normalize(windowsInstallDirectory)
    ) {
      throw new Error("The Windows shell updater requires the exact running installation directory.");
    }
    environment.FLINTTRADE_UPDATE_WINDOWS_INSTALL_DIR = path.win32.normalize(windowsInstallDirectory);
  }
  return environment;
}

export interface NodeShellInstallerHandoffOptions {
  currentExecutablePath?: string | undefined;
  currentLinuxAppDir?: string | undefined;
  currentLinuxAppImage?: string | undefined;
  homeDirectory?: string | undefined;
  environment?: NodeJS.ProcessEnv;
  platform: NodeJS.Platform;
  privateRoot: string;
  resourcesDirectory: string;
}

export function macosBundlePathForExecutable(executablePath: string): string {
  if (!path.posix.isAbsolute(executablePath)) {
    throw new Error("The macOS shell executable path must be absolute.");
  }
  const executable = path.posix.normalize(executablePath);
  const macosDirectory = path.posix.dirname(executable);
  const contentsDirectory = path.posix.dirname(macosDirectory);
  const bundle = path.posix.dirname(contentsDirectory);
  if (
    path.posix.basename(executable) !== "FlintTrade" ||
    path.posix.basename(macosDirectory) !== "MacOS" ||
    path.posix.basename(contentsDirectory) !== "Contents" ||
    path.posix.basename(bundle) !== "FlintTrade.app" ||
    bundle.split("/").includes("AppTranslocation")
  ) {
    throw new Error("The running executable is not a supported FlintTrade.app bundle.");
  }
  return bundle;
}

export function windowsInstallDirectoryForExecutable(executablePath: string): string {
  if (!path.win32.isAbsolute(executablePath)) {
    throw new Error("The Windows shell executable path must be absolute.");
  }
  const executable = path.win32.normalize(executablePath);
  if (path.win32.basename(executable).toLowerCase() !== "flinttrade.exe") {
    throw new Error("The running executable is not a supported FlintTrade Windows installation.");
  }
  return path.win32.dirname(executable);
}

async function resolveCurrentMacosAppBundle(executablePath: string | undefined): Promise<string> {
  if (!executablePath) throw new Error("The packaged macOS executable path is unavailable.");
  const requestedBundle = macosBundlePathForExecutable(executablePath);
  const requestedMetadata = await lstat(requestedBundle);
  if (!requestedMetadata.isDirectory() || requestedMetadata.isSymbolicLink()) {
    throw new Error("The running FlintTrade.app bundle must be an ordinary directory.");
  }
  const [canonicalExecutable, canonicalRequestedBundle] = await Promise.all([
    realpath(executablePath),
    realpath(requestedBundle),
  ]);
  const canonicalBundle = macosBundlePathForExecutable(canonicalExecutable);
  if (canonicalBundle !== canonicalRequestedBundle) {
    throw new Error("The running executable escaped its FlintTrade.app bundle.");
  }
  await access(path.dirname(canonicalBundle), constants.W_OK).catch((error) => {
    throw new Error("The running FlintTrade.app location is not writable for an in-app update.", { cause: error });
  });
  return canonicalBundle;
}

async function resolveCurrentLinuxAppImage(
  appImage: string | undefined,
  appDir: string | undefined,
  executablePath: string | undefined,
): Promise<string> {
  if (
    !appImage || !appDir || !executablePath ||
    !path.isAbsolute(appImage) || !path.isAbsolute(appDir) || !path.isAbsolute(executablePath)
  ) {
    throw new Error("The packaged Linux AppImage runtime identity is unavailable.");
  }
  const [metadata, appDirMetadata] = await Promise.all([lstat(appImage), lstat(appDir)]);
  if (!metadata.isFile() || metadata.isSymbolicLink() || !appDirMetadata.isDirectory()) {
    throw new Error("The running Linux AppImage must be an ordinary file.");
  }
  const [canonical, canonicalAppDir, canonicalExecutable] = await Promise.all([
    realpath(appImage),
    realpath(appDir),
    realpath(executablePath),
  ]);
  if (!isWithin(canonicalAppDir, canonicalExecutable) || isWithin(canonicalAppDir, canonical)) {
    throw new Error("The running executable is not bound to the selected Linux AppImage runtime.");
  }
  await Promise.all([
    access(canonical, constants.W_OK),
    access(path.dirname(canonical), constants.W_OK),
  ]).catch((error) => {
    throw new Error("The running Linux AppImage is not writable for an in-app update.", { cause: error });
  });
  return canonical;
}

async function isManagedLinuxExtractedCandidate(
  executablePath: string | undefined,
  appImage: string | undefined,
  homeDirectory: string | undefined,
): Promise<boolean> {
  if (!homeDirectory || !path.isAbsolute(homeDirectory)) return false;
  const expectedRoot = path.resolve(homeDirectory, ".local", "opt", "flinttrade", "squashfs-root");
  const candidates = [executablePath, appImage].filter((value): value is string => Boolean(value));
  if (candidates.some((value) => path.isAbsolute(value) && isWithin(expectedRoot, path.resolve(value)))) {
    return true;
  }
  try {
    const canonicalRoot = await realpath(expectedRoot);
    for (const candidate of candidates) {
      if (path.isAbsolute(candidate) && isWithin(canonicalRoot, await realpath(candidate))) return true;
    }
  } catch {
    // A missing or invalid managed root cannot classify an unrelated AppImage as extracted mode.
  }
  return false;
}

async function resolveCurrentLinuxExtractedRoot(
  executablePath: string | undefined,
  homeDirectory: string | undefined,
): Promise<string> {
  if (!executablePath || !homeDirectory || !path.isAbsolute(executablePath) || !path.isAbsolute(homeDirectory)) {
    throw new Error("The managed extracted Linux shell identity is unavailable.");
  }
  const expectedRoot = path.resolve(homeDirectory, ".local", "opt", "flinttrade");
  const metadata = await lstat(expectedRoot);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new Error("The managed extracted Linux shell root must be an ordinary directory.");
  }
  const [canonicalExecutable, canonicalRoot] = await Promise.all([
    realpath(executablePath),
    realpath(expectedRoot),
  ]);
  const squashfsRoot = path.join(canonicalRoot, "squashfs-root");
  const executableName = path.basename(canonicalExecutable);
  if (
    !isWithin(squashfsRoot, canonicalExecutable) ||
    !["AppRun", "FlintTrade", "flinttrade"].includes(executableName)
  ) {
    throw new Error("The running executable is not the managed extracted Linux shell.");
  }
  const appRun = path.join(squashfsRoot, "AppRun");
  const appRunMetadata = await lstat(appRun);
  if (!appRunMetadata.isFile() || appRunMetadata.isSymbolicLink()) {
    throw new Error("The managed extracted Linux shell AppRun must be an ordinary file.");
  }
  await Promise.all([
    access(appRun, constants.X_OK),
    access(path.dirname(canonicalRoot), constants.W_OK),
  ]).catch((error) => {
    throw new Error("The managed extracted Linux shell is not writable for an in-app update.", { cause: error });
  });
  return canonicalRoot;
}

async function resolveCurrentWindowsInstallDirectory(executablePath: string | undefined): Promise<string> {
  if (!executablePath) throw new Error("The packaged Windows executable path is unavailable.");
  windowsInstallDirectoryForExecutable(executablePath);
  const metadata = await lstat(executablePath);
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw new Error("The running FlintTrade Windows executable must be an ordinary file.");
  }
  const canonicalExecutable = await realpath(executablePath);
  const installDirectory = windowsInstallDirectoryForExecutable(canonicalExecutable);
  await access(installDirectory, constants.W_OK).catch((error) => {
    throw new Error("The running FlintTrade Windows installation is not writable for an in-app update.", {
      cause: error,
    });
  });
  return installDirectory;
}

function isWithin(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

async function requireOrdinaryFile(target: string, label: string): Promise<void> {
  const metadata = await lstat(target);
  if (!metadata.isFile() || metadata.isSymbolicLink()) throw new Error(`${label} must be an ordinary file.`);
}

async function requirePrivateDirectory(
  target: string,
  parent: string,
  platform: NodeJS.Platform,
): Promise<void> {
  const metadata = await lstat(target);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new Error("Shell update handoff storage must be an ordinary directory.");
  }
  const [canonical, canonicalParent] = await Promise.all([realpath(target), realpath(parent)]);
  if (!isWithin(canonicalParent, canonical)) {
    throw new Error("Shell update handoff storage escaped its private profile.");
  }
  if (platform !== "win32") {
    const owner = process.getuid?.();
    if (owner === undefined || metadata.uid !== owner || (metadata.mode & 0o077) !== 0) {
      throw new Error("Shell update handoff storage is not private to the current user.");
    }
  }
}

function exited(child: ChildProcess): Promise<number> {
  return new Promise((resolve) => {
    child.once("error", () => resolve(-1));
    child.once("exit", (code, signal) => resolve(code ?? (signal ? -1 : 0)));
  });
}

async function waitForExit(child: ChildProcess, timeoutMs: number): Promise<boolean> {
  if (child.exitCode !== null || child.signalCode !== null) return true;
  return await new Promise((resolve) => {
    const timeout = setTimeout(() => resolve(false), timeoutMs);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolve(true);
    });
  });
}

export interface DetachedInstallerCancellationBoundary {
  alreadyExited(): boolean;
  killPosixGroup(signal: "SIGKILL" | "SIGTERM"): "missing" | "sent";
  killWindowsTree(): Promise<boolean>;
  posixGroupExists(): boolean;
  waitForExit(timeoutMs: number): Promise<boolean>;
}

export async function cancelDetachedInstaller(
  platform: NodeJS.Platform,
  boundary: DetachedInstallerCancellationBoundary,
): Promise<void> {
  if (boundary.alreadyExited()) return;
  if (platform === "win32") {
    if (!await boundary.killWindowsTree()) {
      throw new Error("Windows could not prove the detached shell installer tree was terminated.");
    }
    if (!await boundary.waitForExit(5_000)) {
      throw new Error("Windows shell installer did not exit after tree termination.");
    }
    return;
  }

  const termination = boundary.killPosixGroup("SIGTERM");
  if (termination === "missing") {
    if (boundary.alreadyExited()) return;
    throw new Error("The detached shell installer process group could not be found while its leader was alive.");
  }
  await boundary.waitForExit(3_000);
  if (!boundary.posixGroupExists() && boundary.alreadyExited()) return;
  if (boundary.killPosixGroup("SIGKILL") === "missing") {
    if (!boundary.posixGroupExists() && boundary.alreadyExited()) return;
    throw new Error("The detached shell installer process group disappeared without stopped-owner proof.");
  }
  await boundary.waitForExit(2_000);
  if (boundary.posixGroupExists() || !boundary.alreadyExited()) {
    throw new Error("The detached shell installer process group survived forced termination.");
  }
}

async function cancelChild(child: ChildProcess, platform: NodeJS.Platform): Promise<void> {
  if (child.pid === undefined) {
    if (child.exitCode !== null || child.signalCode !== null) return;
    throw new Error("The detached shell installer has no process identity.");
  }
  const pid = child.pid;
  const groupExists = (): boolean => {
    try {
      process.kill(-pid, 0);
      return true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
      if ((error as NodeJS.ErrnoException).code === "EPERM") return true;
      throw error;
    }
  };
  await cancelDetachedInstaller(platform, {
    alreadyExited: () => child.exitCode !== null || child.signalCode !== null,
    killPosixGroup(signal) {
      try {
        process.kill(-pid, signal);
        return "sent";
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ESRCH") return "missing";
        throw error;
      }
    },
    async killWindowsTree() {
      const systemRoot = process.env.SystemRoot ?? process.env.WINDIR ?? "C:\\Windows";
      const taskkill = path.win32.join(systemRoot, "System32", "taskkill.exe");
      const killer = spawn(taskkill, ["/PID", String(pid), "/T", "/F"], {
        stdio: "ignore",
        windowsHide: true,
      });
      return await exited(killer) === 0;
    },
    posixGroupExists: groupExists,
    waitForExit: (timeoutMs) => waitForExit(child, timeoutMs),
  });
}

export function createNodeShellInstallerHandoff(
  options: NodeShellInstallerHandoffOptions,
): ShellInstallerHandoff {
  if (!path.isAbsolute(options.privateRoot) || !path.isAbsolute(options.resourcesDirectory)) {
    throw new Error("Shell update private root and resources must be absolute paths.");
  }
  const privateRoot = path.resolve(options.privateRoot);
  const handoffDirectory = path.join(privateRoot, "shell-updates", "handoff");
  const logDirectory = path.join(privateRoot, "shell-updates", "logs");
  const stagingDirectory = path.join(privateRoot, "shell-updates", "staging");
  const installerLog = path.join(logDirectory, "installer.log");
  const scriptName = options.platform === "win32" ? "flinttrade-install.ps1" : "flinttrade-install.sh";
  const sourceScript = path.join(options.resourcesDirectory, "install", scriptName);

  const preparePrivateDirectory = async (directory: string): Promise<void> => {
    await mkdir(directory, { mode: 0o700, recursive: true });
    const metadata = await lstat(directory);
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
      throw new Error("Shell update handoff storage must be an ordinary directory.");
    }
    if (options.platform !== "win32") await chmod(directory, 0o700);
    await requirePrivateDirectory(directory, privateRoot, options.platform);
  };

  const prepareHandoffDirectory = async (): Promise<void> => preparePrivateDirectory(handoffDirectory);

  return {
    async createMarker(): Promise<string> {
      await prepareHandoffDirectory();
      const marker = path.join(handoffDirectory, `verified-${process.pid}-${randomUUID()}`);
      try {
        await lstat(marker);
        throw new Error("Shell update handoff marker already exists.");
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
      return marker;
    },
    async launch({ assetName, digest, marker, releaseTag }): Promise<ShellInstallerAttempt> {
      if (!INSTALLER_TAG_PATTERN.test(releaseTag)) throw new Error("Shell installer release tag is invalid.");
      if (!INSTALLER_DIGEST_PATTERN.test(digest) || !exactAttestedInstallerName(options.platform, releaseTag, assetName)) {
        throw new Error("Shell installer attestation binding is invalid.");
      }
      await prepareHandoffDirectory();
      if (!isWithin(handoffDirectory, path.resolve(marker)) || path.dirname(marker) !== handoffDirectory) {
        throw new Error("Shell installer handoff marker escaped its private directory.");
      }
      await requireOrdinaryFile(sourceScript, "The packaged shell installer");
      const macosAppBundle = options.platform === "darwin"
        ? await resolveCurrentMacosAppBundle(options.currentExecutablePath)
        : undefined;
      const managedLinuxExtracted = options.platform === "linux" && await isManagedLinuxExtractedCandidate(
        options.currentExecutablePath,
        options.currentLinuxAppImage,
        options.homeDirectory,
      );
      const linuxExtractedRoot = managedLinuxExtracted
        ? await resolveCurrentLinuxExtractedRoot(options.currentExecutablePath, options.homeDirectory)
        : undefined;
      if (linuxExtractedRoot && options.currentLinuxAppImage) {
        const appRun = await realpath(path.join(linuxExtractedRoot, "squashfs-root", "AppRun"));
        if (await realpath(options.currentLinuxAppImage) !== appRun) {
          throw new Error("The extracted Linux shell APPIMAGE identity does not match its managed AppRun.");
        }
      }
      const linuxAppImage = options.platform === "linux" && !linuxExtractedRoot
        ? await resolveCurrentLinuxAppImage(
            options.currentLinuxAppImage,
            options.currentLinuxAppDir,
            options.currentExecutablePath,
          )
        : undefined;
      const windowsInstallDirectory = options.platform === "win32"
        ? await resolveCurrentWindowsInstallDirectory(options.currentExecutablePath)
        : undefined;
      await preparePrivateDirectory(stagingDirectory);
      const canonicalStagingDirectory = await realpath(stagingDirectory);
      const stageDirectory = await mkdtemp(path.join(canonicalStagingDirectory, SHELL_UPDATE_STAGE_PREFIX));
      try {
        if (options.platform !== "win32") await chmod(stageDirectory, 0o700);
        await requirePrivateDirectory(stageDirectory, canonicalStagingDirectory, options.platform);
        const canonicalStageDirectory = await realpath(stageDirectory);
        const stageName = path.basename(canonicalStageDirectory);
        if (
          path.dirname(canonicalStageDirectory) !== canonicalStagingDirectory ||
          !stageName.startsWith(SHELL_UPDATE_STAGE_PREFIX) ||
          stageName.length === SHELL_UPDATE_STAGE_PREFIX.length
        ) {
          throw new Error("Shell update staging storage was not an exact private prefixed directory.");
        }
        const stagedScript = path.join(canonicalStageDirectory, scriptName);
        await copyFile(sourceScript, stagedScript, constants.COPYFILE_EXCL);
        await chmod(stagedScript, 0o700).catch(() => undefined);

        const environment = shellInstallerEnvironment(
          options.environment ?? process.env,
          options.platform,
          marker,
          process.pid,
          macosAppBundle,
          linuxAppImage,
          linuxExtractedRoot,
          windowsInstallDirectory,
        );
        environment.FLINTTRADE_UPDATE_ASSET_NAME = assetName;
        environment.FLINTTRADE_UPDATE_ASSET_SHA256 = digest.slice("sha256:".length);
        let command: string;
        let args: string[];
        if (options.platform === "win32") {
          const systemRoot = environment.SystemRoot ?? environment.WINDIR ?? "C:\\Windows";
          command = path.win32.join(systemRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
          args = [
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            stagedScript,
            "-Update",
            "-Ref",
            releaseTag,
            "-Yes",
          ];
        } else {
          command = "/bin/bash";
          args = [stagedScript, "--update", "--ref", releaseTag, "--yes"];
        }
        await preparePrivateDirectory(logDirectory);
        const noFollow = options.platform === "win32" ? 0 : constants.O_NOFOLLOW;
        const log = await open(
          installerLog,
          constants.O_APPEND | constants.O_CREAT | constants.O_WRONLY | noFollow,
          0o600,
        );
        try {
          const logMetadata = await log.stat();
          if (!logMetadata.isFile() || (options.platform !== "win32" && (logMetadata.mode & 0o077) !== 0)) {
            throw new Error("Shell update installer log is not an owner-only ordinary file.");
          }
          await log.write(`[${new Date().toISOString()}] launching ${releaseTag}\n`);
          let child: ChildProcess;
          try {
            child = spawn(command, args, {
              cwd: canonicalStageDirectory,
              detached: true,
              env: environment,
              stdio: ["ignore", log.fd, log.fd],
              windowsHide: true,
            });
          } catch (error) {
            await log.write(`[${new Date().toISOString()}] installer process could not start\n`).catch(() => undefined);
            throw error;
          }
          const exit = exited(child);
          await new Promise<void>((resolve, reject) => {
            child.once("spawn", resolve);
            child.once("error", reject);
          }).catch(async (error) => {
            await log.write(`[${new Date().toISOString()}] installer process could not start\n`).catch(() => undefined);
            throw error;
          });
          child.unref();
          let cancellation: Promise<void> | null = null;
          return {
            async cancel(): Promise<void> {
              cancellation ??= cancelChild(child, options.platform);
              try {
                await cancellation;
              } catch (error) {
                cancellation = null;
                throw error;
              }
            },
            async cleanup(): Promise<void> {
              // A detached pathname is never sufficient authority for recursive deletion.
              // Preserve failed, cancelled and successful stages; no automatic purge exists.
            },
            exited: exit,
          };
        } finally {
          await log.close().catch(() => undefined);
        }
      } catch (error) {
        // Even pre-launch failures retain the private stage. No later pathname
        // re-derivation is accepted as recursive-deletion authority.
        throw error;
      }
    },
    async markerExists(marker): Promise<boolean> {
      try {
        const metadata = await lstat(marker);
        if (metadata.isSymbolicLink() || !metadata.isFile() || metadata.size !== 0) {
          throw new Error("Shell update handoff marker was not an empty ordinary file.");
        }
        return true;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
        throw error;
      }
    },
    async removeMarker(marker): Promise<void> {
      try {
        await unlink(marker);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    },
  };
}
