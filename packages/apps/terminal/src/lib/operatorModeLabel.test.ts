import { beforeEach, describe, expect, it } from "vitest";

import { useModeStore } from "@/stores/modeStore";
import {
  EXAMPLE_LABEL,
  operatorModeName,
  setConnectedReadPosture,
  visibleServiceNote,
} from "@/lib/operatorModeLabel";

describe("operatorModeName", () => {
  beforeEach(() => {
    useModeStore.setState({ mode: "explore" });
    setConnectedReadPosture(false);
  });

  it("names the sample session Example, never Practice", () => {
    expect(operatorModeName("explore")).toBe(EXAMPLE_LABEL);
    expect(operatorModeName()).toBe("Example");
    expect(operatorModeName("explore", true)).toBe("Example");
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

  it("rewrites a retired Explore service note to Example in every Mode", () => {
    expect(visibleServiceNote("Explore")).toBe("Example");
    expect(visibleServiceNote("connected")).toBe("connected");
    expect(visibleServiceNote(undefined)).toBeUndefined();
    useModeStore.setState({ mode: "live" });
    setConnectedReadPosture(true);
    expect(visibleServiceNote("Explore")).toBe("Example");
  });
});
