import { describe, expect, it } from "vitest";

import { setupStepDetail, setupStepTitle } from "./setupProgress";

describe("setup progress counts", () => {
  it("counts the current step as remaining", () => {
    expect(setupStepTitle(1, false)).toBe("Step 2 of 3 - Vault");
    expect(setupStepDetail(1, false)).toBe("1 of 3 completed - 2 remaining");
  });

  it("treats the last required step as the last step", () => {
    expect(setupStepTitle(2, false)).toBe("Step 3 of 3 - Practice desk");
    expect(setupStepDetail(2, false)).toBe("2 of 3 completed - last step");
  });

  it("drops the vault step when the vault is already open", () => {
    expect(setupStepTitle(0, true)).toBe("Step 1 of 2 - Create operator");
    expect(setupStepTitle(2, true)).toBe("Step 2 of 2 - Practice desk");
    expect(setupStepDetail(2, true)).toBe("1 of 2 completed - last step");
  });
});
