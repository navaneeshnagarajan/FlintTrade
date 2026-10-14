import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

const roots: string[] = [];
const version = "12.11.2";
const packageManager = `pnpm@${version}+sha512.${"a".repeat(128)}`;
function fixture() {
  const root = mkdtempSync(path.join(tmpdir(), "flinttrade-packager-"));
  roots.push(root);
  const desktop = path.join(root, "packages/apps/desktop");
  const runner = path.join(desktop, "scripts/run-electron-builder.mjs");
  const output = path.join(root, "builder.json");
  mkdirSync(path.dirname(runner), { recursive: true });
  copyFileSync(path.resolve(import.meta.dirname, "../scripts/run-electron-builder.mjs"), runner);
  writeFileSync(path.join(root, "package.json"), JSON.stringify({ packageManager }));
  const builder = path.join(desktop, "node_modules/electron-builder");
  mkdirSync(builder, { recursive: true });
  writeFileSync(path.join(builder, "package.json"), '{"name":"electron-builder","version":"0.0.0"}');
  writeFileSync(path.join(builder, "cli.js"), `
    const fs = require("node:fs");
    const path = require("node:path");
    fs.writeFileSync(${JSON.stringify(output)}, JSON.stringify({
      args: process.argv.slice(2), shim: process.env.PATH.split(path.delimiter)[0]
    }));
    process.exit(Number(process.env.BUILDER_EXIT || 0));
  `);
  const invoke = (entry?: string, extra: Record<string, string> = {}) => {
    const env = { ...process.env, ...extra };
    delete env.npm_execpath;
    if (entry !== undefined) env.npm_execpath = entry;
    return spawnSync(process.execPath, [runner, "--publish", "never", "argument with spaces"], {
      cwd: desktop, env, encoding: "utf8",
    });
  };
  return { root, output, invoke };
}

afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { force: true, recursive: true }); });

describe("pinned packaging manager dispatch", () => {
  it.runIf(process.platform !== "win32")("executes a native-style pnpm entrypoint directly and removes its shim", () => {
    const test = fixture();
    const entry = path.join(test.root, "pnpm");
    writeFileSync(entry, `#!/bin/sh\nprintf '%s\\n' '${version}'\n`, { mode: 0o755 });
    const result = test.invoke(entry);
    expect(result.status, result.stderr).toBe(0);
    const receipt = JSON.parse(readFileSync(test.output, "utf8"));
    expect(receipt.args).toEqual(["--publish", "never", "argument with spaces"]);
    expect(existsSync(receipt.shim)).toBe(false);
  });

  it("retains JavaScript manager entrypoint support and builder failure status", () => {
    const test = fixture();
    const entry = path.join(test.root, "pnpm.cjs");
    writeFileSync(entry, `console.log(${JSON.stringify(version)});\n`, { mode: 0o755 });
    const result = test.invoke(entry, { BUILDER_EXIT: "37" });
    expect(result.status, result.stderr).toBe(37);
    const receipt = JSON.parse(readFileSync(test.output, "utf8"));
    expect(existsSync(receipt.shim)).toBe(false);
  });

  it.each(["absent", "relative", "directory", "wrong-version", "failed-probe", "malformed-pin"])(
    "refuses %s before the builder runs", (kind) => {
      const test = fixture();
      let entry: string | undefined = path.join(test.root, "pnpm.cjs");
      writeFileSync(entry, kind === "failed-probe" ? "process.exit(9);" : `console.log('${kind === "wrong-version" ? "10.34.5" : version}');`, { mode: 0o755 });
      if (kind === "absent") entry = undefined;
      if (kind === "relative") entry = "./pnpm.cjs";
      if (kind === "directory") entry = test.root;
      if (kind === "malformed-pin") writeFileSync(path.join(test.root, "package.json"), JSON.stringify({ packageManager: `pnpm@${version}+not-an-integrity` }));
      const result = test.invoke(entry);
      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/repository-pinned|ordinary file|invoking pnpm|integrity/);
      expect(existsSync(test.output)).toBe(false);
    },
  );
});
