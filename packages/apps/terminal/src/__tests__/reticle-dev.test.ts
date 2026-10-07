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
  it("registers every declared real store before capabilities", () => {
    const capsIdx = source.indexOf("registerCapabilities(");
    const modeIdx = source.indexOf('registerStore("mode", useModeStore)');
    expect(modeIdx).toBeGreaterThan(-1);
    expect(capsIdx).toBeGreaterThan(modeIdx);
    for (const name of ["mode", "broker", "connection", "notifications", "queries"]) {
      const storeIdx = source.indexOf(`registerStore("${name}",`);
      expect(storeIdx, `${name} registration`).toBeGreaterThan(-1);
      expect(capsIdx, `${name} registration before capabilities`).toBeGreaterThan(storeIdx);
    }
    expect(source).toMatch(
      /stores:\s*\[\s*"mode"\s*,\s*"broker"\s*,\s*"connection"\s*,\s*"notifications"\s*,\s*"queries"\s*\]/,
    );
  });

  it("retains notification and rotating query subscriptions without exposing auth state", () => {
    expect(source).toContain("getState: () => ({ items: getSnapshot() })");
    expect(source).toContain("getState: () => tanstackQueryStore(queryClient).getState()");
    expect(source).toContain("tanstackQueryStore(activeClient).subscribe(listener)");
    expect(source).toContain("useAuthStore.subscribe(");
    expect(source).toContain("unsubscribeAuth();");
    expect(source).toContain("unsubscribeQueries();");
    expect(source).not.toMatch(/registerStore\(\s*"auth"/);
  });
});
