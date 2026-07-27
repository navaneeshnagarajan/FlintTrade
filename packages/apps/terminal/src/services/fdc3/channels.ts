/**
 * channels.ts — FDC3 user channels for widget interop.
 *
 * FlintTrade implements the FDC3 user-channel model IN-PROCESS: each
 * workspace widget joins one of four colour-coded channels (persisted in
 * its panel config under `channel`), and broadcasting an instrument on a
 * channel retargets every widget joined to it. A widget pinned by params
 * is simply joined to no channel — the pre-FDC3 semantics, unchanged.
 *
 * State boundary note (CLAUDE.md): channel membership is panel config;
 * the channel CONTEXT is selection state and therefore lives in Jotai —
 * one primitive atom per channel, holding the same `WsInstrument` shape
 * the tick plane keys on. The RED channel atom IS the legacy
 * `selectedSymbolAtom`, so consumers not yet migrated (and the WS bridge
 * that follows the selection) keep working while Phase 2 lands widget by
 * widget. Only instrument contexts are carried today; if a future context
 * type needs to ride the channels, store the Context alongside rather
 * than widening these atoms.
 *
 * The app renders inside a `<JotaiProvider>` with its own store, so every
 * imperative operation here takes that store explicitly — components get
 * it from `useStore()` (see hooks.ts); tests pass their `createStore()`.
 */

import { atom } from "jotai";
import type { PrimitiveAtom, createStore } from "jotai";
import type { Context } from "@finos/fdc3";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import type { WsInstrument } from "@/types/api";
import { instrumentContext, instrumentFromContext } from "./contexts";

/** The store shape jotai's Provider hands out. */
export type JotaiStore = ReturnType<typeof createStore>;

// ---------------------------------------------------------------------------
// Channel definitions
// ---------------------------------------------------------------------------

/** FDC3 user-channel ids follow the standard's recommended naming. */
export type UserChannelId =
  | "fdc3.channel.red"
  | "fdc3.channel.green"
  | "fdc3.channel.blue"
  | "fdc3.channel.yellow";

export interface UserChannelMeta {
  id: UserChannelId;
  /** Display colour for the tab-chrome channel dot. */
  colour: string;
  /** Short label for pickers and accessibility names. */
  label: string;
}

/**
 * The four user channels. Red is the DEFAULT channel — the one unmigrated
 * consumers and the watchlist's plain row click use.
 */
export const USER_CHANNELS: readonly UserChannelMeta[] = [
  { id: "fdc3.channel.red", colour: "#ef4444", label: "Red" },
  { id: "fdc3.channel.green", colour: "#22c55e", label: "Green" },
  { id: "fdc3.channel.blue", colour: "#3b82f6", label: "Blue" },
  { id: "fdc3.channel.yellow", colour: "#eab308", label: "Yellow" },
] as const;

export const DEFAULT_CHANNEL_ID: UserChannelId = "fdc3.channel.red";

export function isUserChannelId(value: unknown): value is UserChannelId {
  return USER_CHANNELS.some((c) => c.id === value);
}

/**
 * Resolve a widget's channel membership from its panel params.
 * No `channel` key means the default (red) channel; `channel: "none"` (or
 * any non-channel value) means joined to nothing — the widget only
 * follows its own pins.
 */
export function channelFromParams(params: Record<string, unknown> | undefined): UserChannelId | null {
  const raw = params?.channel;
  if (raw === undefined) return DEFAULT_CHANNEL_ID;
  return isUserChannelId(raw) ? raw : null;
}

// ---------------------------------------------------------------------------
// Live channel membership (per panel)
// ---------------------------------------------------------------------------

/**
 * Membership is LIVE state, not a render-frozen prop: FlexLayout only
 * re-renders visible tab content, so a widget in a hidden-but-mounted tab
 * would keep following its old channel until revealed if it read
 * `params.channel` alone (Phase 2 audit finding). The persisted `channel`
 * key in the tab config remains the save/restore source of truth; the
 * atoms carry only EXPLICIT overrides written by the tab-chrome dot —
 * `undefined` means "defer to the panel params", so resolution is always
 * per-store and never frozen at atom-creation time.
 */
const membershipAtoms = new Map<string, PrimitiveAtom<UserChannelId | null | undefined>>();

export function membershipAtomFor(
  panelId: string,
): PrimitiveAtom<UserChannelId | null | undefined> {
  let existing = membershipAtoms.get(panelId);
  if (!existing) {
    existing = atom<UserChannelId | null | undefined>(undefined);
    membershipAtoms.set(panelId, existing);
  }
  return existing;
}

/** Resolve an override + params pair to the effective membership. */
export function resolveMembership(
  override: UserChannelId | null | undefined,
  params: Record<string, unknown> | undefined,
): UserChannelId | null {
  return override === undefined ? channelFromParams(params) : override;
}

/** Set a panel's live membership (the channel dot's write path). */
export function setChannelMembership(
  store: JotaiStore,
  panelId: string,
  channelId: UserChannelId | null,
): void {
  store.set(membershipAtomFor(panelId), channelId);
}

/** Read a panel's effective membership without subscribing. */
export function getChannelMembership(
  store: JotaiStore,
  panelId: string,
  params: Record<string, unknown> | undefined,
): UserChannelId | null {
  return resolveMembership(store.get(membershipAtomFor(panelId)), params);
}

// ---------------------------------------------------------------------------
// Channel context state (Jotai)
// ---------------------------------------------------------------------------

/**
 * One instrument atom per channel. Red aliases the legacy
 * `selectedSymbolAtom` so both names observe the same state during the
 * consumer migration.
 */
export const channelInstrumentAtoms: Readonly<Record<UserChannelId, PrimitiveAtom<WsInstrument | null>>> = {
  "fdc3.channel.red": selectedSymbolAtom,
  "fdc3.channel.green": atom<WsInstrument | null>(null),
  "fdc3.channel.blue": atom<WsInstrument | null>(null),
  "fdc3.channel.yellow": atom<WsInstrument | null>(null),
};

// ---------------------------------------------------------------------------
// FDC3-shaped operations (in-process desktop-agent subset)
// ---------------------------------------------------------------------------

/**
 * Broadcast a context on a user channel. Non-instrument contexts are
 * ignored (nothing consumes them yet — see the module docstring).
 */
export function broadcastToChannel(store: JotaiStore, channelId: UserChannelId, context: Context): void {
  const instrument = instrumentFromContext(context);
  if (!instrument) return;
  store.set(channelInstrumentAtoms[channelId], instrument);
}

/** Convenience: broadcast a FlintTrade instrument as fdc3.instrument. */
export function broadcastInstrument(store: JotaiStore, channelId: UserChannelId, instrument: WsInstrument): void {
  broadcastToChannel(store, channelId, instrumentContext(instrument));
}

/** Current context of a channel, as the standard's instrument shape. */
export function getChannelContext(store: JotaiStore, channelId: UserChannelId): Context | null {
  const instrument = store.get(channelInstrumentAtoms[channelId]);
  return instrument ? instrumentContext(instrument) : null;
}

/**
 * Subscribe to a channel's instrument context. Returns the unsubscribe
 * function. The handler receives the FlintTrade instrument (the shape
 * consumers actually key ticks on), not the raw Context.
 */
export function subscribeChannelInstrument(
  store: JotaiStore,
  channelId: UserChannelId,
  handler: (instrument: WsInstrument | null) => void,
): () => void {
  const targetAtom = channelInstrumentAtoms[channelId];
  return store.sub(targetAtom, () => handler(store.get(targetAtom)));
}
