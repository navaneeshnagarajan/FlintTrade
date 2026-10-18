import type { AccountAuthorityIdentity } from "@/hooks/useDataScope";

export type AccountQueryFetchStatus = "fetching" | "paused" | "idle";
export type AccountQueryAvailability = "loading" | "ready" | "stale" | "unavailable";

export interface AccountQueryAvailabilityInput {
  accountReadsEnabled: boolean;
  fetchStatus: AccountQueryFetchStatus;
  hasData: boolean;
  isError: boolean;
  isLoading: boolean;
  isOnline: boolean;
  isStale: boolean;
}

/**
 * Presentation only: retain same-scope evidence, including genuine zero.
 * Fresh cached evidence remains ready during a refetch; fetching alone does
 * not expire it. Query isStale owns age/invalidation, without another clock.
 * Offline, paused, disabled or failed reads cannot claim current evidence.
 * Callers retire foreign/session data and select Explore samples separately.
 */
export function resolveAccountQueryAvailability({
  accountReadsEnabled, fetchStatus, hasData, isError, isLoading, isOnline, isStale,
}: AccountQueryAvailabilityInput): AccountQueryAvailability {
  const unavailable = !accountReadsEnabled || !isOnline || isError || fetchStatus === "paused";
  if (hasData) return unavailable || isStale ? "stale" : "ready";
  return !unavailable && isLoading && fetchStatus === "fetching" ? "loading" : "unavailable";
}

interface AccountQueryUiInput {
  accountReadsEnabled: boolean;
  fetchStatus: AccountQueryFetchStatus;
  hasData: boolean;
  isError: boolean;
  isExplore: boolean;
  isLoading: boolean;
}

/**
 * One presentation policy for account-backed TanStack Query surfaces.
 *
 * TanStack Query v5's `isLoading` is true only for a pending query that is
 * actively fetching. `isPending` alone is deliberately not accepted here:
 * disabled and offline-paused observers can remain pending indefinitely.
 */
export function resolveAccountQueryUi({
  accountReadsEnabled,
  fetchStatus,
  hasData,
  isError,
  isExplore,
  isLoading,
}: AccountQueryUiInput) {
  const isPaused = accountReadsEnabled && fetchStatus === "paused";
  const isFrozen =
    !isExplore && hasData && (!accountReadsEnabled || isPaused || isError);
  const canRefetch = !isExplore && accountReadsEnabled && !isPaused;

  return {
    canRefetch,
    isFrozen,
    isPaused,
    showInitialLoading: !isExplore && isLoading,
  };
}

/** Capture a detached, immutable authority snapshot at an intent boundary. */
export function captureAccountAuthority(
  identity: AccountAuthorityIdentity,
): AccountAuthorityIdentity {
  return Object.freeze({
    mode: identity.mode,
    scopeKey: identity.scopeKey,
    brokerType: identity.brokerType,
    accountId: identity.accountId,
  });
}

/** Exact equality for the four fields that define account action authority. */
export function accountAuthorityMatches(
  expected: AccountAuthorityIdentity,
  current: AccountAuthorityIdentity,
): boolean {
  return expected.mode === current.mode
    && expected.scopeKey === current.scopeKey
    && expected.brokerType === current.brokerType
    && expected.accountId === current.accountId;
}

/** Invoke a callback only if authority still matches at the instant of execution. */
export function runWithMatchingAccountAuthority<T>(
  expected: AccountAuthorityIdentity,
  getCurrent: () => AccountAuthorityIdentity,
  callback: () => T,
): T | undefined {
  if (!accountAuthorityMatches(expected, getCurrent())) return undefined;
  return callback();
}

/**
 * Query `enabled` only controls automatic scheduling: an imperative refetch
 * bypasses it. Every UI handler therefore re-checks its current read gate.
 */
export function runGuardedAccountRefetch(
  canRefetch: boolean,
  refetch: () => unknown,
): void {
  if (!canRefetch) return;
  void refetch();
}
