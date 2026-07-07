/**
 * UpdatesSection — in-app updater for the desktop shell (Settings → Updates).
 *
 * Hermes-style build-on-device flow, not a signed-bundle swap: "Update &
 * rebuild" asks the Rust shell (`run_self_update`) to run the LOCAL bootstrap
 * installer from the source workspace detached, then the app exits and the
 * script relaunches the freshly built version. The update check itself talks
 * to the GitHub tags API directly from the desktop webview.
 *
 * Desktop-only: web builds render nothing (the section is also absent from
 * the sidebar — see settingsConfig.buildSections). When no source workspace
 * exists on the machine, the section shows the website install one-liner to
 * copy instead of the rebuild button.
 */

import { useEffect, useState } from "react";
import { Check, Copy, Download, Loader2, RefreshCw } from "lucide-react";
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

// ---------------------------------------------------------------------------
// Constants & types
// ---------------------------------------------------------------------------

const GITHUB_TAGS_URL =
  "https://api.github.com/repos/navaneeshnagarajan/FlintTrade/tags?per_page=100";

const UNIX_ONE_LINER = "curl -fsSL https://flinttrade.vercel.app/install.sh | bash";
const WINDOWS_ONE_LINER = "irm https://flinttrade.vercel.app/install.ps1 | iex";

/** Payload of the shell's `updater_state` command. */
interface UpdaterShellState {
  app_version: string;
  src_dir: string | null;
}

type CheckState =
  | { phase: "idle" }
  | { phase: "checking" }
  | { phase: "current"; tag: string }
  | { phase: "newer"; tag: string }
  | { phase: "error"; message: string };

// ---------------------------------------------------------------------------
// Semver (v-tag) parsing & comparison — supports -beta.N style prereleases
// ---------------------------------------------------------------------------

interface ParsedVersion {
  major: number;
  minor: number;
  patch: number;
  prerelease: string[];
}

/** Parse a `vX.Y.Z[-pre]` tag (leading `v` optional). Null when not semver. */
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

/** Semver precedence: positive when a > b, negative when a < b, 0 when equal. */
export function compareVersions(a: ParsedVersion, b: ParsedVersion): number {
  if (a.major !== b.major) return a.major - b.major;
  if (a.minor !== b.minor) return a.minor - b.minor;
  if (a.patch !== b.patch) return a.patch - b.patch;
  // A release outranks any prerelease of the same core version.
  if (a.prerelease.length === 0 && b.prerelease.length === 0) return 0;
  if (a.prerelease.length === 0) return 1;
  if (b.prerelease.length === 0) return -1;
  const len = Math.max(a.prerelease.length, b.prerelease.length);
  for (let i = 0; i < len; i += 1) {
    const ai = a.prerelease[i];
    const bi = b.prerelease[i];
    if (ai === undefined) return -1; // shorter prerelease sorts lower
    if (bi === undefined) return 1;
    const aNum = /^\d+$/.test(ai);
    const bNum = /^\d+$/.test(bi);
    if (aNum && bNum) {
      if (Number(ai) !== Number(bi)) return Number(ai) - Number(bi);
    } else if (aNum !== bNum) {
      return aNum ? -1 : 1; // numeric identifiers sort below alphanumeric
    } else if (ai !== bi) {
      return ai < bi ? -1 : 1;
    }
  }
  return 0;
}

/** Pick the highest semver `v*` tag name from the GitHub tags payload. */
export function highestVersionTag(tagNames: string[]): string | null {
  let bestName: string | null = null;
  let best: ParsedVersion | null = null;
  for (const name of tagNames) {
    const parsed = parseVersionTag(name);
    if (!parsed) continue;
    if (!best || compareVersions(parsed, best) > 0) {
      best = parsed;
      bestName = name;
    }
  }
  return bestName;
}

// ---------------------------------------------------------------------------
// Section component
// ---------------------------------------------------------------------------

export function UpdatesSection() {
  // Web builds show nothing — the updater only exists inside the desktop shell.
  if (!isDesktopShell()) return null;
  return <DesktopUpdatesSection />;
}

function DesktopUpdatesSection() {
  const [shell, setShell] = useState<UpdaterShellState | null>(null);
  const [shellFailed, setShellFailed] = useState(false);
  const [check, setCheck] = useState<CheckState>({ phase: "idle" });
  const [updateStarted, setUpdateStarted] = useState(false);
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

  // Prefer the shell-reported version (Tauri package metadata); fall back to
  // the frontend build tag while loading or if the IPC call failed.
  const runningTag = shell ? `v${shell.app_version.replace(/^v/, "")}` : APP_VERSION_TAG;
  const isWindows = navigator.userAgent.includes("Windows");
  const oneLiner = isWindows ? WINDOWS_ONE_LINER : UNIX_ONE_LINER;

  async function checkForUpdates(): Promise<void> {
    setCheck({ phase: "checking" });
    let response: Response;
    try {
      response = await fetch(GITHUB_TAGS_URL, {
        headers: { Accept: "application/vnd.github+json" },
      });
    } catch {
      setCheck({
        phase: "error",
        message: "Could not reach GitHub — check your network connection and try again.",
      });
      return;
    }
    if (response.status === 403 || response.status === 429) {
      setCheck({
        phase: "error",
        message: "GitHub rate limit reached — wait a few minutes and try again.",
      });
      return;
    }
    if (!response.ok) {
      setCheck({ phase: "error", message: `GitHub responded with HTTP ${response.status}.` });
      return;
    }
    let names: string[];
    try {
      const tags = (await response.json()) as Array<{ name?: string }>;
      names = tags.map((t) => t.name ?? "").filter((n) => n.length > 0);
    } catch {
      setCheck({ phase: "error", message: "GitHub returned an unexpected response." });
      return;
    }
    const latest = highestVersionTag(names);
    if (!latest) {
      setCheck({ phase: "error", message: "No release tags found on GitHub." });
      return;
    }
    const latestParsed = parseVersionTag(latest);
    const runningParsed = parseVersionTag(runningTag);
    if (latestParsed && runningParsed && compareVersions(latestParsed, runningParsed) > 0) {
      setCheck({ phase: "newer", tag: latest });
    } else {
      setCheck({ phase: "current", tag: latest });
    }
  }

  async function startUpdate(): Promise<void> {
    setUpdateError(null);
    try {
      await invokeDesktopCommand<void>("run_self_update");
      setUpdateStarted(true);
    } catch (error) {
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

  const showRebuildPath = check.phase === "newer" && shell?.src_dir != null;
  const showOneLinerFallback = check.phase === "newer" && (shell == null || shell.src_dir == null);

  return (
    <div className="space-y-5">
      <SectionTitle>Updates</SectionTitle>

      {/* Running version */}
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
          {check.phase === "checking" ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <RefreshCw size={13} />
          )}
          {check.phase === "checking" ? "Checking…" : "Check for updates"}
        </Button>
      </div>

      {shellFailed && (
        <p className="text-xs text-loss">
          The desktop shell did not report its updater state — the version shown comes from the
          frontend build and in-app updating is unavailable.
        </p>
      )}

      {/* Check result */}
      {check.phase === "error" && <p className="text-xs text-loss">{check.message}</p>}

      {check.phase === "current" && (
        <p className="text-xs text-text-secondary">
          You are on the latest release (<span className="font-mono">{check.tag}</span>).
        </p>
      )}

      {check.phase === "newer" && (
        <div className="space-y-3 p-4 rounded-lg bg-surface-card border border-accent/30">
          <p className="text-xs text-text-primary">
            <span className="font-mono font-semibold">{check.tag}</span> is available (you are on{" "}
            <span className="font-mono">{runningTag}</span>).
          </p>

          {showRebuildPath && !updateStarted && (
            <>
              <p className="text-xs text-text-secondary leading-relaxed">
                Updating rebuilds FlintTrade from source on this machine — the same behaviour as
                re-running the website installer. Source workspace:{" "}
                <span className="font-mono break-all">{shell?.src_dir}</span>
              </p>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button type="button" size="sm" className="text-xs">
                    <Download size={13} />
                    Update &amp; rebuild
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Update to {check.tag}?</AlertDialogTitle>
                    <AlertDialogDescription>
                      FlintTrade builds the update from source on this machine, which takes
                      roughly 10–20 minutes. The app will close whilst the build runs and
                      relaunch itself once the new version is installed.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={() => void startUpdate()}>
                      Rebuild and relaunch
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
              {updateError && <p className="text-xs text-loss">{updateError}</p>}
            </>
          )}

          {updateStarted && (
            <p className="text-xs text-text-secondary">
              Update started — the app will close in a moment and relaunch itself when the build
              completes.{" "}
              {isWindows ? (
                <>The build runs in its own console window so you can follow the progress.</>
              ) : (
                <>
                  Build output is written to <span className="font-mono">self_update.log</span> in
                  the FlintTrade workspace directory.
                </>
              )}
            </p>
          )}

          {showOneLinerFallback && (
            <div className="space-y-2">
              <p className="text-xs text-text-secondary leading-relaxed">
                No source workspace was found on this machine, so the in-app rebuild is
                unavailable. Run the bootstrap installer in a terminal instead — it performs the
                same update:
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
        Updates are built from the GitHub release tags on your own machine — nothing is downloaded
        as a prebuilt binary, so there is no unsigned-installer warning and nothing to trust beyond
        the source itself.
      </p>
    </div>
  );
}
