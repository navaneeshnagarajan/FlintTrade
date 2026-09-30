/**
 * optionalSetupTray.test.ts — setup strip wording.
 */

import { describe, expect, it } from "vitest";

import { optionalSetupStripLabel } from "../optionalSetupTray";

describe("optionalSetupStripLabel", () => {
  it("leaves out skipped when nothing is skipped and shows it when some are", () => {
    const none = optionalSetupStripLabel(1, 0);
    expect(none).toBe("Optional setup · 1 of 4 done");
    expect(none).not.toContain("skipped");

    expect(optionalSetupStripLabel(1, 1)).toBe("Optional setup · 1 of 4 done · 1 skipped");
    expect(optionalSetupStripLabel(1, 2)).toBe("Optional setup · 1 of 4 done · 2 skipped");
  });
});
