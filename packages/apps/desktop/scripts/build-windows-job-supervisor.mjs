#!/usr/bin/env node

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { lstatSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform === "win32") {
  const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const source = path.join(desktop, "native", "windows-job-supervisor", "Program.cs");
  const output = path.join(desktop, "dist", "native", "win32-x64", "flinttrade-job-supervisor.exe");
  const windowsDirectory = process.env.WINDIR;
  assert.ok(windowsDirectory && path.win32.isAbsolute(windowsDirectory), "WINDIR must identify an absolute trusted Windows directory.");
  const compiler = path.win32.join(windowsDirectory, "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe");
  for (const [label, target] of [
    ["Windows Job supervisor source", source],
    ["trusted .NET Framework x64 compiler", compiler],
  ]) {
    const metadata = lstatSync(target);
    assert.ok(metadata.isFile() && !metadata.isSymbolicLink(), `${label} must be a no-follow regular file: ${target}`);
  }
  mkdirSync(path.dirname(output), { recursive: true });
  execFileSync(
    compiler,
    [
      "/nologo",
      "/target:exe",
      "/platform:x64",
      "/optimize+",
      "/checked+",
      "/warn:4",
      "/warnaserror+",
      `/out:${output}`,
      source,
    ],
    { stdio: "inherit", windowsHide: true },
  );
}
