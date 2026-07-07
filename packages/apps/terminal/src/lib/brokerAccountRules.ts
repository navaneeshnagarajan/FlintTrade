/**
 * brokerAccountRules — the ONE primary-eligibility rule for broker accounts.
 *
 * `brokers.execution.default` (the live write target) may only be pointed at
 * an account that is connected, not already primary, and not read-only —
 * regardless of source (native / gateway / OpenAlgo). A stale or read-only
 * row promoted to write default is the exact silent-retarget failure class
 * the "native write-target fail-closed" rule exists to prevent.
 *
 * Consumed by both the Settings surface (`components/account/BrokerConnect`)
 * and the setup wizard (`routes/setup/ConnectedAccounts`) so the two can
 * never drift again (commit 5ae55537 unified Settings; the setup route had
 * kept its own divergent predicate).
 */

import type { BrokerAccount } from "@/types/broker";

/** True when `account` may be promoted to the primary / live write default. */
export function canPromotePrimaryAccount(account: BrokerAccount): boolean {
  return account.status === "connected" && !account.is_primary && account.read_only !== true;
}
