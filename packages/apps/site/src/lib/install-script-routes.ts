/**
 * Shared handler for the `/web-install.sh`, `/web-install.ps1`, `/install.sh`,
 * `/install.ps1`, `/uninstall.sh`, and `/uninstall.ps1` bootstrap-script routes.
 *
 * The site redirects to the script from the exact commit that produced the
 * deployment. This keeps the one-command bootstrap auditable even if `main`
 * or a release tag changes later.
 *
 * The web installers are the primary path and need no published release: they
 * provision a pinned, checksum-verified toolchain, build the managed source
 * checkout, and install the `flinttrade` launcher. They are deliberately
 * separate files from the desktop installers so neither one inherits the
 * other's prerequisites. The desktop install scripts instead resolve the
 * current versioned GitHub release and install the matching small Electron
 * shell after verification, then leave the local source build to the shell's
 * first run. The uninstall scripts remove only receipt-proved shells and
 * integration files, and keep the workspace unless explicitly purged.
 */

const RAW_REPOSITORY =
  'https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade';
const SOURCE_SHA_PATTERN = /^[0-9a-f]{40}$/;

export const INSTALL_SCRIPT_NAMES = {
  sh: 'flinttrade-install.sh',
  ps1: 'flinttrade-install.ps1',
  'web-sh': 'flinttrade-web-install.sh',
  'web-ps1': 'flinttrade-web-install.ps1',
  'uninstall-sh': 'flinttrade-uninstall.sh',
  'uninstall-ps1': 'flinttrade-uninstall.ps1',
} as const;

export type InstallScriptKind = keyof typeof INSTALL_SCRIPT_NAMES;

export function siteSourceSha(
  environment: Readonly<Record<string, string | undefined>> = process.env,
): string | null {
  for (const value of [environment.FLINTTRADE_SITE_SOURCE_SHA, environment.VERCEL_GIT_COMMIT_SHA]) {
    const candidate = value?.trim().toLowerCase() ?? '';
    if (SOURCE_SHA_PATTERN.test(candidate)) return candidate;
  }
  return null;
}

export function installScriptUrl(kind: InstallScriptKind, sourceSha: string): string | null {
  const candidate = sourceSha.trim().toLowerCase();
  if (!SOURCE_SHA_PATTERN.test(candidate)) return null;
  return `${RAW_REPOSITORY}/${candidate}/scripts/install/${INSTALL_SCRIPT_NAMES[kind]}`;
}

export function installScriptRedirect(
  kind: InstallScriptKind,
  sourceSha: string | null = siteSourceSha(),
): Response {
  const url = sourceSha === null ? null : installScriptUrl(kind, sourceSha);
  if (url === null) {
    return new Response('The immutable FlintTrade install-script source is unavailable.\n', {
      headers: { 'Cache-Control': 'no-store', 'Content-Type': 'text/plain; charset=utf-8' },
      status: 503,
    });
  }
  return Response.redirect(url, 302);
}
