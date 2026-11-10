import { beforeEach, describe, expect, it } from "vitest";

import { useModeStore } from "@/stores/modeStore";
import {
  EXAMPLE_LABEL,
  operatorModeName,
  visibleServiceNote,
} from "@/lib/operatorModeLabel";

describe("operatorModeName", () => {
  beforeEach(() => {
    useModeStore.setState({ mode: "explore" });
  });

  it("names the sample session Example, never Practice", () => {
    expect(operatorModeName("explore")).toBe(EXAMPLE_LABEL);
    expect(operatorModeName()).toBe("Example");
  });

  it("names Practice, Live, and Unavailable from the claim and never Connected (read)", () => {
    useModeStore.setState({ mode: "practice" });
    expect(operatorModeName()).toBe("Practice");
    expect(operatorModeName("practice")).toBe("Practice");
    expect(operatorModeName("live")).toBe("Live");
    expect(operatorModeName("unavailable")).toBe("Unavailable");
    for (const mode of ["explore", "practice", "live", "unavailable"] as const) {
      expect(operatorModeName(mode)).not.toBe("Connected (read)");
    }
  });

  it("rewrites a retired Explore service note to Example in every Mode", () => {
    expect(visibleServiceNote("Explore")).toBe("Example");
    expect(visibleServiceNote("connected")).toBe("connected");
    expect(visibleServiceNote(undefined)).toBeUndefined();
    useModeStore.setState({ mode: "live" });
    expect(visibleServiceNote("Explore")).toBe("Example");
  });
});
