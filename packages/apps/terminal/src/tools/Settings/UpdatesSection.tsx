/**
 * UpdatesSection — in-app updater for the desktop shell (Settings -> Updates).
 *
 * Preferred path: the shell's signed native updater (check_native_update /
 * apply_native_update) downloads, verifies, and installs the update in place,
 * then restarts the app — one click, no OS installer. When the native check
 * fails (unsigned or dev builds, older shells, unsupported package formats)
 * the section falls back to the release manifest + bundled installer script,
 * and source rebuilds remain available when a source workspace exists.
 */

import { useEffect, useState } from "react";
import { Check, Copy, Download, Hammer, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { invokeDesktopCommand, isDesktopShell } from "@/lib/desktopShell";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import { SectionTitle } from "./shared";

const UNIX_ONE_LINER = "curl -fsSL https://flinttrade.vercel.app/install.sh | bash";
const WINDOWS_ONE_LINER = "irm https://flinttrade.vercel.app/install.ps1 | iex";

/**
 * Rolling release-manifest URL for the running build's channel: beta when the
 * version tag carries a pre-release suffix, stable otherwise. Published by the
 * desktop-release workflow alongside the Tauri updater feed.
 */
export function desktopReleaseManifestUrl(versionTag: string): string {
  const channel = versionTag.includes("-") ? "beta" : "stable";
  return `https://github.com/navaneeshnagarajan/FlintTrade/releases/download/updater-${channel}/flinttrade-desktop-manifest.json`;
}

interface UpdaterShellState {
  app_version: string;
  platform_os?: string | null;
  platform_arch?: string | null;
  src_dir: string | null;
  installer_script?: string | null;
}

interface DesktopReleaseAsset {
  os: "macos" | "windows" | "linux";
  arch: "x64" | "arm64";
  kind: "dmg" | "nsis" | "appimage" | "deb" | "rpm";
  name: string;
  size: number;
  url: string;
}

interface DesktopReleaseManifest {
  tag: string;
  version: string;
  channel: "beta" | "stable";
  prerelease: boolean;
  html_url: string;
  assets: DesktopReleaseAsset[];
}

interface PlatformHint {
  platform_os?: string | null;
  platform_arch?: string | null;
  os?: string | null;
  arch?: string | null;
}

/** Payload of the shell's `check_native_update` command. */
interface NativeUpdateCheck {
  available: boolean;
  version: string | null;
  notes: string | null;
}

type CheckState =
  | { phase: "idle" }
  | { phase: "checking" }
  | { phase: "current"; tag: string }
  | { phase: "native"; version: string | null; notes: string | null }
  | { phase: "newer"; manifest: DesktopReleaseManifest; asset: DesktopReleaseAsset | null }
  | { phase: "indeterminate"; manifest: DesktopReleaseManifest; asset: DesktopReleaseAsset | null }
  | { phase: "error"; message: string };

type UpdateKind = "binary" | "source";

interface ParsedVersion {
  major: number;
  minor: number;
  patch: number;
  prerelease: string[];
}

export function parseVersionTag(tag: string): ParsedVersion | null {
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/.exec(tag.trim());
  if (!match) return null;
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: match[4] ? match[4].split(".") : [],
  };
}

export function compareVersions(a: ParsedVersion, b: ParsedVersion): number {
  if (a.major !== b.major) return a.major - b.major;
  if (a.minor !== b.minor) return a.minor - b.minor;
  if (a.patch !== b.patch) return a.patch - b.patch;
  if (a.prerelease.length === 0 && b.prerelease.length === 0) return 0;
  if (a.prerelease.length === 0) return 1;
  if (b.prerelease.length === 0) return -1;
  const len = Math.max(a.prerelease.length, b.prerelease.length);
  for (let i = 0; i < len; i += 1) {
    const ai = a.prerelease[i];
    const bi = b.prerelease[i];
    if (ai === undefined) return -1;
    if (bi === undefined) return 1;
    const aNum = /^\d+$/.test(ai);
    const bNum = /^\d+$/.test(bi);
    if (aNum && bNum) {
      if (Number(ai) !== Number(bi)) return Number(ai) - Number(bi);
    } else if (aNum !== bNum) {
      return aNum ? -1 : 1;
    } else if (ai !== bi) {
      return ai < bi ? -1 : 1;
    }
  }
  return 0;
}

export function matchingPlatformAsset(
  manifest: DesktopReleaseManifest,
  platformOrUserAgent: PlatformHint | string = navigator.userAgent,
  userAgent = navigator.userAgent,
): DesktopReleaseAsset | null {
  const platform = typeof platformOrUserAgent === "string" ? null : platformOrUserAgent;
  const ua = (typeof platformOrUserAgent === "string" ? platformOrUserAgent : userAgent).toLowerCase();
  const hintedOs = normalisePlatformOs(platform?.platform_os ?? platform?.os);
  const hintedArch = normalisePlatformArch(platform?.platform_arch ?? platform?.arch);
  const os = hintedOs ?? osFromUserAgent(ua);
  const arch = hintedArch ?? archFromUserAgent(ua);
  if (!os) return null;

  const kinds: DesktopReleaseAsset["kind"][] =
    os === "windows" ? ["nsis"] : os === "macos" ? ["dmg"] : ["appimage", "deb", "rpm"];
  for (const kind of kinds) {
    const exact = manifest.assets.find((asset) => asset.os === os && asset.arch === arch && asset.kind === kind);
    if (exact) return exact;
    if (!arch) {
      const osMatch = manifest.assets.find((asset) => asset.os === os && asset.kind === kind);
      if (osMatch) return osMatch;
    }
  }
  return null;
}

function normalisePlatformOs(value: string | null | undefined): DesktopReleaseAsset["os"] | null {
  const key = value?.toLowerCase();
  if (key === "macos" || key === "darwin" || key === "mac") return "macos";
  if (key === "windows" || key === "win32" || key === "win") return "windows";
  if (key === "linux") return "linux";
  return null;
}

function normalisePlatformArch(value: string | null | undefined): DesktopReleaseAsset["arch"] | null {
  const key = value?.toLowerCase();
  if (key === "arm64" || key === "aarch64") return "arm64";
  if (key === "x64" || key === "x86_64" || key === "amd64") return "x64";
  return null;
}

function osFromUserAgent(userAgent: string): DesktopReleaseAsset["os"] | null {
  if (userAgent.includes("windows")) return "windows";
  if (userAgent.includes("mac")) return "macos";
  if (userAgent.includes("linux")) return "linux";
  return null;
}

function archFromUserAgent(userAgent: string): DesktopReleaseAsset["arch"] | null {
  if (userAgent.includes("arm64") || userAgent.includes("aarch64")) return "arm64";
  if (userAgent.includes("x86_64") || userAgent.includes("amd64") || userAgent.includes("x64")) return "x64";
  if (userAgent.includes("windows") || userAgent.includes("linux")) return "x64";
  return null;
}

export function UpdatesSection() {
  if (!isDesktopShell()) return null;
  return <DesktopUpdatesSection />;
}

function DesktopUpdatesSection() {
  const [shell, setShell] = useState<UpdaterShellState | null>(null);
  const [shellFailed, setShellFailed] = useState(false);
  const [check, setCheck] = useState<CheckState>({ phase: "idle" });
  const [updateStarted, setUpdateStarted] = useState<UpdateKind | null>(null);
  const [nativeApplying, setNativeApplying] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let mounted = true;
    invokeDesktopCommand<UpdaterShellState>("updater_state")
      .then((state) => {
        if (mounted) setShell(state);
      })
      .catch(() => {
        if (mounted) setShellFailed(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const runningTag = shell ? `v${shell.app_version.replace(/^v/, "")}` : APP_VERSION_TAG;
  const isWindows = navigator.userAgent.includes("Windows");
  const oneLiner = isWindows ? WINDOWS_ONE_LINER : UNIX_ONE_LINER;

  async function checkForUpdates(): Promise<void> {
    setCheck({ phase: "checking" });
    setUpdateError(null);

    // Preferred path: the shell's signed native updater. When the check
    // rejects (unsigned or dev build, older shell without the command,
    // unsupported package format), fall back silently to the release
    // manifest + installer-script flow below.
    let native: NativeUpdateCheck | null = null;
    try {
      native = (await invokeDesktopCommand<NativeUpdateCheck | undefined>("check_native_update")) ?? null;
    } catch {
      native = null;
    }
    if (native) {
      if (native.available) {
        setCheck({ phase: "native", version: native.version, notes: native.notes });
      } else {
        setCheck({ phase: "current", tag: runningTag });
      }
      return;
    }

    let response: Response;
    try {
      response = await fetch(desktopReleaseManifestUrl(runningTag), {
        headers: { Accept: "application/json" },
      });
    } catch {
      setCheck({
        phase: "error",
        message: "Could not reach the FlintTrade release manifest — check your network connection and try again.",
      });
      return;
    }
    if (response.status === 403 || response.status === 429) {
      setCheck({
        phase: "error",
        message: "Release lookup is rate limited — wait a few minutes and try again.",
      });
      return;
    }
    if (!response.ok) {
      setCheck({ phase: "error", message: `Release lookup responded with HTTP ${response.status}.` });
      return;
    }
    let manifest: DesktopReleaseManifest;
    try {
      manifest = (await response.json()) as DesktopReleaseManifest;
    } catch {
      setCheck({ phase: "error", message: "The release manifest returned an unexpected response." });
      return;
    }
    const latestParsed = parseVersionTag(manifest.tag);
    const runningParsed = parseVersionTag(runningTag);
    const asset = matchingPlatformAsset(manifest, shell ?? undefined);
    if (!latestParsed || !runningParsed) {
      // Fail safe: an unparseable version tag must never be reported as "up to
      // date" (that would silently hide a real update). Surface the uncertainty
      // and still offer the update path — prefer showing it over hiding it.
      setCheck({ phase: "indeterminate", manifest, asset });
    } else if (compareVersions(latestParsed, runningParsed) > 0) {
      setCheck({ phase: "newer", manifest, asset });
    } else {
      setCheck({ phase: "current", tag: manifest.tag });
    }
  }

  async function startUpdate(kind: UpdateKind, tag?: string): Promise<void> {
    setUpdateError(null);
    try {
      if (kind === "binary") {
        await invokeDesktopCommand<void>("run_binary_update", tag ? { tag } : undefined);
      } else {
        await invokeDesktopCommand<void>("run_self_update");
      }
      setUpdateStarted(kind);
    } catch (error) {
      setUpdateError(error instanceof Error ? error.message : String(error));
    }
  }

  async function applyNativeUpdate(): Promise<void> {
    setUpdateError(null);
    setNativeApplying(true);
    try {
      // The shell restarts the app once the update is installed, so this
      // promise normally never resolves — the busy state holds until the
      // window is torn down.
      await invokeDesktopCommand<void>("apply_native_update");
    } catch (error) {
      setNativeApplying(false);
      setUpdateError(error instanceof Error ? error.message : String(error));
    }
  }

  async function copyOneLiner(): Promise<void> {
    try {
      await navigator.clipboard?.writeText(oneLiner);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied — the command stays visible to copy manually.
    }
  }

  const release = check.phase === "newer" || check.phase === "indeterminate" ? check : null;
  const indeterminate = check.phase === "indeterminate";
  // The bundled installer script resolves the correct release asset server-side,
  // so a failed client-side platform match must NOT hide the one-click update —
  // require only that a script is present. The website one-liner stays the
  // fallback only when there is genuinely no in-app update path.
  const showBinaryPath = release != null && shell?.installer_script != null;
  const showSourcePath = release != null && shell?.src_dir != null;
  const showOneLinerFallback = release != null && !showBinaryPath && !showSourcePath;

  return (
    <div className="space-y-5">
      <SectionTitle>Updates</SectionTitle>

      <div className="flex items-center gap-3 p-4 rounded-lg bg-surface-card border border-border-default">
        <div className="flex-none w-10 h-10 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center">
          <Download size={18} className="text-accent" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-text-primary">FlintTrade Desktop</div>
          <div className="text-xs text-text-muted">
            Running version <span className="font-mono text-text-secondary">{runningTag}</span>
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto text-xs"
          onClick={() => void checkForUpdates()}
          disabled={check.phase === "checking"}
        >
          {check.phase === "checking" ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          {check.phase === "checking" ? "Checking..." : "Check for updates"}
        </Button>
      </div>

      {shellFailed && (
        <p className="text-xs text-loss">
          The desktop shell did not report its updater state — the version shown comes from the
          frontend build and in-app updating is unavailable.
        </p>
      )}

      {check.phase === "error" && <p className="text-xs text-loss">{check.message}</p>}

      {check.phase === "current" && (
        <p className="text-xs text-text-secondary">
          You are on the latest desktop release (<span className="font-mono">{check.tag}</span>).
        </p>
      )}

      {check.phase === "native" && (
        <div className="space-y-3 p-4 rounded-lg bg-surface-card border border-accent/30">
          <p className="text-xs text-text-primary">
            {check.version ? (
              <>
                Version{" "}
                <span className="font-mono font-semibold">v{check.version.replace(/^v/, "")}</span>{" "}
                is available (you are on <span className="font-mono">{runningTag}</span>).
              </>
            ) : (
              <>A newer desktop build is available (you are on <span className="font-mono">{runningTag}</span>).</>
            )}
          </p>

          {check.notes && (
            <p className="text-xs text-text-secondary leading-relaxed whitespace-pre-wrap">{check.notes}</p>
          )}

          {nativeApplying ? (
            <p className="flex items-center gap-2 text-xs text-text-secondary" role="status">
              <Loader2 size={13} className="animate-spin" />
              Updating — the app will restart itself.
            </p>
          ) : (
            <>
              <p className="text-xs text-text-secondary leading-relaxed">
                The update downloads in the background, verifies its signature, and installs in
                place. The app restarts itself once it is ready.
              </p>
              <Button type="button" size="sm" className="text-xs" onClick={() => void applyNativeUpdate()}>
                <Download size={13} />
                Update and restart
              </Button>
            </>
          )}

          {updateError && <p className="text-xs text-loss">{updateError}</p>}
        </div>
      )}

      {release && (
        <div className="space-y-3 p-4 rounded-lg bg-surface-card border border-accent/30">
          {indeterminate ? (
            <p className="text-xs text-text-primary">
              Could not determine whether{" "}
              <span className="font-mono font-semibold">{release.manifest.tag}</span> is newer than
              your current version (<span className="font-mono">{runningTag}</span>). Re-run the
              check above, or install it below if you want the latest build.
            </p>
          ) : (
            <p className="text-xs text-text-primary">
              <span className="font-mono font-semibold">{release.manifest.tag}</span> is available
              (you are on <span className="font-mono">{runningTag}</span>).
            </p>
          )}

          {showBinaryPath && !updateStarted && (
            <>
              <p className="text-xs text-text-secondary leading-relaxed">
                {release.asset ? (
                  <>
                    The default update downloads the published installer asset for this machine:{" "}
                    <span className="font-mono break-all">{release.asset.name}</span>.
                  </>
                ) : (
                  <>The bundled installer script will download the matching desktop package for this machine.</>
                )}{" "}
                The app will close while the installer runs.
              </p>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button type="button" size="sm" className="text-xs">
                    <Download size={13} />
                    Download &amp; install update
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Install {release.manifest.tag}?</AlertDialogTitle>
                    <AlertDialogDescription>
                      FlintTrade will launch the bundled installer script, download the matching
                      desktop package, close this app, and let the OS installer replace the old app.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={() => void startUpdate("binary", release.manifest.tag)}>
                      Install and relaunch
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </>
          )}

          {showSourcePath && !updateStarted && (
            <div className="space-y-2">
              <p className="text-xs text-text-secondary leading-relaxed">
                Advanced fallback: rebuild FlintTrade from source in{" "}
                <span className="font-mono break-all">{shell?.src_dir}</span>. This needs the full
                developer toolchain and can take 10-20 minutes.
              </p>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button type="button" variant="outline" size="sm" className="text-xs">
                    <Hammer size={13} />
                    Rebuild from source
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Rebuild {release.manifest.tag} from source?</AlertDialogTitle>
                    <AlertDialogDescription>
                      FlintTrade will run the source-build installer from the local checkout. The app
                      will close while the build runs and relaunch after installation.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={() => void startUpdate("source")}>
                      Rebuild and relaunch
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          )}

          {updateError && <p className="text-xs text-loss">{updateError}</p>}

          {updateStarted && (
            <p className="text-xs text-text-secondary">
              {updateStarted === "binary" ? "Installer update" : "Source rebuild"} started — the app
              will close in a moment.{" "}
              {isWindows ? (
                <>A console or installer window may show progress.</>
              ) : (
                <>
                  Output is written to <span className="font-mono">self_update.log</span> in the
                  FlintTrade workspace directory when available.
                </>
              )}
            </p>
          )}

          {showOneLinerFallback && (
            <div className="space-y-2">
              <p className="text-xs text-text-secondary leading-relaxed">
                This desktop build does not include an updater script. Run the installer in a terminal:
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 min-w-0 px-3 py-2 rounded bg-surface-base border border-border-default text-xs font-mono text-text-primary overflow-x-auto whitespace-nowrap">
                  {oneLiner}
                </code>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="flex-none text-xs"
                  onClick={() => void copyOneLiner()}
                  aria-label="Copy install command"
                >
                  {copied ? <Check size={13} /> : <Copy size={13} />}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      <p className="text-xs text-text-muted leading-relaxed">
        Updates install signed desktop release builds in one click where supported, falling back to
        the published installer assets. Source rebuilds remain available for contributor checkouts
        and advanced operators.
      </p>
    </div>
  );
}
