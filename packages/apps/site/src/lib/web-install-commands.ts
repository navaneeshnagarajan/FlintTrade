/**
 * Canonical one-command installers for the self-hosted web app.
 *
 * Keep these separate from /install.sh and /install.ps1: those routes are the
 * release-gated Electron shell installers. Both the homepage and /download
 * render this single source so their commands cannot drift.
 */
export const WEB_INSTALL_COMMANDS = [
  {
    platform: 'macOS / Linux',
    command: 'curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash',
    needs:
      'No prerequisites. Provisions a pinned, checksum-verified toolchain, builds the managed source checkout, and installs the flinttrade launcher.',
  },
  {
    platform: 'Windows 10/11',
    command: 'irm https://flinttrade.vercel.app/web-install.ps1 | iex',
    needs:
      'No prerequisites. Run in a normal (non-Administrator) PowerShell window; the same bootstrap installs a per-user launcher and Start Menu shortcut.',
  },
] as const;
