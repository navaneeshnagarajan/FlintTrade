import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";

export function getBase(): string {
  if (import.meta.env.DEV) return "/ft-api";
  return "";
}

export function isDemoAuthSession(): boolean {
  const token = useAuthStore.getState().token;
  return token === "demo-user" || token === "dev-bypass";
}

/**
 * Build the standard request headers for every FT-API helper call.
 *
 * Attaches the configured backend ``X-API-Key`` (from
 * :mod:`connectionStore`; FlintTrade key preferred, OpenAlgo key still works
 * as a compatibility fallback) and the FlintTrade JWT
 * ``Authorization: Bearer <jwt>`` (from :mod:`authStore`) when present.
 * This ensures server-side guards like :func:`require_live_unlocked` and
 * :func:`require_auth` see the auth context regardless of which helper a
 * caller picked — previously only :func:`api.postOrder` attached these,
 * which left helper-based callers (e.g. :func:`placeBracketOrder`)
 * unauthenticated and rejected by the new mode-guard.
 *
 * The ``Content-Type`` is conditionally added only for body-bearing
 * methods (POST/PUT) so that GET/DELETE preflights are not affected.
 *
 * @param includeJson — add ``Content-Type: application/json`` (true for POST/PUT).
 */
function buildHeaders(includeJson: boolean): Record<string, string> {
  const headers: Record<string, string> = {};
  if (includeJson) headers["Content-Type"] = "application/json";

  // Read store state imperatively — these are React-store hooks but
  // ``.getState()`` works outside of components.
  const apiKey = useConnectionStore.getState().apiKey;
  const jwt = useAuthStore.getState().token;

  if (apiKey) headers["X-API-Key"] = apiKey;
  if (jwt) headers["Authorization"] = `Bearer ${jwt}`;

  return headers;
}

export async function parseResponse<T>(res: Response, endpoint: string): Promise<T> {
  const json: unknown = await res.json();
  if (
    json !== null &&
    typeof json === "object" &&
    "status" in json &&
    (json as { status: unknown }).status === "error"
  ) {
    const msg =
      "message" in json
        ? String((json as { message: unknown }).message)
        : `FT API ${endpoint} error`;
    throw new Error(msg);
  }
  const data =
    json !== null && typeof json === "object" && "data" in json
      ? (json as { data: unknown }).data
      : json;
  return data as T;
}

export async function post<T>(endpoint: string, body: object = {}): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

export async function get<T>(endpoint: string): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    headers: buildHeaders(false),
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

/**
 * POST against the backend's bare ``/v1/...`` blueprint family (e.g.
 * ``/v1/backtest/permutation``, ``/v1/oi/...``) rather than the ``/api/v1/...``
 * family the helpers above target. These blueprints register at ``/v1`` and are
 * unreachable via {@link post} (which would 404 at ``/api/v1/...``); this helper
 * makes them reachable with the SAME auth headers and error/data unwrapping, so
 * the ``/v1`` family is no longer a dead end. ``getBase()`` resolves correctly in
 * both dev (``/ft-api/v1/...`` → stripped to ``/v1/...``) and prod (``/v1/...``).
 */
export async function postV1<T>(endpoint: string, body: object = {}): Promise<T> {
  const resp = await fetch(`${getBase()}/v1/${endpoint}`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`FT API v1 ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

export async function put<T>(endpoint: string, body: object = {}): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "PUT",
    headers: buildHeaders(true),
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

export async function del<T>(endpoint: string): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "DELETE",
    headers: buildHeaders(false),
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}
