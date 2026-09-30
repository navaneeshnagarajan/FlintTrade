/**
 * Whether the operator has enrolled an authenticator.
 *
 * Live in the Mode menu stays locked until this is true. A failed or missing
 * status read stays locked so the desk never asks for a code that was not set up.
 */

import { useQuery } from "@tanstack/react-query";
import { getAuthStatus, type AuthStatusData } from "@/services/ftApi.admin";

/** True only for an explicit enrolled flag — 0 / "false" / missing stay deferred. */
export function isTotpEnabledFlag(value: unknown): boolean {
  return value === true || value === 1 || value === "true" || value === "1";
}

/**
 * Authenticator enrolment and PIN presence for the Live menu.
 *
 * Shares the Settings auth-status query, so creating a PIN or confirming
 * an authenticator unlocks the menu without a reload. A missing or failed
 * read stays locked.
 */
export function useLiveArmFactors(): { totpEnrolled: boolean; hasPin: boolean } {
  const query = useQuery<AuthStatusData>({
    queryKey: ["ft", "auth", "status"],
    queryFn: getAuthStatus,
    staleTime: 30_000,
    retry: false,
  });
  return {
    totpEnrolled: isTotpEnabledFlag(query.data?.totp_enabled),
    hasPin: query.data?.has_pin === true,
  };
}

export function useTotpEnrolled(): boolean {
  return useLiveArmFactors().totpEnrolled;
}
