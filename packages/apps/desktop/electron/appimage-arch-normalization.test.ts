import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

interface AppImageArchNormalizer {
  (buildResult: { artifactPaths?: string[] }): string[];
  canonicaliseAppImageArch(artifactPaths: string[]): string[];
}

const require = createRequire(import.meta.url);
const normalize = require("../scripts/normalize-appimage-arch.cjs") as AppImageArchNormalizer;

const VERSION = "0.6.0-beta.13";

describe("electron-builder AppImage arch normalisation", () => {
  let directory: string;

  beforeEach(() => {
    directory = mkdtempSync(path.join(tmpdir(), "flinttrade-appimage-"));
  });

  afterEach(() => {
    rmSync(directory, { force: true, recursive: true });
  });

  const artifact = (name: string): string => {
    const target = path.join(directory, name);
    writeFileSync(target, "artifact");
    return target;
  };

  it("renames the x64 AppImage from electron-builder's x86_64 name to the canonical linux-x64 name", () => {
    const produced = artifact(`FlintTrade-${VERSION}-linux-x86_64.AppImage`);
    const canonical = path.join(directory, `FlintTrade-${VERSION}-linux-x64.AppImage`);

    const renamed = normalize({ artifactPaths: [produced] });

    expect(renamed).toEqual([canonical]);
    expect(existsSync(canonical)).toBe(true);
    expect(existsSync(produced)).toBe(false);
  });

  it("leaves the arm64 AppImage and non-AppImage installers untouched", () => {
    const arm64 = artifact(`FlintTrade-${VERSION}-linux-arm64.AppImage`);
    const dmg = artifact(`FlintTrade-${VERSION}-mac-universal.dmg`);
    const exe = artifact(`FlintTrade-${VERSION}-win-x64.exe`);

    const renamed = normalize({ artifactPaths: [arm64, dmg, exe] });

    expect(renamed).toEqual([]);
    expect(existsSync(arm64)).toBe(true);
    expect(existsSync(dmg)).toBe(true);
    expect(existsSync(exe)).toBe(true);
  });

  it("only matches the x86_64 suffix, never an x86_64 substring elsewhere in the path", () => {
    const decoy = artifact(`FlintTrade-${VERSION}-linux-x86_64.AppImage.blockmap`);

    const renamed = normalize({ artifactPaths: [decoy] });

    expect(renamed).toEqual([]);
    expect(existsSync(decoy)).toBe(true);
  });

  it("tolerates a build result with no artifacts", () => {
    expect(normalize({ artifactPaths: [] })).toEqual([]);
    expect(normalize({})).toEqual([]);
  });
});
