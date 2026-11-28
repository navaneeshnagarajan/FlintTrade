/**
 * Honest Connected (read) status for native Dhan and Kotak Neo.
 *
 * The status label is Connected (read). API smoke belongs in broker-connect
 * helper copy for a non-funded read, not on a Mode chip or this status line.
 * Never imply placeable Live orders. Neo has no Practice sandbox.
 */

import type { BrokerAccount } from "@/types/broker";

export const CONNECTED_READ_BROKERS = ["dhan", "kotakneo"] as const;
export const CONNECTED_READ_LABEL = "Connected (read)";
export const API_SMOKE_LABEL = "API smoke";
export const NEO_OPERATOR_COPY = "Read only. Live orders can't be sent to the broker.";

export function isConnectedReadBroker(broker: string): boolean {
  return (CONNECTED_READ_BROKERS as readonly string[]).includes(broker);
}

export function connectedReadChrome(
  account: Pick<BrokerAccount, "broker" | "status" | "read_smoke_ok">,
): string | null {
  if (!isConnectedReadBroker(account.broker)) return null;
  if (account.status !== "connected") return null;
  if (account.read_smoke_ok !== true) return null;
  return CONNECTED_READ_LABEL;
}

export function connectedAccountStatusLine(account: BrokerAccount): string {
  const chrome = connectedReadChrome(account);
  if (chrome) {
    const parts = [account.broker, chrome];
    if (account.is_primary) parts.splice(1, 0, "primary");
    if (account.broker === "kotakneo") parts.push(NEO_OPERATOR_COPY);
    return parts.join(" · ");
  }
  return "";
}
