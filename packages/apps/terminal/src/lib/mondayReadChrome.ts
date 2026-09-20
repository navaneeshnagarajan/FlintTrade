/**
 * FT-MONDAY-002 — honest Connected (read) / API smoke chrome.
 *
 * Dhan + Kotak Neo on the MSI path are non-funded read smoke only.
 * Never imply placeable Live orders. Neo has no Practice sandbox.
 */

import type { BrokerAccount } from "@/types/broker";

export const MONDAY_READ_BROKERS = ["dhan", "kotakneo"] as const;
export const CONNECTED_READ_LABEL = "Connected (read)";
export const API_SMOKE_LABEL = "API smoke";
export const NEO_OPERATOR_COPY = "Live read only until funded unlock.";

export function isMondayReadBroker(broker: string): boolean {
  return broker === "dhan" || broker === "kotakneo";
}

export function mondayReadChrome(account: Pick<BrokerAccount, "broker" | "status">): string | null {
  if (!isMondayReadBroker(account.broker)) return null;
  if (account.status !== "connected") return null;
  return CONNECTED_READ_LABEL;
}

export function mondayAccountStatusLine(account: BrokerAccount): string {
  const chrome = mondayReadChrome(account);
  if (chrome) {
    const parts = [account.broker, chrome, API_SMOKE_LABEL];
    if (account.is_primary) parts.splice(1, 0, "primary");
    if (account.broker === "kotakneo") parts.push(NEO_OPERATOR_COPY);
    return parts.join(" · ");
  }
  return "";
}
