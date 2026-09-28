/**
 * Whether the operator has enrolled an authenticator.
 *
 * Live in the Mode menu stays locked until this is true. A failed or missing
 * status read stays locked so the desk never asks for a code that was not set up.
 */

import { useEffect, useState } from "react";
import { getAuthStatus } from "@/services/ftApi.admin";

/** True only for an explicit enrolled flag — 0 / "false" / missing stay deferred. */
function isTotpEnabledFlag(value: unknown): boolean {
  return value === true || value === 1 || value === "true" || value === "1";
}

export function useTotpEnrolled(): boolean {
  const [enrolled, setEnrolled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const status = await getAuthStatus();
        if (!cancelled) setEnrolled(isTotpEnabledFlag(status.totp_enabled));
      } catch {
        if (!cancelled) setEnrolled(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return enrolled;
}
