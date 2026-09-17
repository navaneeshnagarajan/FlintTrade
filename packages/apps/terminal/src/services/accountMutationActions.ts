import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore } from "@/stores/authStore";
import { FtApiError } from "./ftApi.helpers";

/** A logical UI action owns its key; HTTP attempts never allocate one. */
export class AccountMutationActions {
  private readonly pending = new Map<string, { key: string; inFlight?: Promise<unknown> }>();

  async run<T>(scope: string, send: (key: string) => Promise<T>): Promise<T> {
    if (!scope.trim() || scope.length > 2048) throw new Error("Invalid account action scope");
    let action = this.pending.get(scope);
    if (!action) {
      action = { key: crypto.randomUUID() };
      this.pending.set(scope, action);
    }
    if (action.inFlight) throw new Error("Account action is in progress");
    const current = action;
    const attempt = Promise.resolve().then(() => send(current.key));
    current.inFlight = attempt;
    try {
      const result = await attempt;
      this.pending.delete(scope);
      return result;
    } catch (error) {
      // A parsed terminal rejection ends this logical action. Timeout, retry-
      // later and server failures may conceal an invoked operation: retain it.
      if (error instanceof FtApiError && error.status >= 400 && error.status < 500
        && ![408, 425, 429].includes(error.status)) this.pending.delete(scope);
      throw error;
    } finally {
      // A failed/ambiguous outcome keeps the same identity for explicit retry.
      // No payload, credential or credential-derived hash is retained here.
      delete current.inFlight;
    }
  }

  /** Forget a UI retry identity, not the server operation or its side effects. */
  cancel(scope: string): void {
    if (this.pending.get(scope)?.inFlight) throw new Error("Account action is in progress");
    this.pending.delete(scope);
  }
}

let sessionActions = new AccountMutationActions();
let sessionFence = captureAuthSessionFence();
let sessionToken = useAuthStore.getState().token;

/** UI-level action owner, retained across remounts but never across authentication. */
export function runAccountAction<T>(scope: string, send: (key: string) => Promise<T>): Promise<T> {
  const token = useAuthStore.getState().token;
  if (!isAuthSessionFenceCurrent(sessionFence) || token !== sessionToken) {
    sessionActions = new AccountMutationActions();
    sessionFence = captureAuthSessionFence();
    sessionToken = token;
  }
  const fence = sessionFence;
  return sessionActions.run(scope, (key) => {
    if (!isAuthSessionFenceCurrent(fence) || useAuthStore.getState().token !== token) {
      throw new Error("The account action's authenticated session has changed");
    }
    return send(key);
  });
}

/** Explicit cancellation discards only the local retry identity. */
export function cancelAccountAction(scope: string): void {
  sessionActions.cancel(scope);
}
