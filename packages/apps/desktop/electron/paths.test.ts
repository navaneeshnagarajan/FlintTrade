import { existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { resolveDesktopPaths } from "./paths";

describe("desktop path resolution", () => {
  it("keeps source and tools outside the macOS data workspace", () => {
    const paths = resolveDesktopPaths({
      currentWorkingDirectory: "/checkout/FlintTrade",
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
      resolveDesktopPaths({
        currentWorkingDirectory: "C:\\checkout\\FlintTrade",
        env: {},
        homeDirectory: "C:\\Users\\flint",
        platform: "win32",
      }).workspace,
    ).toBe("C:\\Users\\flint\\AppData\\Roaming\\flinttrade");
    expect(
      resolveDesktopPaths({
        currentWorkingDirectory: "/checkout/FlintTrade",
        env: {},
        homeDirectory: "/home/flint",
        platform: "linux",
      }).workspace,
    ).toBe("/home/flint/.flinttrade");
  });

  it("honours workspace overrides without creating anything", () => {
    const untouched = join("/tmp", `flinttrade-path-test-${process.pid}-${Date.now()}`);
    expect(existsSync(untouched)).toBe(false);

    const paths = resolveDesktopPaths({
      currentWorkingDirectory: "/checkout/FlintTrade",
      env: { FLINTTRADE_WORKSPACE_DIR: untouched },
      homeDirectory: "/Users/flint",
      platform: "darwin",
    });

    expect(paths.workspace).toBe(untouched);
    expect(paths.logs).toBe(join(untouched, "logs"));
    expect(existsSync(untouched)).toBe(false);
  });

  it.each([
    {
      env: { FLINTTRADE_WORKSPACE_DIR: "relative/workspace" },
      expected: "/checkout/FlintTrade/relative/workspace",
      label: "relative workspace override",
    },
    {
      env: { FLINTTRADE_WORKSPACE_DIR: "  relative workspace  " },
      expected: "/checkout/FlintTrade/  relative workspace  ",
      label: "whitespace-bearing workspace override",
    },
    {
      env: { FLINTTRADE_WORKSPACE_DIR: "", FLINTTRADE_HOME: "relative/home" },
      expected: "/checkout/FlintTrade/relative/home",
      label: "empty workspace override falling through to FLINTTRADE_HOME",
    },
    {
      env: { FLINTTRADE_WORKSPACE_DIR: "", FLINTTRADE_HOME: "" },
      expected: "/Users/flint/Library/Application Support/flinttrade",
      label: "empty overrides falling through to the platform default",
    },
    {
      env: { FLINTTRADE_WORKSPACE_DIR: " ", FLINTTRADE_HOME: "/ignored" },
      expected: "/checkout/FlintTrade/ ",
      label: "whitespace-only workspace override remaining truthy",
    },
    {
      env: { FLINTTRADE_WORKSPACE_DIR: "", FLINTTRADE_HOME: " " },
      expected: "/checkout/FlintTrade/ ",
      label: "whitespace-only FLINTTRADE_HOME remaining truthy",
    },
    {
      env: { FLINTTRADE_WORKSPACE_DIR: "~/workspace" },
      expected: "/Users/flint/workspace",
      label: "POSIX current-user expansion",
    },
    {
      env: { FLINTTRADE_WORKSPACE_DIR: "~" },
      expected: "/Users/flint",
      label: "bare current-user expansion",
    },
  ])("matches the Python resolver for $label", ({ env, expected }) => {
    expect(
      resolveDesktopPaths({
        currentWorkingDirectory: "/checkout/FlintTrade",
        env,
        homeDirectory: "/Users/flint",
        platform: "darwin",
      }).workspace,
    ).toBe(expected);
  });

  it("does not treat a Windows-shaped tilde path as home-relative on POSIX", () => {
    expect(() =>
      resolveDesktopPaths({
        currentWorkingDirectory: "/checkout/FlintTrade",
        env: { FLINTTRADE_WORKSPACE_DIR: "~\\sandbox" },
        homeDirectory: "/Users/flint",
        platform: "darwin",
      }),
    ).toThrow("Could not determine home directory");
  });

  it("expands both Windows separator forms and preserves Python APPDATA fallbacks", () => {
    const inputs = {
      currentWorkingDirectory: "C:\\checkout\\FlintTrade",
      homeDirectory: "C:\\Users\\flint",
      platform: "win32" as const,
    };

    expect(resolveDesktopPaths({ ...inputs, env: { FLINTTRADE_WORKSPACE_DIR: "~\\sandbox" } }).workspace).toBe(
      "C:\\Users\\flint\\sandbox",
    );
    expect(resolveDesktopPaths({ ...inputs, env: { FLINTTRADE_WORKSPACE_DIR: "~/sandbox" } }).workspace).toBe(
      "C:\\Users\\flint\\sandbox",
    );
    expect(resolveDesktopPaths({ ...inputs, env: { APPDATA: "" } }).workspace).toBe(
      "C:\\Users\\flint\\AppData\\Roaming\\flinttrade",
    );
    expect(resolveDesktopPaths({ ...inputs, env: { APPDATA: " " } }).workspace).toBe(" \\flinttrade");
    expect(resolveDesktopPaths({ ...inputs, env: { APPDATA: "relative\\appdata" } }).workspace).toBe(
      "relative\\appdata\\flinttrade",
    );
  });
});
