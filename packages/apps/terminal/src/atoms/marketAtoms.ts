import { atom, type WritableAtom } from "jotai";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { resolveMarketDataScope } from "@/lib/marketDataScope";
import type { WsTick, WsInstrument } from "@/types/api";

/** Writable per-instrument tick atom, as returned by {@link tickAtomFamily}. */
export type TickAtom = WritableAtom<WsTick | null, [WsTick | null | ((previous: WsTick | null) => WsTick | null), string?], void>;

function currentMarketScope(): string {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return resolveMarketDataScope({ mode: useModeStore.getState().mode, accounts, activeAccountId });
}

// Weak observations keep no abandoned Jotai store alive. Synchronous Zustand
// notifications retire even unmounted cached observations before a B render.
const scopeObservers = new Set<WeakRef<(scope: string) => void>>();
function retireOtherScopes(): void {
  if (scopeObservers.size === 0) return;
  const scope = currentMarketScope();
  for (const reference of scopeObservers) {
    const notify = reference.deref();
    if (notify) notify(scope);
    else scopeObservers.delete(reference);
  }
}
useModeStore.subscribe?.(retireOtherScopes);
useBrokerStore.subscribe?.(retireOtherScopes);

interface TickObservation {
  scope: string;
  tick: WsTick;
  notify: (scope: string) => void;
  reference: WeakRef<(scope: string) => void>;
}
function scopedTickAtom(): TickAtom {
  const observation = atom<TickObservation | null>(null);
  return atom(
    (get) => {
      const stored = get(observation);
      if (!stored) return null;
      return stored.scope === currentMarketScope() ? stored.tick : null;
    },
    (get, set, update: WsTick | null | ((previous: WsTick | null) => WsTick | null), capturedScope = currentMarketScope()) => {
      const scope = currentMarketScope();
      if (capturedScope !== scope) return;
      const previous = get(observation);
      const current = previous?.scope === scope ? previous.tick : null;
      const tick = typeof update === "function" ? update(current) : update;
      if (previous) scopeObservers.delete(previous.reference);
      if (!tick) { set(observation, null); return; }
      const notify = (nextScope: string) => {
        if (nextScope === scope) return;
        scopeObservers.delete(reference);
        set(observation, null);
      };
      const reference = new WeakRef(notify);
      scopeObservers.add(reference);
      set(observation, { scope, tick, notify, reference });
    },
  );
}

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
  const entry: TickAtomEntry = { atom: scopedTickAtom(), mountCount: 0 };
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
 * Derived atom: indices + MCX summary for TickerBar.
 * NSE/BSE indices and MCX metals/energy share one marquee. `venue` is the
 * public badge (NSE, BSE, MCX) — quote exchanges such as NSE_INDEX stay on
 * `exchange` and must not be shown as a second venue.
 */
export const indicesSummaryAtom = atom((get) => {
  return [
    { name: "NIFTY 50", venue: "NSE", exchange: "NSE_INDEX", data: get(niftyAtom) },
    { name: "SENSEX", venue: "BSE", exchange: "BSE_INDEX", data: get(sensexAtom) },
    { name: "BANK NIFTY", venue: "NSE", exchange: "NSE_INDEX", data: get(bankniftyAtom) },
    { name: "VIX", venue: "NSE", exchange: "NSE_INDEX", data: get(vixAtom) },
    { name: "GOLD", venue: "MCX", exchange: "MCX", data: get(goldAtom) },
    { name: "SILVER", venue: "MCX", exchange: "MCX", data: get(silverAtom) },
    { name: "CRUDEOIL", venue: "MCX", exchange: "MCX", data: get(crudeOilAtom) },
    { name: "NATGAS", venue: "MCX", exchange: "MCX", data: get(naturalGasAtom) },
  ];
});

/**
 * Selected symbol atom — set by WatchlistWidget when a row is clicked.
 * Other widgets (Chart, Depth, Greeks, etc.) can subscribe to react.
 */
export const selectedSymbolAtom = atom<WsInstrument | null>(null);
