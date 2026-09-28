import { describe, expect, it } from "vitest";
import { LAYA_NOT_QUALIFIED_FOR_LIVE, layaChipStatus, layaDisabledLiveReason } from "./layaStatus";

describe("Laya chip status", () => {
  it("follows Practice from the sidecar and never reads Down while Practice can admit", () => {
    expect(layaChipStatus({ mode: "practice", practice: "ready", live: "down" })).toBe("ready");
    expect(layaChipStatus({ mode: "practice", practice: "degraded", live: "down" })).toBe("degraded");
    expect(layaChipStatus({ mode: "explore", practice: "ready", live: "down" })).toBe("ready");
    expect(layaChipStatus({ mode: "practice", practice: "down", live: "down" })).toBe("down");
  });

  it("follows Live-facing status in Live", () => {
    expect(layaChipStatus({ mode: "live", practice: "ready", live: "down" })).toBe("down");
    expect(layaChipStatus({ mode: "live", practice: "ready", live: "ready" })).toBe("ready");
  });

  it("exposes Not qualified for Live for the chip tooltip and the Mode menu", () => {
    expect(LAYA_NOT_QUALIFIED_FOR_LIVE).toBe("Not qualified for Live");
    expect(layaDisabledLiveReason({ practice: "ready", liveQualified: false })).toBe(
      LAYA_NOT_QUALIFIED_FOR_LIVE,
    );
    expect(layaDisabledLiveReason({ practice: "degraded", liveQualified: false })).toBe(
      LAYA_NOT_QUALIFIED_FOR_LIVE,
    );
    expect(layaDisabledLiveReason({ practice: "down", liveQualified: false })).toBeNull();
    expect(layaDisabledLiveReason({ practice: "ready", liveQualified: true })).toBeNull();
  });
});
