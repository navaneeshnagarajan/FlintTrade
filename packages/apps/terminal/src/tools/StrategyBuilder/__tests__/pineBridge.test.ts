/**
 * pineBridge.test.ts
 *
 * Tests for the Pine SOURCE hand-off contract between the Pine Script Editor
 * and the Strategy Builder's sandboxed interpreter (PineTab).
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  PENDING_PINE_DRAFT_KEY,
  LOAD_PINE_DRAFT_EVENT,
  OPEN_STRATEGY_BUILDER_EVENT,
  isPineDraft,
  stashPendingPineDraft,
  hasPendingPineDraft,
  readAndClearPendingPineDraft,
  sendPineDraftToBuilder,
  type PineDraft,
} from "../pineBridge";

const DRAFT: PineDraft = { source: "//@version=5\nindicator(\"X\")\nplot(close)" };

describe("pineBridge", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("stashes, detects, and reads-and-clears a draft (one-shot)", () => {
    expect(hasPendingPineDraft()).toBe(false);

    stashPendingPineDraft(DRAFT);
    expect(hasPendingPineDraft()).toBe(true);

    expect(readAndClearPendingPineDraft()).toEqual(DRAFT);
    // One-shot: the stash is consumed.
    expect(hasPendingPineDraft()).toBe(false);
    expect(readAndClearPendingPineDraft()).toBeNull();
  });

  it("returns null (and clears) for a malformed stash", () => {
    sessionStorage.setItem(PENDING_PINE_DRAFT_KEY, "{not json");
    expect(readAndClearPendingPineDraft()).toBeNull();
    expect(sessionStorage.getItem(PENDING_PINE_DRAFT_KEY)).toBeNull();
  });

  it("rejects stashed drafts with a missing, non-string, or blank source", () => {
    for (const bad of ["null", "42", '{"source":7}', '{"source":"   "}', '{"code":"x"}']) {
      sessionStorage.setItem(PENDING_PINE_DRAFT_KEY, bad);
      expect(readAndClearPendingPineDraft()).toBeNull();
    }
  });

  it("isPineDraft validates the shape", () => {
    expect(isPineDraft(DRAFT)).toBe(true);
    expect(isPineDraft(null)).toBe(false);
    expect(isPineDraft("plot(close)")).toBe(false);
    expect(isPineDraft({ source: "" })).toBe(false);
    expect(isPineDraft({ source: 42 })).toBe(false);
  });

  it("sendPineDraftToBuilder stashes and dispatches load + open events", () => {
    const onLoad = vi.fn();
    const onOpen = vi.fn();
    window.addEventListener(LOAD_PINE_DRAFT_EVENT, onLoad);
    window.addEventListener(OPEN_STRATEGY_BUILDER_EVENT, onOpen);
    try {
      expect(sendPineDraftToBuilder(DRAFT)).toBe(true);
    } finally {
      window.removeEventListener(LOAD_PINE_DRAFT_EVENT, onLoad);
      window.removeEventListener(OPEN_STRATEGY_BUILDER_EVENT, onOpen);
    }

    expect(onLoad).toHaveBeenCalledTimes(1);
    expect((onLoad.mock.calls[0][0] as CustomEvent<PineDraft>).detail).toEqual(DRAFT);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(JSON.parse(sessionStorage.getItem(PENDING_PINE_DRAFT_KEY) ?? "null")).toEqual(DRAFT);
  });

  it("sendPineDraftToBuilder refuses a blank draft", () => {
    const onLoad = vi.fn();
    window.addEventListener(LOAD_PINE_DRAFT_EVENT, onLoad);
    try {
      expect(sendPineDraftToBuilder({ source: "   " })).toBe(false);
    } finally {
      window.removeEventListener(LOAD_PINE_DRAFT_EVENT, onLoad);
    }
    expect(onLoad).not.toHaveBeenCalled();
    expect(hasPendingPineDraft()).toBe(false);
  });
});
