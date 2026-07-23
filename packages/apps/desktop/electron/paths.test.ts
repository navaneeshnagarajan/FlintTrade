import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import path, { basename, dirname, join } from "node:path";

import { describe, expect, it } from "vitest";

import { canonicalisePathComponents, resolveDesktopPaths } from "./paths";

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

    const canonicalUntouched = join(realpathSync.native(dirname(untouched)), basename(untouched));
    expect(paths.workspace).toBe(canonicalUntouched);
    expect(paths.logs).toBe(join(canonicalUntouched, "logs"));
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

  it.runIf(process.platform !== "win32")(
    "canonicalises existing symlink components exactly like Python Path.resolve",
    () => {
      const root = mkdtempSync(join(tmpdir(), "flinttrade-path-parity-"));
      try {
        const realHome = join(root, "real-home");
        const linkedHome = join(root, "linked-home");
        mkdirSync(realHome);
        symlinkSync(realHome, linkedHome, "dir");
        const override = join(linkedHome, "missing", "workspace");
        const pythonResolved = execFileSync(
          "python3",
          ["-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())", override],
          { encoding: "utf8" },
        ).trim();

        const resolved = resolveDesktopPaths({
          currentWorkingDirectory: root,
          env: { FLINTTRADE_WORKSPACE_DIR: override },
          homeDirectory: linkedHome,
          platform: process.platform,
        });

        expect(resolved.workspace).toBe(pythonResolved);
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    },
  );

  it.runIf(process.platform !== "win32")(
    "matches Python when dot-dot follows absolute and relative symlinks and missing suffixes",
    () => {
      const root = mkdtempSync(join(tmpdir(), "flinttrade-path-dotdot-parity-"));
      try {
        const base = join(root, "base");
        const realChild = join(root, "real", "child");
        mkdirSync(base, { recursive: true });
        mkdirSync(realChild, { recursive: true });
        symlinkSync(realChild, join(base, "absolute-link"), "dir");
        symlinkSync("../real/child", join(base, "relative-link"), "dir");
        symlinkSync(join(base, "relative-link"), join(base, "chained-link"), "dir");

        for (const candidate of [
          `${join(base, "absolute-link")}/../workspace/missing`,
          `${join(base, "relative-link")}/../workspace/missing`,
          `${join(base, "chained-link")}/../workspace/missing`,
        ]) {
          const pythonResolved = execFileSync(
            "python3",
            ["-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())", candidate],
            { encoding: "utf8" },
          ).trim();
          expect(canonicalisePathComponents(candidate, path.posix)).toBe(pythonResolved);
        }
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    },
  );

  it.runIf(process.platform !== "win32")(
    "matches Python for dangling relative and absolute links and literal POSIX backslashes",
    () => {
      const root = mkdtempSync(join(tmpdir(), "flinttrade-path-dangling-parity-"));
      try {
        const base = join(root, "base");
        const literalBackslash = join(base, "literal\\component");
        mkdirSync(base, { recursive: true });
        mkdirSync(literalBackslash);
        symlinkSync("missing/child", join(base, "dangling-relative"));
        symlinkSync(join(root, "absolute-missing", "child"), join(base, "dangling-absolute"));

        for (const candidate of [
          `${join(base, "dangling-relative")}/../workspace`,
          `${join(base, "dangling-absolute")}/../workspace`,
          `${literalBackslash}/../workspace`,
        ]) {
          const pythonResolved = execFileSync(
            "python3",
            ["-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=False))", candidate],
            { encoding: "utf8" },
          ).trim();
          expect(canonicalisePathComponents(candidate, path.posix)).toBe(pythonResolved);
        }
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    },
  );

  it.runIf(process.platform !== "win32")("resolves a filesystem symlink loop exactly like Python without unbounded traversal", () => {
    const root = mkdtempSync(join(tmpdir(), "flinttrade-path-loop-parity-"));
    try {
      const first = join(root, "first");
      const second = join(root, "second");
      symlinkSync("second", first);
      symlinkSync("first", second);
      const candidate = join(first, "workspace");
      const pythonResolved = execFileSync(
        "python3",
        ["-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=False))", candidate],
        { encoding: "utf8", stdio: "pipe" },
      ).trim();
      expect(canonicalisePathComponents(candidate, path.posix)).toBe(pythonResolved);
    } finally {
      rmSync(root, { force: true, recursive: true });
    }
  });

  it.runIf(process.platform !== "win32")("follows one legitimate symlink again after leaving its traversal chain", () => {
    const root = mkdtempSync(join(tmpdir(), "flinttrade-path-repeated-link-"));
    try {
      const target = join(root, "real", "child");
      const link = join(root, "link");
      mkdirSync(target, { recursive: true });
      symlinkSync(target, link, "dir");
      const candidate = `${link}/../../link/workspace`;
      const pythonResolved = execFileSync(
        "python3",
        ["-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=False))", candidate],
        { encoding: "utf8" },
      ).trim();

      expect(canonicalisePathComponents(candidate, path.posix)).toBe(pythonResolved);
    } finally {
      rmSync(root, { force: true, recursive: true });
    }
  });

  it("keeps deterministic Windows component semantics when host junction resolution is unavailable", () => {
    const observed: string[] = [];
    const resolved = canonicalisePathComponents("C:\\base\\junction\\..\\workspace\\missing", path.win32, {
      lstat: (candidate) => {
        observed.push(candidate);
        if (candidate === "C:\\base\\junction") return { isSymbolicLink: () => true };
        if (candidate === "C:\\" || candidate === "C:\\base" || candidate === "D:\\") {
          return { isSymbolicLink: () => false };
        }
        return null;
      },
      readlink: (candidate) => (candidate === "C:\\base\\junction" ? "D:\\real\\child" : candidate),
      realpath: (candidate) => candidate,
    });

    expect(resolved).toBe("D:\\real\\workspace\\missing");
    expect(observed).toContain("C:\\base\\junction");
  });

  it.runIf(process.platform !== "win32")(
    "rejects POSIX named-user overrides before any filesystem mutation",
    () => {
      const root = join(tmpdir(), `flinttrade-named-user-${process.pid}-${Date.now()}`);
      expect(existsSync(root)).toBe(false);

      expect(() =>
        resolveDesktopPaths({
          currentWorkingDirectory: root,
          env: { FLINTTRADE_WORKSPACE_DIR: "~root/flinttrade-workspace" },
          homeDirectory: join(root, "home"),
          platform: process.platform,
        }),
      ).toThrow("Named-user home paths are not supported");

      expect(existsSync(root)).toBe(false);
    },
  );

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
