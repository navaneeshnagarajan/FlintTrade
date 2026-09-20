/**
 * Official Reticle scaffold must register a real store before capabilities.
 * An empty `stores: []` makes state asserts indistinguishable from a healthy
 * empty read (Codex P1 on #261).
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const source = fs.readFileSync(path.resolve(import.meta.dirname, "../reticle-dev.ts"), "utf8");

describe("reticle-dev capabilities", () => {
  it("registers the mode store before declaring capabilities", () => {
    const storeIdx = source.indexOf('registerStore("mode", useModeStore)');
    const capsIdx = source.indexOf("registerCapabilities(");
    expect(storeIdx).toBeGreaterThan(-1);
    expect(capsIdx).toBeGreaterThan(storeIdx);
    expect(source).toMatch(/stores:\s*\[\s*"mode"\s*\]/);
  });
});
