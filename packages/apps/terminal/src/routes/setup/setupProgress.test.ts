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

  it("keeps one total from Create operator through Practice when the vault is already secured", () => {
    expect(setupStepTitle(0, true)).toBe("Step 1 of 2 - Create operator");
    expect(setupStepDetail(0, true)).toBe("0 of 2 completed - 2 remaining");
    expect(setupStepTitle(2, true)).toBe("Step 2 of 2 - Practice desk");
    expect(setupStepDetail(2, true)).toBe("1 of 2 completed - last step");
    expect(setupStepTitle(0, true)).not.toMatch(/of 3/);
    expect(setupStepTitle(2, true)).not.toMatch(/of 3/);
    expect(setupStepDetail(0, true)).not.toMatch(/of 3/);
    expect(setupStepDetail(2, true)).not.toMatch(/of 3/);
  });
});
