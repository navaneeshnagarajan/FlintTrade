/**
 * Shared handler for the `/install.sh` and `/install.ps1` bootstrap-script
 * routes.
 *
 * The site never snapshots the scripts: it redirects to the raw GitHub copy
 * on `main`, so `curl -fsSL https://<site>/install.sh | bash` always fetches
 * the current script without a site redeploy. The scripts themselves resolve
 * the newest release tag at run time and build FlintTrade on the user's own
 * machine (see `scripts/install/` in the repository).
 */

const RAW_BASE =
  'https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install';

export const INSTALL_SCRIPTS = {
  sh: `${RAW_BASE}/flinttrade-install.sh`,
  ps1: `${RAW_BASE}/flinttrade-install.ps1`,
} as const;

export function installScriptRedirect(kind: keyof typeof INSTALL_SCRIPTS): Response {
  return Response.redirect(INSTALL_SCRIPTS[kind], 302);
}
