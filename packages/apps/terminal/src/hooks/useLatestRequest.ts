/**
 * useLatestRequest — the one request-generation / in-flight-key guard.
 *
 * Three option-chain surfaces (`OIChart`, the retired `OIHeatmap` and
 * `OptionChain/useOptionChainData`) each grew their own copy of the same
 * guard, character for character apart from the identifier names. They carry
 * the heaviest race pins in the widget suite, so the copies could not simply
 * be deleted — they are extracted here instead, once, with their own tests.
 *
 * The problem it solves. A polled market-data panel has two overlapping
 * hazards that a plain `cancelled` flag does not cover:
 *
 *   1. **Stale identity.** The operator switches symbol or expiry while a
 *      request is in flight. The response arrives describing the PREVIOUS
 *      contract. Committing it paints one instrument's open interest under
 *      another instrument's header.
 *   2. **Overlapping polls.** The refresh interval fires again while the
 *      previous request for the SAME identity is still out. Firing a second
 *      request neither cancels the first nor helps: the two can settle out of
 *      order, so the older snapshot can overwrite the newer one.
 *
 * The guard answers both with one monotonic generation counter plus a map of
 * the request generation currently in flight per fetch key:
 *
 *   - {@link LatestRequestGuard.begin} refuses to start a second request for a
 *     key whose in-flight request belongs to the CURRENT generation — that is
 *     the "skip a poll tick while one is pending" rule.
 *   - Any identity change bumps the generation, which both invalidates every
 *     in-flight response and releases the block, so an abandoned request can
 *     never wedge a later, validated round trip for the same key.
 *   - {@link LatestRequestTicket.isCurrent} is the post-await gate: a response
 *     may only be committed while its generation is still the newest AND its
 *     key still matches the key the component is rendering.
 *
 * `activeKey` is captured during render, not in an effect, because a response
 * that resolves between a render and its effects must already be judged
 * against the key the component is currently showing.
 *
 * Usage:
 *
 * ```ts
 * const requests = useLatestRequest(requestKey);
 *
 * const fetchData = useCallback(async () => {
 *   const ticket = requests.begin(requestKey);
 *   if (!ticket) return;                      // one is already in flight
 *   setLoading(true);
 *   try {
 *     const chain = await getOptionChain(...);
 *     if (!ticket.isCurrent()) return;        // superseded — drop it
 *     setChain(chain);
 *   } finally {
 *     if (ticket.settle()) setLoading(false); // settle() frees the slot
 *   }
 * }, [requests, requestKey]);
 * ```
 */

import { useEffect, useMemo, useRef } from "react";

/** A single in-flight request's handle. */
export interface LatestRequestTicket {
  /**
   * True while this request is still the newest one AND its key still matches
   * the guard's active key. Check it after every await, before committing.
   */
  isCurrent(): boolean;
  /**
   * Release this request's in-flight slot (only if it still owns it) and
   * report whether the ticket is still current — i.e. whether the caller
   * should apply its settled/loading-finished state.
   */
  settle(): boolean;
}

export interface LatestRequestGuard {
  /**
   * Claim the in-flight slot for `fetchKey`.
   *
   * Returns `null` when a request of the current generation is already in
   * flight for that key, which is the caller's signal to skip this tick.
   */
  begin(fetchKey: string): LatestRequestTicket | null;
  /**
   * Invalidate every in-flight request. Call from an interval/effect teardown;
   * an identity change invalidates automatically.
   */
  invalidate(): void;
}

export function useLatestRequest(activeKey: string): LatestRequestGuard {
  const generationRef = useRef(0);
  const inFlightKeysRef = useRef(new Map<string, number>());
  const activeKeyRef = useRef(activeKey);
  // Assigned during render on purpose: a response that resolves between this
  // render and its effects must be judged against what is on screen NOW.
  activeKeyRef.current = activeKey;

  useEffect(() => {
    // The identity changed — every in-flight response now describes something
    // the component is no longer showing. The in-flight map is deliberately
    // NOT cleared: each entry is how its own request releases its slot, and
    // every read of it is generation-checked.
    generationRef.current += 1;
  }, [activeKey]);

  return useMemo<LatestRequestGuard>(() => ({
    invalidate() {
      generationRef.current += 1;
    },
    begin(fetchKey: string): LatestRequestTicket | null {
      if (inFlightKeysRef.current.get(fetchKey) === generationRef.current) return null;
      const generation = ++generationRef.current;
      inFlightKeysRef.current.set(fetchKey, generation);
      const isCurrent = () => (
        generation === generationRef.current
        && fetchKey === activeKeyRef.current
      );
      return {
        isCurrent,
        settle() {
          if (inFlightKeysRef.current.get(fetchKey) === generation) {
            inFlightKeysRef.current.delete(fetchKey);
          }
          return isCurrent();
        },
      };
    },
  }), []);
}
