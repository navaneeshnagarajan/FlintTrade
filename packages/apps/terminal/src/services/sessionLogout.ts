import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore, type LogoutResult } from "@/stores/authStore";
import { getBase } from "./ftApi.helpers";
/** Capture original authority before retiring local state. Never retry with a
 * replacement/empty token, and never let the old receipt affect a new login. */
export async function logoutSession(): Promise<LogoutResult> {
  const start = captureAuthSessionFence();
  const token = useAuthStore.getState().token ?? useAuthStore.getState().reauthToken;
  if (!token || token === "demo-user" || token === "dev-bypass") {
    if (isAuthSessionFenceCurrent(start)) useAuthStore.getState().setLoggedOut();
    return { state: "local-only" };
  }
  let pending: Promise<Response>;
  try {
    pending = fetch(`${getBase()}/v1/auth/logout`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: "{}", credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(10_000) });
  } catch (error) { pending = Promise.reject(error); }
  const retiredHere = isAuthSessionFenceCurrent(start);
  if (retiredHere) useAuthStore.getState().setLoggedOut();
  const retired = captureAuthSessionFence();
  if (retiredHere && retired.status === "logged-out") useAuthStore.setState({ logoutResult: { state: "pending" } });
  let result: LogoutResult;
  try {
    const response = await pending;
    const body: unknown = await response.json();
    const record = body && typeof body === "object" ? body as Record<string, unknown> : {};
    result = response.ok && record.status === "success" ? { state: "confirmed" } : { state: "unconfirmed", code: typeof record.code === "string" ? record.code : `HTTP ${response.status}` };
  } catch { result = { state: "unconfirmed", code: "transport_or_response_unavailable" }; }
  if (retiredHere && isAuthSessionFenceCurrent(retired) && retired.status === "logged-out") useAuthStore.setState({ logoutResult: result });
  return result;
}
