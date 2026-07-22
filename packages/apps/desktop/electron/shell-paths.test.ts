import { mkdtempSync, rmSync, symlinkSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { assertShellUserDataSeparated, resolveShellUserDataPath } from "./shell-paths";

describe("Electron shell profile path", () => {
  it("uses a sibling profile on macOS instead of colliding with the workspace", () => {
    const appData = "/Users/operator/Library/Application Support";
    const profile = resolveShellUserDataPath(appData, "darwin");
    expect(profile).toBe("/Users/operator/Library/Application Support/flinttrade-shell");
    expect(() => assertShellUserDataSeparated(
      profile,
      "/Users/operator/Library/Application Support/flinttrade",
      "darwin",
    )).not.toThrow();
  });

  it("rejects a profile nested in the workspace, case-insensitively on Windows", () => {
    expect(() => assertShellUserDataSeparated(
      "C:\\Users\\operator\\AppData\\Roaming\\FlintTrade\\Shell",
      "c:\\users\\operator\\appdata\\roaming\\flinttrade",
      "win32",
    )).toThrow(/must be separate/i);
  });

  it("rejects case aliases conservatively on macOS", () => {
    expect(() => assertShellUserDataSeparated(
      "/Users/operator/Library/Application Support/flinttrade-shell",
      "/Users/operator/Library/Application Support/FLINTTRADE-SHELL",
      "darwin",
    )).toThrow(/must be separate/i);
  });

  it.runIf(process.platform !== "win32")("rejects an existing symlink alias", () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "flinttrade-shell-paths-"));
    try {
      const profile = path.join(root, "flinttrade-shell");
      const alias = path.join(root, "workspace-alias");
      symlinkSync(profile, alias);
      expect(() => assertShellUserDataSeparated(profile, alias, process.platform)).toThrow(/must be separate/i);
    } finally {
      rmSync(root, { force: true, recursive: true });
    }
  });
});
