/**
 * Pending Forever-order cancels for the current tab session.
 *
 * A dropped cancel is presentation state. The dispatch ledger may already
 * hold the broker write, but the Forever orders read does not return it.
 * This record lets a reloaded terminal recognise a later trigger row. It
 * does not authorise another cancel. Storage is the shared pending-order
 * store, so sign-out clears it with every other pending order line.
 */

import { z } from "zod";
import { createPendingOrderStore, FOREVER_PENDING_CANCELS_PREFIX } from "@/lib/pendingOrderStore";

const storedPendingCancelSchema = z.object({
  orderId: z.string().min(1),
  submittedAt: z.number().finite(),
  receivedAt: z.number().finite(),
  listUpdatedAt: z.number().finite(),
});

const store = createPendingOrderStore(FOREVER_PENDING_CANCELS_PREFIX, storedPendingCancelSchema);

export function clearForeverPendingCancels(): void {
  store.clear();
}

export interface ForeverPendingCancel {
  scope: string;
  orderId: string;
  submittedAt: number;
  receivedAt: number;
  listUpdatedAt: number;
}

export function readForeverPendingCancels(scope: string): ForeverPendingCancel[] {
  return store.read(scope).map((record) => ({ scope, ...record }));
}

export function writeForeverPendingCancels(scope: string, pending: readonly ForeverPendingCancel[]): void {
  store.write(
    scope,
    pending
      .filter((record) => record.scope === scope)
      .map(({ orderId, submittedAt, receivedAt, listUpdatedAt }) => ({
        orderId, submittedAt, receivedAt, listUpdatedAt,
      })),
  );
}
