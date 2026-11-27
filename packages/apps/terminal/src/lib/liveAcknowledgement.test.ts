import { beforeEach, describe, expect, it } from "vitest";

import {
  liveAcknowledgementVersion,
  pendingLiveAcknowledgement,
  recordLiveAcknowledgement,
} from "./liveAcknowledgement";

describe("Live acknowledgement", () => {
  beforeEach(() => localStorage.removeItem("flinttrade.liveAcknowledgement"));

  it("asks from its effective date, not before", () => {
    expect(pendingLiveAcknowledgement("2026-11-19")).toBe("");
    expect(pendingLiveAcknowledgement("2026-11-20")).toMatch(/^Orders will be sent from this computer/);
  });

  it("asks once, then only again when the text changes", () => {
    const text = pendingLiveAcknowledgement("2026-11-22");
    recordLiveAcknowledgement(text);
    expect(pendingLiveAcknowledgement("2026-11-22")).toBe("");
    localStorage.setItem("flinttrade.liveAcknowledgement", liveAcknowledgementVersion(`${text} (old)`));
    expect(pendingLiveAcknowledgement("2026-11-22")).toBe(text);
  });

  it("never uses regulatory or category words on screen", () => {
    expect(pendingLiveAcknowledgement("2026-11-22")).not.toMatch(/undertaking|algo|SEBI|regulation|we |please/i);
  });
});
