#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { lstatSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(packageRoot, "..", "..", "..");
const packageManager = JSON.parse(readFileSync(path.join(repositoryRoot, "package.json"), "utf8")).packageManager;
const expected = /^pnpm@(\d+\.\d+\.\d+)\+/.exec(packageManager)?.[1];
if (!expected) throw new Error("The repository packageManager must pin an exact pnpm version and integrity.");

const npmExecPath = process.env.npm_execpath;
if (!npmExecPath || !path.isAbsolute(npmExecPath)) {
  throw new Error("Run Electron packaging through the repository-pinned pnpm command.");
}
const pinnedPnpm = realpathSync(npmExecPath);
if (!lstatSync(pinnedPnpm).isFile()) throw new Error("The invoking pnpm entrypoint is not an ordinary file.");
const versionProbe = spawnSync(process.execPath, [pinnedPnpm, "--version"], { encoding: "utf8" });
if (versionProbe.status !== 0 || versionProbe.stdout.trim() !== expected) {
  throw new Error(`Electron packaging requires the invoking pnpm ${expected} entrypoint.`);
}

const shimDirectory = mkdtempSync(path.join(os.tmpdir(), "flinttrade-pinned-pnpm-"));
try {
  if (process.platform === "win32") {
    const runner = path.join(shimDirectory, "pinned-pnpm.cjs");
    writeFileSync(
      runner,
      `const { spawnSync } = require("node:child_process");\n` +
        `const result = spawnSync(process.execPath, [${JSON.stringify(pinnedPnpm)}, ...process.argv.slice(2)], { stdio: "inherit" });\n` +
        `process.exit(result.status ?? 1);\n`,
      { mode: 0o700 },
    );
    writeFileSync(
      path.join(shimDirectory, "pnpm.cmd"),
      `@"${process.execPath}" "${runner}" %*\r\n`,
      { mode: 0o700 },
    );
  } else {
    if ((lstatSync(pinnedPnpm).mode & 0o111) === 0) {
      throw new Error("The invoking pnpm entrypoint is not executable.");
    }
    symlinkSync(pinnedPnpm, path.join(shimDirectory, "pnpm"));
  }

  const require = createRequire(import.meta.url);
  const builder = require.resolve("electron-builder/cli.js");
  const result = spawnSync(process.execPath, [builder, ...process.argv.slice(2)], {
    env: {
      ...process.env,
      PATH: `${shimDirectory}${path.delimiter}${process.env.PATH ?? ""}`,
    },
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} finally {
  rmSync(shimDirectory, { force: true, recursive: true });
}
