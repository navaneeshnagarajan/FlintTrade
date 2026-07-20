/**
 * Shared handler for the `/install.sh`, `/install.ps1`, `/uninstall.sh`, and
 * `/uninstall.ps1` bootstrap-script routes.
 *
 * The site never snapshots the scripts: it redirects to the raw GitHub copy on
 * `main`, so `curl -fsSL https://<site>/install.sh | bash` always fetches the
 * current script without a site redeploy. The install scripts resolve the
 * current desktop-release manifest at run time and install the matching release
 * asset by default, with source builds available only via explicit flags. The
 * uninstall scripts remove the app plus its disposable residue and keep BOTH
 * the workspace and the WebView storage (in-app saved content) unless
 * explicitly purged.
 */

const RAW_BASE =
  'https://raw.githubusercontent.com/navaneeshnagarajan/FlintTrade/main/scripts/install';

export const INSTALL_SCRIPTS = {
  sh: `${RAW_BASE}/flinttrade-install.sh`,
  ps1: `${RAW_BASE}/flinttrade-install.ps1`,
  'uninstall-sh': `${RAW_BASE}/flinttrade-uninstall.sh`,
  'uninstall-ps1': `${RAW_BASE}/flinttrade-uninstall.ps1`,
} as const;

export function installScriptRedirect(kind: keyof typeof INSTALL_SCRIPTS): Response {
  return Response.redirect(INSTALL_SCRIPTS[kind], 302);
}
