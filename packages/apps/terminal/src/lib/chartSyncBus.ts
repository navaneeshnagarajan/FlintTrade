/**
 * chartSyncBus.ts
 *
 * Minimal time-scale sync bus for chart panels living in the same window.
 *
 * The Three Panel preset (and any future multi-chart preset) lays out several
 * independent ChartWidget panels that must scroll and zoom together. Each
 * panel joins a named group with a per-instance id; when one panel's visible
 * logical range changes it publishes the range, and every OTHER member of the
 * group applies it.
 *
 * Feedback-loop safety is split between the bus and its callers:
 *  - The bus NEVER delivers a publication back to the publisher (self
 *    exclusion by id), so a publisher cannot be asked to re-apply its own
 *    range.
 *  - A subscriber applying a received range must not re-publish the change
 *    events that the apply provokes on its own chart. The bus cannot see
 *    those chart events, so the caller guards them: set a ref before calling
 *    `setVisibleLogicalRange`, skip publishing while it is set, and clear it
 *    afterwards (ChartWidget's `isApplyingSyncRangeRef`). Even if a guard
 *    slips, ranges converge — a chart whose range already matches does not
 *    emit a change event — so the pairing degrades to one redundant hop, not
 *    an unbounded loop.
 *
 * Module-level singleton, no globals, no timers. Subscriptions are held in a
 * plain Map keyed by group name; empty groups are dropped so an abandoned
 * group name retains nothing.
 */

/** Visible logical range of a lightweight-charts time scale. */
export interface ChartSyncRange {
  readonly from: number;
  readonly to: number;
}

type ChartSyncListener = (range: ChartSyncRange) => void;

/** group name → (member id → listener). */
const groups = new Map<string, Map<string, ChartSyncListener>>();

/**
 * Join a sync group.
 *
 * `id` identifies this member within the group — publications carrying the
 * same id are not delivered to it. Subscribing again with the same id
 * replaces the previous listener. Returns an unsubscribe function; a stale
 * unsubscribe (kept after a same-id resubscribe) is a no-op rather than
 * tearing down the newer listener.
 */
export function subscribeChartSync(
  group: string,
  id: string,
  listener: ChartSyncListener,
): () => void {
  let members = groups.get(group);
  if (!members) {
    members = new Map();
    groups.set(group, members);
  }
  members.set(id, listener);

  return () => {
    const current = groups.get(group);
    if (!current || current.get(id) !== listener) return;
    current.delete(id);
    if (current.size === 0) groups.delete(group);
  };
}

/**
 * Publish a visible-range change to every member of `group` except the
 * publisher itself (matched by `id`).
 */
export function publishChartSync(group: string, id: string, range: ChartSyncRange): void {
  const members = groups.get(group);
  if (!members) return;
  members.forEach((listener, memberId) => {
    if (memberId === id) return;
    listener(range);
  });
}
