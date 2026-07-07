import { atom } from "jotai";
import type { WsTick, WsInstrument } from "@/types/api";

/** Writable per-instrument tick atom, as returned by {@link tickAtomFamily}. */
export type TickAtom = ReturnType<typeof atom<WsTick | null>>;

/**
 * Atom cache for per-instrument tick data.
 * Key format: "{exchange}:{symbol}" e.g. "NSE_INDEX:NIFTY"
 *
 * Using a plain Map instead of atomFamily (deprecated in jotai/utils, removed
 * in v3). Interface is identical — callers use
 * tickAtomFamily("NSE_INDEX:NIFTY") unchanged.
 *
 * Boundedness: the cache is capped at {@link TICK_ATOM_CACHE_LIMIT} entries so
 * a long session that touches thousands of symbols (option-chain scans,
 * screeners, watchlist churn) does not retain every atom for the tab's
 * lifetime. Eviction is LRU over entries with no active subscriber:
 *
 *   - Every `tickAtomFamily(key)` access refreshes the entry's recency, so
 *     both readers (render-time lookups) and the WS bridge writer keep hot
 *     instruments at the back of the queue.
 *   - Each atom tracks its jotai mount count via `onMount` — an atom that any
 *     store is currently subscribed to (useAtomValue / store.sub) is NEVER
 *     evicted, so identity semantics for active subscribers are preserved.
 *   - The module-level index/MCX atoms below are pinned: derived atoms hold
 *     direct references to them, so eviction would silently detach them from
 *     the WS bridge's writes.
 */
interface TickAtomEntry {
  atom: TickAtom;
  /** Number of jotai stores currently mounting this atom (active subscribers). */
  mountCount: number;
}

/**
 * Maximum number of cached tick atoms. Generous — a heavy layout (several
 * option chains + watchlists + indices) stays comfortably below this — while
 * still bounding a scan-everything session to a few hundred small objects.
 */
export const TICK_ATOM_CACHE_LIMIT = 512;

const _tickAtomCache = new Map<string, TickAtomEntry>();

/** Keys that must never be evicted (module-level atoms reference them directly). */
const _pinnedKeys = new Set<string>();

function evictIfOverLimit(): void {
  if (_tickAtomCache.size <= TICK_ATOM_CACHE_LIMIT) return;
  // Map iteration order is insertion order; accesses re-insert, so the front
  // of the map is the least-recently-used end.
  for (const [key, entry] of _tickAtomCache) {
    if (_tickAtomCache.size <= TICK_ATOM_CACHE_LIMIT) return;
    if (entry.mountCount > 0 || _pinnedKeys.has(key)) continue;
    _tickAtomCache.delete(key);
  }
  // If every entry is mounted or pinned the cache may exceed the cap — that is
  // fine: it is then bounded by the number of live subscribers, not history.
}

export function tickAtomFamily(key: string): TickAtom {
  const existing = _tickAtomCache.get(key);
  if (existing) {
    // Touch: re-insert so Map insertion order doubles as LRU recency.
    _tickAtomCache.delete(key);
    _tickAtomCache.set(key, existing);
    return existing.atom;
  }
  const entry: TickAtomEntry = { atom: atom<WsTick | null>(null), mountCount: 0 };
  // Track active subscribers through jotai's own mount lifecycle. onMount runs
  // when the first subscriber in a store mounts the atom; the returned cleanup
  // runs when the last one in that store releases it.
  entry.atom.onMount = () => {
    entry.mountCount += 1;
    return () => {
      entry.mountCount -= 1;
    };
  };
  _tickAtomCache.set(key, entry);
  evictIfOverLimit();
  return entry.atom;
}

/** Diagnostic: number of tick atoms currently cached (bounded by eviction). */
export function tickAtomCacheSize(): number {
  return _tickAtomCache.size;
}

/**
 * Create a tick atom whose cache entry is exempt from eviction. Only for
 * module-level atoms that hold a direct reference for the tab's lifetime.
 */
function pinnedTickAtom(key: string): TickAtom {
  _pinnedKeys.add(key);
  return tickAtomFamily(key);
}

// Derived index atoms (convenience) — pinned: these module-level references
// live for the tab's lifetime, so their cache entries must never be evicted
// (an evicted entry would be recreated as a NEW atom and the WS bridge would
// write ticks the old reference never sees).
export const niftyAtom = pinnedTickAtom("NSE_INDEX:NIFTY");
export const sensexAtom = pinnedTickAtom("BSE_INDEX:SENSEX");
export const bankniftyAtom = pinnedTickAtom("NSE_INDEX:BANKNIFTY");
export const vixAtom = pinnedTickAtom("NSE_INDEX:INDIAVIX");

// MCX commodity atoms
export const goldAtom = pinnedTickAtom("MCX:GOLD");
export const silverAtom = pinnedTickAtom("MCX:SILVER");
export const crudeOilAtom = pinnedTickAtom("MCX:CRUDEOIL");
export const naturalGasAtom = pinnedTickAtom("MCX:NATURALGAS");

/**
 * Derived atom: indices + MCX summary for TickerBar
 * Matches Groww 915 ticker: NIFTY, SENSEX, BANKNIFTY, VIX + GOLD, SILVER, CRUDEOIL, NATURALGAS
 */
export const indicesSummaryAtom = atom((get) => {
  return [
    { name: "NIFTY 50", data: get(niftyAtom) },
    { name: "SENSEX", data: get(sensexAtom) },
    { name: "BANK NIFTY", data: get(bankniftyAtom) },
    { name: "VIX", data: get(vixAtom) },
    { name: "GOLD", data: get(goldAtom) },
    { name: "SILVER", data: get(silverAtom) },
    { name: "CRUDEOIL", data: get(crudeOilAtom) },
    { name: "NATGAS", data: get(naturalGasAtom) },
  ];
});

/**
 * Selected symbol atom — set by WatchlistWidget when a row is clicked.
 * Other widgets (Chart, Depth, Greeks, etc.) can subscribe to react.
 */
export const selectedSymbolAtom = atom<WsInstrument | null>(null);
