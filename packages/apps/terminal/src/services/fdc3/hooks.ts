/**
 * hooks.ts — React bindings for the FDC3 channel bus.
 *
 * Components never touch the store plumbing: `useChannelInstrument`
 * subscribes reactively through the app's Jotai Provider, and
 * `useBroadcastInstrument` hands back a stable broadcaster bound to the
 * same store, so widget code reads like the FDC3 verbs it implements.
 */

import { useCallback } from "react";
import { atom, useAtomValue, useStore } from "jotai";
import type { WsInstrument } from "@/types/api";
import {
  broadcastInstrument,
  channelInstrumentAtoms,
  DEFAULT_CHANNEL_ID,
  type UserChannelId,
} from "./channels";

// A widget joined to no channel reads a constant null without violating
// the rules of hooks — the atom itself is the constant.
const NO_CHANNEL_ATOM = atom<WsInstrument | null>(null);

/**
 * The instrument currently broadcast on a channel, or null when the
 * widget is joined to no channel (`channelId: null`) or nothing has been
 * broadcast yet.
 */
export function useChannelInstrument(channelId: UserChannelId | null): WsInstrument | null {
  return useAtomValue(channelId ? channelInstrumentAtoms[channelId] : NO_CHANNEL_ATOM);
}

/**
 * A stable broadcaster for the given channel (defaults to red). Widgets
 * that SET the focused instrument (watchlist row click, quick-trade
 * hover) call this instead of writing `selectedSymbolAtom` directly.
 */
export function useBroadcastInstrument(channelId: UserChannelId = DEFAULT_CHANNEL_ID) {
  const store = useStore();
  return useCallback(
    (instrument: WsInstrument) => broadcastInstrument(store, channelId, instrument),
    [store, channelId],
  );
}
