/**
 * Pending cancels for the Orders widget.
 *
 * An acknowledged or lost cancel shows "Cancellation requested" until a
 * newer complete order read settles it. Only a confirmed CANCELLED row turns
 * it into "Order cancelled". A row that leaves the list, or ends in another
 * status, clears the line without claiming a cancel. Each order settles on its
 * own row, so confirming one pending cancel never confirms another.
 *
 * Records live in the shared pending-order store, so they survive a reload,
 * are hidden by a mode or account switch, and clear on sign-out.
 */

import { useCallback, useEffect, useState } from "react";
import { z } from "zod";
import {
  createPendingOrderStore,
  onPendingOrderOutcomesCleared,
  ORDER_PENDING_CANCELS_PREFIX,
} from "@/lib/pendingOrderStore";

const pendingCancelSchema = z.object({
  orderId: z.string().min(1),
  receivedAt: z.number().finite(),
  listUpdatedAt: z.number().finite(),
});

export type PendingOrderCancel = z.infer<typeof pendingCancelSchema>;

const store = createPendingOrderStore(ORDER_PENDING_CANCELS_PREFIX, pendingCancelSchema);

export type PendingCancelSettlement = "cancelled" | "open" | "ended";

interface Options<Row> {
  scope: string;
  /** Rows from the latest successful, complete order read. Null while unavailable. */
  rows: readonly Row[] | null;
  dataUpdatedAt: number;
  orderId: (row: Row) => string | null;
  settle: (row: Row) => PendingCancelSettlement;
  onConfirmed: (orderId: string) => void;
}

export function usePendingOrderCancels<Row>({
  scope, rows, dataUpdatedAt, orderId, settle, onConfirmed,
}: Options<Row>) {
  const [state, setState] = useState(() => ({ scope, pending: store.read(scope) }));
  const [confirmed, setConfirmed] = useState<{ scope: string; ids: string[] }>({ scope, ids: [] });

  if (state.scope !== scope) setState({ scope, pending: store.read(scope) });
  if (confirmed.scope !== scope) setConfirmed({ scope, ids: [] });

  useEffect(() => onPendingOrderOutcomesCleared(() => {
    setState((current) => ({ scope: current.scope, pending: [] }));
    setConfirmed((current) => ({ scope: current.scope, ids: [] }));
  }), []);

  const update = useCallback((next: (pending: PendingOrderCancel[]) => PendingOrderCancel[]) => {
    setState((current) => {
      const pending = next(current.pending);
      if (pending === current.pending) return current;
      store.write(current.scope, pending);
      return { scope: current.scope, pending };
    });
  }, []);

  const request = useCallback((id: string, receivedAt: number, listUpdatedAt: number) => {
    update((pending) => [
      ...pending.filter((record) => record.orderId !== id),
      { orderId: id, receivedAt, listUpdatedAt },
    ]);
    setConfirmed((current) => ({ scope: current.scope, ids: current.ids.filter((item) => item !== id) }));
  }, [update]);

  const confirm = useCallback((id: string) => {
    update((pending) => (pending.some((record) => record.orderId === id)
      ? pending.filter((record) => record.orderId !== id)
      : pending));
    setConfirmed((current) => ({
      scope: current.scope,
      ids: current.ids.includes(id) ? current.ids : [...current.ids, id],
    }));
  }, [update]);

  useEffect(() => {
    if (!rows || state.scope !== scope || state.pending.length === 0) return;
    const settledCancelled: string[] = [];
    let changed = false;
    const next = state.pending.filter((record) => {
      if (!(dataUpdatedAt > record.receivedAt) || !(dataUpdatedAt > record.listUpdatedAt)) return true;
      const row = rows.find((candidate) => orderId(candidate) === record.orderId);
      // A newer complete list without the order ends the pending line. It
      // does not say the order was cancelled.
      if (!row) {
        changed = true;
        return false;
      }
      const settlement = settle(row);
      if (settlement === "open") return true;
      changed = true;
      if (settlement === "cancelled") settledCancelled.push(record.orderId);
      return false;
    });
    if (!changed) return;
    update(() => next);
    if (settledCancelled.length > 0) {
      setConfirmed((current) => ({
        scope: current.scope,
        ids: [...current.ids.filter((id) => !settledCancelled.includes(id)), ...settledCancelled],
      }));
      settledCancelled.forEach(onConfirmed);
    }
  }, [rows, dataUpdatedAt, scope, state, orderId, settle, onConfirmed, update]);

  return {
    pending: state.scope === scope ? state.pending : [],
    confirmed: confirmed.scope === scope ? confirmed.ids : [],
    request,
    confirm,
  };
}
