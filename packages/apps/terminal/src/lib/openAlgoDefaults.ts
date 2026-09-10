/**
 * Shared OpenAlgo REST defaults for Settings → Broker Gateway and Ditto Add Account.
 *
 * Port 5000 is the repo convention (`flinttrade_core.config.DEFAULT_OPENALGO_HOST`,
 * Vite `/api` proxy, `OPENALGO_PORT`). Port 5001 is not an OpenAlgo default —
 * older Ditto fixtures used it, which made Add Account disagree with Gateway.
 */

export const DEFAULT_OPENALGO_HOST = "http://127.0.0.1:5000";
export const DEFAULT_OPENALGO_PORT = "5000";
export const DEFAULT_OPENALGO_WS_PORT = "8765";

/**
 * Prefer the saved Broker Gateway URL; otherwise the shared OpenAlgo default.
 */
export function resolveOpenAlgoHost(configuredHost?: string | null): string {
  const trimmed = configuredHost?.trim() ?? "";
  return trimmed || DEFAULT_OPENALGO_HOST;
}
