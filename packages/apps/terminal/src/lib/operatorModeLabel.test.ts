import { beforeEach, describe, expect, it } from "vitest";

import { useModeStore } from "@/stores/modeStore";
import {
  operatorModeName,
  setConnectedReadPosture,
  visibleServiceNote,
} from "@/lib/operatorModeLabel";

describe("operatorModeName", () => {
  beforeEach(() => {
    useModeStore.setState({ mode: "explore" });
    setConnectedReadPosture(false);
  });

  it("names the sample session Practice", () => {
    expect(operatorModeName("explore")).toBe("Practice");
    expect(operatorModeName()).toBe("Practice");
  });

  it("names a practice session Practice until Connected (read) is posted", () => {
    useModeStore.setState({ mode: "practice" });
    expect(operatorModeName()).toBe("Practice");
    setConnectedReadPosture(true);
    expect(operatorModeName()).toBe("Connected (read)");
  });

  it("names Live even when a stale Connected (read) posture is still set", () => {
    setConnectedReadPosture(true);
    expect(operatorModeName("live", true)).toBe("Live");
  });

  it("does not treat the sample session as Connected (read)", () => {
    expect(operatorModeName("explore", true)).toBe("Practice");
  });

  it("rewrites a retired Explore service note to the current Mode name", () => {
    expect(visibleServiceNote("Explore")).toBe("Practice");
    expect(visibleServiceNote("connected")).toBe("connected");
    expect(visibleServiceNote(undefined)).toBeUndefined();
    useModeStore.setState({ mode: "live" });
    expect(visibleServiceNote("Explore")).toBe("Live");
  });
});
