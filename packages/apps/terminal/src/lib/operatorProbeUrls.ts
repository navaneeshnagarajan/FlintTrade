/**
 * Public probe URLs for the operator incident model.
 *
 * Kept free of app imports so the fail-closed Playwright registry can allow
 * these reads without loading the desk. `scripts/apply-site-url.py` rewrites
 * the product host from this file.
 */

export const PUBLIC_SITE_PROBE_URL = "https://flinttrade.vercel.app/";
export const INSTALL_PROBE_URL = "https://flinttrade.vercel.app/install.sh";
/** Install/update and the public site. Either network failure is edge/CDN. */
export const EDGE_PROBE_URLS = [PUBLIC_SITE_PROBE_URL, INSTALL_PROBE_URL] as const;
/**
 * Neutral public-internet check. Not the product site and not a broker host.
 * A failure while the desk ping is ok is network_local.
 */
export const PUBLIC_INTERNET_PROBE_URL = "https://example.com/";
