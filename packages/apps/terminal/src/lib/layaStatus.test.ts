import { describe, expect, it } from "vitest";
import {
  LAYA_NOT_QUALIFIED_FOR_LIVE,
  LAYA_START_COMMAND,
  LAYA_START_DOCS_HREF,
  layaChipLabel,
  layaChipStatus,
  layaDisabledLiveReason,
  layaReasonPlain,
  layaReasonTooltip,
} from "./layaStatus";

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

  it("names each sidecar reason in plain words and keeps the first load off Down", () => {
    expect(layaReasonPlain("not_started", 8000)).toBe("Not started");
    expect(layaReasonPlain("stopped", 8000)).toBe("Stopped");
    expect(layaReasonPlain("port_in_use", 8123)).toBe("Port 8123 in use");
    expect(layaReasonPlain("still_loading", 8000)).toBe("Still loading");
    expect(layaReasonPlain("unreachable", 8000)).toBe("Unreachable");
    expect(layaReasonPlain("wrong_revision", 8000)).toBe("Wrong model revision");
    expect(layaReasonPlain(null, 8000)).toBeNull();
    const loading = layaChipLabel({ mode: "practice", practice: "down", live: "down", reason: "still_loading" });
    expect(loading).toBe("Still loading");
    expect(loading).not.toMatch(/Down/);
    expect(layaReasonTooltip("still_loading", 8000)).toBe(`Still loading. Next: ${LAYA_START_COMMAND}`);
    expect(LAYA_START_DOCS_HREF).toContain("USER_GUIDE.md#start-laya");
    expect(layaChipLabel({ mode: "practice", practice: "down", live: "down", reason: "not_started" })).toBe("Down");
  });
});
