/**
 * Canonical one-command installers for the self-hosted web app.
 *
 * Keep these separate from /install.sh and /install.ps1: those routes are the
 * release-gated Electron shell installers. Both the homepage and /download
 * render this single source so their commands cannot drift.
 *
 * Commands are origin-aware so a Hostinger / custom-domain deploy can set
 * FLINTTRADE_SITE_URL without a code edit. The default argument is the
 * canonical public origin so flint.toml's site-URL rewrite still has a
 * literal to update.
 */

const DEFAULT_SITE_ORIGIN = 'https://flinttrade.vercel.app';

function originBase(origin: string): string {
  return origin.replace(/\/$/, '');
}

export function webInstallCommands(origin: string = DEFAULT_SITE_ORIGIN) {
  const base = originBase(origin);
  return [
    {
      platform: 'macOS / Linux',
      command: `curl -fsSL ${base}/web-install.sh | bash`,
      needs:
        'No prerequisites. Provisions a pinned, checksum-verified toolchain, builds the managed source checkout, and installs the flinttrade launcher.',
    },
    {
      platform: 'Windows 10/11',
      command: `irm ${base}/web-install.ps1 | iex`,
      needs:
        'No prerequisites. Run in a normal (non-Administrator) PowerShell window; the same bootstrap installs a per-user launcher and Start Menu shortcut.',
    },
  ] as const;
}

export function uninstallCommands(origin: string = DEFAULT_SITE_ORIGIN) {
  const base = originBase(origin);
  return [
    {
      platform: 'macOS / Linux',
      command: `curl -fsSL ${base}/uninstall.sh | bash`,
      purgeLabel: '# add --purge to also delete the workspace and its data',
      purge: `curl -fsSL ${base}/uninstall.sh | bash -s -- --purge`,
      needs:
        'Removes the app, launcher, and managed tools. Your workspace and its data are kept unless you add --purge.',
    },
    {
      platform: 'Windows 10/11',
      command: `irm ${base}/uninstall.ps1 | iex`,
      purgeLabel: '# add -Purge to also delete the workspace and its data',
      purge: `& ([scriptblock]::Create((irm ${base}/uninstall.ps1))) -Purge`,
      needs:
        'Removes the app, launcher, and managed tools. Your workspace and its data are kept unless you add -Purge.',
    },
  ] as const;
}

export function desktopInstallCommands(origin: string = DEFAULT_SITE_ORIGIN) {
  const base = originBase(origin);
  return [
    {
      platform: 'macOS (Apple Silicon & Intel)',
      command: `curl -fsSL ${base}/install.sh | bash`,
      needs: 'Downloads and verifies the universal DMG, installs FlintTrade.app, and launches the shell.',
    },
    {
      platform: 'Linux (x64 & arm64)',
      command: `curl -fsSL ${base}/install.sh | bash`,
      needs: 'Downloads and verifies the matching AppImage, with an automatic no-FUSE fallback.',
    },
    {
      platform: 'Windows 10/11 (x64)',
      command: `irm ${base}/install.ps1 | iex`,
      needs: 'Downloads and verifies the x64 NSIS setup before running the per-user installer.',
    },
  ] as const;
}

export const WEB_INSTALL_COMMANDS = webInstallCommands();
