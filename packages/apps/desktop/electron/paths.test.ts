import { existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { resolveDesktopPaths } from "./paths";

describe("desktop path resolution", () => {
  it("keeps source and tools outside the macOS data workspace", () => {
    const paths = resolveDesktopPaths({
      env: {},
      homeDirectory: "/Users/flint",
      platform: "darwin",
    });

    expect(paths).toEqual({
      activeSource: "/Users/flint/.flinttrade/src/FlintTrade",
      logs: "/Users/flint/Library/Application Support/flinttrade/logs",
      sourceRoot: "/Users/flint/.flinttrade/src",
      toolsRoot: "/Users/flint/.flinttrade/tools",
      workspace: "/Users/flint/Library/Application Support/flinttrade",
    });
  });

  it("matches the Python workspace defaults on Windows and Linux", () => {
    expect(
      resolveDesktopPaths({ env: {}, homeDirectory: "C:\\Users\\flint", platform: "win32" }).workspace,
    ).toBe("C:\\Users\\flint\\AppData\\Roaming\\flinttrade");
    expect(resolveDesktopPaths({ env: {}, homeDirectory: "/home/flint", platform: "linux" }).workspace).toBe(
      "/home/flint/.flinttrade",
    );
  });

  it("honours workspace overrides without creating anything", () => {
    const untouched = join("/tmp", `flinttrade-path-test-${process.pid}-${Date.now()}`);
    expect(existsSync(untouched)).toBe(false);

    const paths = resolveDesktopPaths({
      env: { FLINTTRADE_WORKSPACE_DIR: untouched },
      homeDirectory: "/Users/flint",
      platform: "darwin",
    });

    expect(paths.workspace).toBe(untouched);
    expect(paths.logs).toBe(join(untouched, "logs"));
    expect(existsSync(untouched)).toBe(false);
  });
});
