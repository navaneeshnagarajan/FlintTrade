/**
 * One-time acknowledgement before the first switch to Live.
 *
 * The sentence comes from the dated order-rules row, so it is the same text
 * the docs table lists. Agreeing is stored with a hash of that text: the
 * question comes back only when the text changes. Practice never asks, and
 * the acknowledgement never blocks an order.
 */

import { liveAcknowledgementText } from "@/lib/orderRules";

export const LIVE_ACK_TITLE = "Turn on Live";
export const LIVE_ACK_CHECKBOX = "I understand";
export const LIVE_ACK_CANCEL = "Cancel";
export const LIVE_ACK_CONFIRM = "Turn on Live";

const STORAGE_KEY = "flinttrade.liveAcknowledgement";

/** FNV-1a over the text; a version tag, not a security control. */
export function liveAcknowledgementVersion(text: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `v1:${hash.toString(16).padStart(8, "0")}`;
}

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

/** The text to show, or "" when nothing needs acknowledging. */
export function pendingLiveAcknowledgement(on?: string): string {
  const text = on ? liveAcknowledgementText(on) : liveAcknowledgementText();
  if (!text) return "";
  return storage()?.getItem(STORAGE_KEY) === liveAcknowledgementVersion(text) ? "" : text;
}

export function recordLiveAcknowledgement(text: string): void {
  if (!text) return;
  storage()?.setItem(STORAGE_KEY, liveAcknowledgementVersion(text));
}
